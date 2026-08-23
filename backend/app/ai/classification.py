"""Sınıflandırma boşluk doldurma (KAPI A8).

Kural tabanlı sınıflandırma (SPRINT 2) her ekseni dolduramıyor. Ölçüldü —
495 kampanyada:

    audience etiketi olan       57 / 495     ← en büyük boşluk
    product_type etiketi olan  318 / 495
    sector = 'genel'                164 etiket
    confidence < 0.5                108 etiket

`target_customer` alanının gold set F1'i **0.00**; bu boşluğun doğrudan
sonucudur. LLM'in bu sprintteki görev tanımı tam olarak burasıdır.

⚠️ `confidence=1.0` ETİKETE DOKUNULMAZ. Bu etiketler URL yolundan ya da
bankanın kendi kategori etiketinden gelir — kaynağın kendi beyanıdır ve
olasılıklı bir tahminle değiştirilemez.

⚠️ MEVCUT ETİKETİN ÜZERİNE YAZILMAZ, yeni satır eklenir (`source='llm'`,
`confidence=0.70`). Böylece "bu etiketi kural mı model mi buldu?" sorusu
sonradan yanıtlanabilir ve ablasyon tablosu kurulabilir.

⚠️ SÖZLÜK DIŞI ETİKET REDDEDİLİR. Prompt'a kontrollü liste verilir ama
modelin ona uyacağı GARANTİ DEĞİLDİR; yanıt sözlüğe karşı ayrıca
doğrulanır. Sözlük dışı bir etiket veritabanındaki CHECK kısıtını ihlal
eder ve tüm çalıştırmayı düşürürdü.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.cache import cached_generate
from app.ai.fields import MAX_PROMPT_CHARS
from app.ai.prompts import load_prompt
from app.ai.providers.base import LLMProvider, LLMProviderError
from app.core.normalization.text import ascii_fold_tr
from app.core.taxonomy import AUDIENCES, BENEFITS, PRODUCT_TYPES, SECTORS
from app.db.models import Campaign, CampaignCategory
from app.logging_config import get_logger

logger = get_logger(__name__)

# LLM kaynaklı etiketin güveni. Kural katmanının altında kalır ki
# çakışmada kaynağa dayalı etiket kazansın.
LLM_LABEL_CONFIDENCE: Final[Decimal] = Decimal("0.700")

# Bu güvenin ÜSTÜNDEKİ etiketler dokunulmaz sayılır.
UNTOUCHABLE_CONFIDENCE: Final[Decimal] = Decimal("1.000")

# Bu güvenin ALTINDAKİ etiketler "zayıf" sayılır ve eksen yeniden sorulur.
WEAK_CONFIDENCE: Final[Decimal] = Decimal("0.500")

# Eksen → kontrollü sözlük.
AXIS_VOCAB: Final[dict[str, tuple[str, ...]]] = {
    "product_type": PRODUCT_TYPES,
    "sector": SECTORS,
    "audience": AUDIENCES,
    "benefit": BENEFITS,
}

# ⚠️ `sector='genel'` bir etiket DEĞİL, etiketlenememenin adıdır. Bu değeri
# taşıyan eksen boş sayılır ve modele sorulur.
# `herkes` de öyle: model boş kitleyi buna dolduruyor; gold'da varsayılan
# `mevcut_musteri`. Kanıtsız `herkes` yer tutucudur.
PLACEHOLDER_VALUES: Final[dict[str, frozenset[str]]] = {
    "sector": frozenset({"genel"}),
    "audience": frozenset({"herkes"}),
}

# Kuralın sinyal yokken yazdığı varsayılan. Güveni 0.30 olduğu için eski
# kod bunu "zayıf" sayıp modele tekrar soruyordu; model `herkes` yazıyordu.
FALLBACK_AUDIENCE: Final[str] = "mevcut_musteri"

# `herkes` ancak metin açıkça herkese hitap ediyorsa kabul.
_HERKES_KANIT_RE: Final[re.Pattern[str]] = re.compile(
    r"herkese\s+acik|tum\s+musteriler|herkes\s+icin",
)


@dataclass
class ClassificationResult:
    """Sınıflandırma tamamlamanın çıktısı."""

    added: list[CampaignCategory] = field(default_factory=list)
    requested_axes: list[str] = field(default_factory=list)
    llm_calls: int = 0
    cache_hits: int = 0
    # Sözlük dışı olduğu için reddedilen etiketler: (eksen, değer).
    rejected_labels: list[tuple[str, str]] = field(default_factory=list)
    skipped_reason: str | None = None


def _existing_labels(session: Session, campaign_id: int) -> dict[str, list[CampaignCategory]]:
    """Kampanyanın mevcut etiketlerini eksen bazında döndürür."""
    gruplar: dict[str, list[CampaignCategory]] = {}
    for kayit in session.scalars(
        select(CampaignCategory).where(CampaignCategory.campaign_id == campaign_id)
    ):
        gruplar.setdefault(kayit.axis, []).append(kayit)
    return gruplar


def missing_axes(mevcut: dict[str, list[CampaignCategory]]) -> list[str]:
    """Modele sorulacak eksenleri belirler.

    Bir eksen şu üç durumda istenir:
      1. Hiç etiketi yok
      2. Yalnızca yer tutucu etiketi var (`sector='genel'`)
      3. Tüm etiketleri zayıf (`confidence < 0.5`)

    ⚠️ `confidence=1.0` etiketi olan eksen ASLA istenmez.

    Args:
        mevcut: Eksen → etiket listesi.

    Returns:
        Doldurulacak eksen adları.
    """
    istenen: list[str] = []

    for eksen in AXIS_VOCAB:
        etiketler = mevcut.get(eksen, [])
        if not etiketler:
            istenen.append(eksen)
            continue

        if any(e.confidence >= UNTOUCHABLE_CONFIDENCE for e in etiketler):
            # Kaynağın kendi beyanı; dokunulmaz.
            continue

        yer_tutucular = PLACEHOLDER_VALUES.get(eksen, frozenset())
        anlamli = [e for e in etiketler if e.value not in yer_tutucular]
        if not anlamli:
            istenen.append(eksen)
            continue

        # ⚠️ Varsayılan `mevcut_musteri` zayıf görünür ama gold'un çoğunluğu
        # budur. Tekrar sormak modeli `herkes` yazmaya iter.
        if eksen == "audience" and any(e.value == FALLBACK_AUDIENCE for e in anlamli):
            continue

        if all(e.confidence < WEAK_CONFIDENCE for e in anlamli):
            istenen.append(eksen)

    return istenen


def _herkes_izinli(kanit: str, clean_text: str) -> bool:
    """`herkes` yalnızca metin açıkça herkese hitap ediyorsa kabul."""
    katman = ascii_fold_tr(f"{kanit} {clean_text}")
    return _HERKES_KANIT_RE.search(katman) is not None


def _validate_labels(
    parsed: dict[str, Any] | None,
    istenen: list[str],
    *,
    clean_text: str = "",
) -> tuple[dict[str, list[tuple[str, str]]], list[tuple[str, str]]]:
    """Model yanıtını kontrollü sözlüğe karşı doğrular.

    Returns:
        `(kabul edilen etiketler, reddedilen etiketler)`. Kabul edilenler
        eksen → [(değer, kanıt)] biçimindedir.
    """
    kabul: dict[str, list[tuple[str, str]]] = {}
    red: list[tuple[str, str]] = []

    if not parsed:
        return kabul, red

    for eksen in istenen:
        ham = parsed.get(eksen)
        if not isinstance(ham, list):
            continue
        sozluk = AXIS_VOCAB[eksen]
        for oge in ham:
            if not isinstance(oge, dict):
                continue
            deger = str(oge.get("value") or "").strip()
            kanit = str(oge.get("evidence") or "").strip()
            if not deger:
                continue
            if deger not in sozluk:
                # ⚠️ Sözlük dışı etiket veritabanı kısıtını ihlal eder.
                red.append((eksen, deger))
                continue
            if eksen == "audience" and deger == "herkes" and not _herkes_izinli(kanit, clean_text):
                red.append((eksen, deger))
                continue
            kabul.setdefault(eksen, []).append((deger, kanit))

    return kabul, red


async def complete_classification(
    provider: LLMProvider,
    session: Session,
    campaign: Campaign,
    clean_text: str,
    *,
    prompt_version: str,
    use_cache: bool = True,
) -> ClassificationResult:
    """Kural katmanının dolduramadığı eksenleri modele sorar.

    Args:
        provider: LLM sağlayıcısı.
        session: Veritabanı oturumu.
        campaign: Sınıflandırılacak kampanya.
        clean_text: Kampanyanın temiz metni.
        prompt_version: Etkin prompt sürümü.
        use_cache: False ise önbellek okunmaz.

    Returns:
        Eklenen etiketler ve sayaçlar. Doldurulacak eksen yoksa modele
        HİÇ çağrı yapılmaz.
    """
    mevcut = _existing_labels(session, campaign.id)
    istenen = missing_axes(mevcut)
    if not istenen:
        return ClassificationResult()

    mevcut_ozet = {
        eksen: [e.value for e in etiketler] for eksen, etiketler in mevcut.items() if etiketler
    }

    istem = load_prompt(
        "classify",
        prompt_version,
        mevcut_etiketler=mevcut_ozet or "{}",
        istenen_eksenler=", ".join(istenen),
        product_type_sozlugu=", ".join(PRODUCT_TYPES),
        sector_sozlugu=", ".join(SECTORS),
        audience_sozlugu=", ".join(AUDIENCES),
        benefit_sozlugu=", ".join(BENEFITS),
        # ⚠️ Sınıflandırmada metin BÖLÜNMEZ; tek çağrıda karar verilir.
        # Bölünmüş parçalar birbirinden habersiz etiket üretir ve aynı
        # kampanya iki farklı sektöre atanabilir.
        clean_text=clean_text[:MAX_PROMPT_CHARS],
    )

    sema = {
        "type": "object",
        "properties": {
            eksen: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "value": {"type": "string"},
                        "evidence": {"type": ["string", "null"]},
                    },
                    "required": ["value", "evidence"],
                },
            }
            for eksen in istenen
        },
    }

    try:
        yanit = await cached_generate(
            provider,
            session,
            text=istem,
            task="classify",
            prompt_version=prompt_version,
            use_cache=use_cache,
            system=load_prompt("system", prompt_version),
            schema=sema,
        )
    except LLMProviderError as exc:
        # ⚠️ Model hatası kampanyayı düşürür, çalıştırmayı değil.
        logger.warning(
            "siniflandirma_atlandi",
            kampanya_id=campaign.id,
            hata=f"{type(exc).__name__}: {exc}",
        )
        return ClassificationResult(requested_axes=istenen, skipped_reason=type(exc).__name__)

    kabul, red = _validate_labels(yanit.parsed, istenen, clean_text=clean_text)
    if red:
        logger.warning("sozluk_disi_etiket_reddedildi", kampanya_id=campaign.id, etiketler=red)

    # Aynı (kampanya, eksen, değer) üçlüsü benzersizdir; tekrar eklenmez.
    var_olanlar = {(e.axis, e.value) for etiketler in mevcut.values() for e in etiketler}

    eklenen: list[CampaignCategory] = []
    for eksen, degerler in kabul.items():
        for deger, kanit in degerler:
            if (eksen, deger) in var_olanlar:
                continue
            var_olanlar.add((eksen, deger))
            kayit = CampaignCategory(
                campaign_id=campaign.id,
                axis=eksen,
                value=deger,
                confidence=LLM_LABEL_CONFIDENCE,
                source="llm",
                evidence=kanit or None,
            )
            session.add(kayit)
            eklenen.append(kayit)

    return ClassificationResult(
        added=eklenen,
        requested_axes=istenen,
        llm_calls=1,
        cache_hits=1 if yanit.from_cache else 0,
        rejected_labels=red,
    )
