"""Katman 3 — LLM tabanlı çıkarım.

⚠️ LLM YALNIZCA KURALIN ÇÖZEMEDİĞİ ALANLAR İÇİN ÇALIŞIR. `already_found`
kümesi prompt'tan ve şemadan ÇIKARILIR. Bu bir hız iyileştirmesi değil,
doğruluk kararıdır: şartname 5.6'daki `%2,05` = `% 2.05` = `2.05 %` dönüşümü
regex ile %100 doğrulukla çözülüyor. Aynı alanı bir de modele sormak, kesin
bir sonucu olasılıklı bir sonuçla değiştirme riski taşır. Yan faydası çıktı
token'ının yarıya inmesidir.

⚠️ İSTENEN ALAN KALMADIYSA MODELE HİÇ ÇAĞRI YAPILMAZ. Boş bir şemayla çağrı
yapmak, yerel modelde kampanya başına saniyeler demektir; 495 kampanyada
saatlere çıkar.

⚠️ MODEL HATASI KAMPANYAYI DÜŞÜRÜR, ÇALIŞTIRMAYI DEĞİL. Bozuk JSON bir kez
yeniden denenir; yine bozuksa o kampanyada LLM atlanır ve KURAL SONUÇLARI
KORUNUR. Zaman aşımı ve servis yokluğunda da aynı: yarım kalmış bir çalıştırma,
495 kampanyanın 400'ünü işledikten sonra çökmekten iyidir.

⚠️ BU DOSYA MockProvider İLE TAM OLARAK TEST EDİLEBİLİR. Gerçek modele dair
hiçbir varsayım yoktur — SPRINT 3B'de `LocalProvider` takılınca kod
değişmeyecek.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from sqlalchemy.orm import Session

from app.ai.cache import cached_generate
from app.ai.chunking import chunk_for_llm
from app.ai.extraction.rule_based import ExtractedField
from app.ai.fields import EXTRACTABLE_FIELDS, build_extraction_schema, unit_of
from app.ai.prompts import load_prompt
from app.ai.providers.base import (
    LLMInvalidJSONError,
    LLMProvider,
    LLMProviderError,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

# LLM çıkarımının taban güveni. Tablo 1.00, kural 0.90, LLM 0.70 —
# merger (KAPI A7) çakışmada bu sıraya göre karar verir.
LLM_CONFIDENCE: Final[Decimal] = Decimal("0.70")

# Bozuk JSON'da kaç kez yeniden denenir (ilk deneme hariç).
JSON_RETRY: Final[int] = 1

# Modelin ürettiği kanıt bu uzunluğun altındaysa ofset araması yapılmaz:
# iki üç karakterlik bir dize metnin her yerinde eşleşir ve kanıt
# doğrulamasını anlamsızlaştırır.
MIN_EVIDENCE_CHARS: Final[int] = 8


@dataclass
class LLMExtractionResult:
    """LLM katmanının çıktısı ve çalıştırma sayaçları."""

    fields: list[ExtractedField] = field(default_factory=list)
    llm_calls: int = 0
    cache_hits: int = 0
    # Model hatası yüzünden bu kampanyada LLM atlandıysa doldurulur.
    skipped_reason: str | None = None


def _locate(evidence: str, clean_text: str) -> tuple[int, int] | None:
    """Kanıtın kaynak metindeki karakter aralığını bulur.

    İki aşama: birebir arama, sonra boşluk farklarına dayanıklı arama.
    Model çoğu zaman metni doğru kopyalar ama satır sonlarını boşluğa
    çevirebilir; bu tek fark yüzünden doğru bir kanıtı reddetmek, guard'ı
    aşırı katı yapar.

    ⚠️ TAM EŞLEŞME BULUNAMAZSA None DÖNER. Yaklaşık bir aralık uydurmak,
    "bu değer nereden geldi?" sorusuna yanlış yeri göstermek olurdu.

    Args:
        evidence: Modelin ürettiği kanıt.
        clean_text: Kaynak metin.

    Returns:
        (başlangıç, bitiş) ya da bulunamazsa None.
    """
    if len(evidence) < MIN_EVIDENCE_CHARS:
        return None

    bas = clean_text.find(evidence)
    if bas != -1:
        return bas, bas + len(evidence)

    # Boşluk toleranslı arama: kanıtın kelimeleri sırayla ve aralarında
    # yalnızca boşluk olacak şekilde geçiyor mu?
    kelimeler = evidence.split()
    if not kelimeler:
        return None

    imlec = clean_text.find(kelimeler[0])
    while imlec != -1:
        son = imlec
        eslesti = True
        for kelime in kelimeler:
            bulundu = clean_text.find(kelime, son)
            if bulundu == -1 or clean_text[son:bulundu].strip():
                eslesti = False
                break
            son = bulundu + len(kelime)
        if eslesti:
            return imlec, son
        imlec = clean_text.find(kelimeler[0], imlec + 1)

    return None


def _to_field(alan_adi: str, deger: Any, kanit: str, clean_text: str) -> ExtractedField | None:
    """Model çıktısındaki bir alanı `ExtractedField`e çevirir.

    ⚠️ DEĞER YOKSA ALAN ÜRETİLMEZ. `null` dönmek modelin DOĞRU davranışıdır
    (bilgi yok); onu boş bir kayda çevirmek "sistem bir şey buldu ama boş"
    izlenimi yaratır ve doğru susma oranını bozar.

    ⚠️ KANIT ZORUNLUDUR (§8.1 katman 2). Kanıtsız değer reddedilir.

    Args:
        alan_adi: Alan adı.
        deger: Modelin ürettiği değer.
        kanit: Modelin ürettiği kanıt.
        clean_text: Kaynak metin.

    Returns:
        Çıkarım kaydı; değer ya da kanıt yoksa None.
    """
    if deger is None or deger == "":
        return None

    kanit_metni = (kanit or "").strip()
    if not kanit_metni:
        return None

    aralik = _locate(kanit_metni, clean_text)
    if aralik is None:
        # ⚠️ KAYIT ATILMAZ. Kaynakta bulunmayan kanıt bir halüsinasyon
        # adayıdır; guard (KAPI A7) reddedecek ve `rejected_reason` ile
        # saklayacak. Burada sessizce atmak, halüsinasyon oranını sıfır
        # gösterirdi — ölçülmeyen bir hata düzeltilemez.
        return ExtractedField(
            field_name=alan_adi,
            value_raw=kanit_metni,
            value_normalized=str(deger),
            unit=unit_of(alan_adi),
            evidence_text=kanit_metni,
            evidence_char_start=None,
            evidence_char_end=None,
            confidence=LLM_CONFIDENCE,
            method="llm",
            validation_note="kanıt kaynakta bulunamadı",
        )

    bas, son = aralik
    return ExtractedField(
        field_name=alan_adi,
        value_raw=clean_text[bas:son],
        value_normalized=str(deger),
        unit=unit_of(alan_adi),
        evidence_text=clean_text[bas:son],
        evidence_char_start=bas,
        evidence_char_end=son,
        confidence=LLM_CONFIDENCE,
        method="llm",
    )


def _parse_payload(
    parsed: dict[str, Any] | None, istenen: list[str], clean_text: str
) -> list[ExtractedField]:
    """Model yanıtını çıkarım kayıtlarına çevirir.

    ⚠️ İSTENMEYEN ALAN YOK SAYILIR. Model şemada olmayan bir alan üretirse
    bu bir uydurmadır; kaydedilirse `already_found` filtresi anlamsızlaşır.
    """
    if not parsed:
        return []

    bulunan: list[ExtractedField] = []
    for alan_adi in istenen:
        ham = parsed.get(alan_adi)
        if not isinstance(ham, dict):
            continue
        alan = _to_field(alan_adi, ham.get("value"), ham.get("evidence") or "", clean_text)
        if alan is not None:
            bulunan.append(alan)
    return bulunan


def _merge(parcalar: list[list[ExtractedField]]) -> list[ExtractedField]:
    """Parça sonuçlarını birleştirir: alan başına İLK DOLU değer.

    ⚠️ Uzun metin bölündüğünde aynı alan birden çok parçada bulunabilir.
    İlkini almak, metnin başındaki tanım cümlesini sondaki hariç tutma
    listesine tercih etmek demektir; kampanyanın kendi değeri baştadır.
    """
    secilen: dict[str, ExtractedField] = {}
    for parca in parcalar:
        for alan in parca:
            secilen.setdefault(alan.field_name, alan)
    return list(secilen.values())


async def extract_llm(
    provider: LLMProvider,
    session: Session,
    clean_text: str,
    campaign: Any,
    already_found: set[str],
    *,
    prompt_version: str,
    use_cache: bool = True,
) -> LLMExtractionResult:
    """Kuralın çözemediği alanları modele sorar.

    Args:
        provider: LLM sağlayıcısı.
        session: Veritabanı oturumu (önbellek için).
        clean_text: Kampanyanın temiz metni.
        campaign: Kampanya kaydı (günlükleme için).
        already_found: Tablo ve kural katmanının ÇÖZDÜĞÜ alanlar.
        prompt_version: Etkin prompt sürümü.
        use_cache: False ise önbellek okunmaz (`--yeniden`).

    Returns:
        Çıkarım kayıtları ve sayaçlar. Model hatasında `skipped_reason` dolar
        ve `fields` boş kalır — kural sonuçları çağıranda korunur.
    """
    istenen = [alan for alan in EXTRACTABLE_FIELDS if alan not in already_found]
    if not istenen:
        # ⚠️ MODELE HİÇ ÇAĞRI YAPILMAZ.
        logger.debug("llm_atlandi_alan_kalmadi", kampanya_id=getattr(campaign, "id", None))
        return LLMExtractionResult()

    parcalar = chunk_for_llm(clean_text)
    if not parcalar:
        return LLMExtractionResult()

    sema = build_extraction_schema(istenen)
    sistem = load_prompt("system", prompt_version)
    sonuclar: list[list[ExtractedField]] = []
    cagri = 0
    isabet = 0

    for parca in parcalar:
        istem = load_prompt(
            "extract",
            prompt_version,
            requested_fields=", ".join(istenen),
            clean_text=parca,
        )

        yanit = None
        for deneme in range(JSON_RETRY + 1):
            try:
                yanit = await cached_generate(
                    provider,
                    session,
                    text=istem,
                    task="extract",
                    prompt_version=prompt_version,
                    use_cache=use_cache,
                    system=sistem,
                    schema=sema,
                )
                break
            except LLMInvalidJSONError as exc:
                if deneme < JSON_RETRY:
                    logger.warning(
                        "llm_bozuk_json_yeniden",
                        kampanya_id=getattr(campaign, "id", None),
                        hata=str(exc),
                    )
                    continue
                # ⚠️ ÇÖKME YOK: bu kampanyada LLM atlanır, kural sonuçları kalır.
                logger.warning("llm_bozuk_json_atlandi", kampanya_id=getattr(campaign, "id", None))
                return LLMExtractionResult(
                    llm_calls=cagri, cache_hits=isabet, skipped_reason="invalid_json"
                )
            except LLMProviderError as exc:
                # Zaman aşımı ve servis yokluğu: kampanya atlanır, çalıştırma sürer.
                logger.warning(
                    "llm_saglayici_hatasi",
                    kampanya_id=getattr(campaign, "id", None),
                    hata=f"{type(exc).__name__}: {exc}",
                )
                return LLMExtractionResult(
                    llm_calls=cagri,
                    cache_hits=isabet,
                    skipped_reason=type(exc).__name__,
                )

        if yanit is None:  # pragma: no cover - yukarıdaki dallar hepsini kapsar
            continue

        cagri += 1
        if yanit.from_cache:
            isabet += 1
        sonuclar.append(_parse_payload(yanit.parsed, istenen, clean_text))

    return LLMExtractionResult(fields=_merge(sonuclar), llm_calls=cagri, cache_hits=isabet)
