"""Getirilen kanıttan Türkçe yanıt üretir ve üretileni denetler.

MODELİN ÜRETTİĞİ HİÇBİR SAYI DENETİMSİZ GEÇMEZ. Yanıt metnindeki her
rakam, atıf verilen kampanyanın kartında ya da `campaign_metrics` satırında
bulunmak zorundadır. Bulunmuyorsa cümle "doğrulanamadı" işaretiyle döner.

KART YOKSA MODEL HİÇ ÇAĞRILMAZ. Boş sonuçta şablon reddetme cümlesi döner.

Guard 5: rate_type yön denetimi · Guard 6: terminoloji düzeltme turu.
Sohbet promptu: `app/ai/prompts/chat_v1.txt` (3B system_v1'e dokunulmaz).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from app.ai.providers.base import LLMProvider, LLMProviderError
from app.ai.validation.terminology import TerminologyWarning, check_terminology
from app.core.rate_direction import avantajli_yon, yon_notu
from app.logging_config import get_logger
from app.retrieval.query import QueryPlan
from app.retrieval.search import SearchHit

logger = get_logger(__name__)

MAX_CONTEXT_CARDS: Final[int] = 5
MAX_ANSWER_TOKENS: Final[int] = 480

_CHAT_PROMPT_PATH: Final[Path] = (
    Path(__file__).resolve().parents[1] / "ai" / "prompts" / "chat_v1.txt"
)

# Yedek — dosya okunamazsa (test ortamı) kullanılacak asgari kurallar.
_FALLBACK_SYSTEM: Final[str] = (
    "Sen Katibim'sin. SADECE KAYNAK kartlarına dayan. "
    "faiz/kredi/mevduat yazma; kâr payı/finansman/katılma hesabı kullan. "
    "Köşeli parantez atıf koyma. Selamı selamla. En fazla 5 cümle."
)

_ATIF_RE: Final[re.Pattern[str]] = re.compile(r"\[(\d+)\]")
_SAYI_RE: Final[re.Pattern[str]] = re.compile(r"\d[\d.,]*")
MIN_CHECKED_NUMBER_LENGTH: Final[int] = 2

# Guard 5 — avantaj değerlendirme ifadeleri.
_AVANTAJ_RE: Final[re.Pattern[str]] = re.compile(
    r"(avantajl[ıi]|daha iyi|daha uygun|daha d[uü][sş][uü]k|daha y[uü]ksek|"
    r"en avantajl[ıi]|en uygun)",
    re.IGNORECASE,
)
_DUSUK_AVANTAJ_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(daha d[uü][sş][uü]k|en d[uü][sş][uü]k|d[uü][sş][uü]k.*avantaj)\b",
    re.IGNORECASE,
)
_YUKSEK_AVANTAJ_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(daha y[uü]ksek|en y[uü]ksek|y[uü]ksek.*avantaj)\b",
    re.IGNORECASE,
)


def _system_prompt() -> str:
    """chat_v1.txt yükler; yoksa yedek."""
    try:
        return _CHAT_PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return _FALLBACK_SYSTEM


@dataclass(frozen=True)
class UnverifiedNumber:
    """Yanıtta geçen ama kaynakta bulunamayan sayı."""

    value: str
    cited: tuple[int, ...]


@dataclass(frozen=True)
class GeneratedAnswer:
    """Üretilen yanıt ve denetim sonuçları."""

    text: str
    # "model" | "template" | "refusal" | "computed"
    source: str
    citations: tuple[int, ...] = ()
    unverified_numbers: tuple[UnverifiedNumber, ...] = ()
    terminology_warnings: tuple[TerminologyWarning, ...] = ()
    model_error: str | None = None
    model_name: str | None = None
    latency_ms: int | None = None
    direction_note: str | None = None

    @property
    def is_grounded(self) -> bool:
        """Yanıtın tamamı kaynağa dayanıyor mu?"""
        return not self.unverified_numbers and not self.terminology_warnings


def _baglam(hits: tuple[SearchHit, ...]) -> str:
    """Getirilen kartları bağlama çevirir — DB id numarası yok."""
    parcalar: list[str] = []
    for sira, vurus in enumerate(hits[:MAX_CONTEXT_CARDS], start=1):
        doc = vurus.doc
        parcalar.append(f"Kart {sira}: {doc.bank_name} — {doc.card_text.strip()}")
    return "\n\n".join(parcalar)


def _sayilari_dogrula(
    text: str, hits: tuple[SearchHit, ...], citations: tuple[int, ...]
) -> tuple[UnverifiedNumber, ...]:
    """Yanıttaki sayıların kaynakta geçtiğini doğrular."""
    atifsiz = _ATIF_RE.sub(" ", text)
    kart_metni = {vurus.doc.campaign_id: vurus.doc.card_text for vurus in hits}
    aranacak = [kart_metni[k] for k in citations if k in kart_metni] or list(kart_metni.values())
    havuz = " ".join(aranacak)
    havuz_sade = re.sub(r"[.,\s]", "", havuz)

    bulunamayan: list[UnverifiedNumber] = []
    gorulen: set[str] = set()
    for eslesme in _SAYI_RE.finditer(atifsiz):
        ham = eslesme.group(0).strip(".,")
        sade = re.sub(r"[.,]", "", ham)
        if len(sade) < MIN_CHECKED_NUMBER_LENGTH or sade in gorulen:
            continue
        gorulen.add(sade)
        if sade not in havuz_sade:
            bulunamayan.append(UnverifiedNumber(value=ham, cited=citations))
    return tuple(bulunamayan)


def _yon_bozuk_mu(text: str, rate_type: str | None) -> bool:
    """Avantaj cümlesi rate_type yönüne aykırı mı?"""
    if not rate_type or not _AVANTAJ_RE.search(text):
        return False
    yon = avantajli_yon(rate_type)
    if yon is None:
        # Karz-ı hasen: avantaj cümlesi kurulmamalı.
        return True
    if yon is False and _YUKSEK_AVANTAJ_RE.search(text):
        # Finansmanda "daha yüksek avantajlı" yanlış.
        return True
    if yon is True and _DUSUK_AVANTAJ_RE.search(text):
        # Getiride "daha düşük avantajlı" yanlış.
        return True
    return False


def _sablon_yanit(plan: QueryPlan, hits: tuple[SearchHit, ...]) -> str:
    """Model olmadan üretilen yanıt — sayı uydurmaz; özetlerden kısa anlatır."""
    _ = plan
    if len(hits) == 1:
        doc = hits[0].doc
        ozet = (doc.summary or "").strip()
        if ozet:
            return f"{doc.bank_name} — {doc.title}: {ozet}"
        return f"{doc.bank_name} kampanyası: {doc.title}."

    parcalar: list[str] = []
    for vurus in hits[:3]:
        doc = vurus.doc
        ozet = (doc.summary or "").strip()
        if ozet:
            parcalar.append(f"{doc.title}: {ozet}")
        else:
            parcalar.append(doc.title)
    bankalar = list(dict.fromkeys(v.doc.bank_name for v in hits))
    banka_metni = ", ".join(bankalar[:3])
    return f"{banka_metni} bünyesinde sorunuza uyan {len(hits)} kampanya var. " + " ".join(parcalar)


async def _model_cagir(
    provider: LLMProvider,
    istem: str,
    *,
    system: str,
) -> tuple[str, str | None, int | None]:
    """Model çağrısı; (metin, model_name, latency_ms)."""
    yanit = await provider.generate(
        istem,
        system=system,
        temperature=0.0,
        max_tokens=MAX_ANSWER_TOKENS,
    )
    return yanit.text.strip(), yanit.model_name, yanit.latency_ms


async def generate_answer(
    plan: QueryPlan,
    hits: tuple[SearchHit, ...],
    *,
    provider: LLMProvider | None,
    forbidden_terms: dict[str, str | None],
    previous_query: str | None = None,
) -> GeneratedAnswer:
    """Getirilen kartlardan Türkçe yanıt üretir.

    Guard 5: ters yönlü avantaj cümlesi → şablon.
    Guard 6: yasaklı terim → tek yeniden yazma turu; yine sızarsa şablon.
    """
    from app.retrieval.relevance import strip_citation_markers

    if not hits:
        return GeneratedAnswer(
            text=(
                "Bu soruya elimizdeki veriyle yanıt verilemiyor: sorgu süzgeçlerini "
                "sağlayan kampanya bulunamadı."
            ),
            source="refusal",
        )

    # Yön notu yalnızca oran karşılaştırmasında.
    direction = yon_notu(plan.rate_type) if plan.rate_type else None

    if provider is None:
        return GeneratedAnswer(
            text=_sablon_yanit(plan, hits),
            source="template",
            direction_note=direction,
        )

    baglam = _baglam(hits)
    onceki = ""
    if previous_query and previous_query.strip() and previous_query.strip() != plan.raw:
        onceki = f"ÖNCEKİ SORU (bağlam): {previous_query.strip()}\n\n"
    istem = f"{onceki}KAYNAK KARTLARI:\n{baglam}\n\nSORU: {plan.raw}"
    system = _system_prompt()

    try:
        metin, model_name, latency = await _model_cagir(provider, istem, system=system)
    except LLMProviderError as exc:
        logger.warning("yanit_uretilemedi", hata=str(exc), tip=type(exc).__name__)
        return GeneratedAnswer(
            text=_sablon_yanit(plan, hits),
            source="template",
            model_error=str(exc),
            direction_note=direction,
        )

    #  Guard 4b — BOŞ YANIT SESSİZCE GEÇMEZ. Model HTTP 200 döndürüp metni
    # boş bırakabiliyor: düşünme kipi açık kaldığında ya da `num_predict`
    # yetersizken üretim bütçesi tükeniyor ve `content` boş geliyor. İstisna
    # fırlatmadığı için yukarıdaki `except` bloğu bunu yakalamıyor; aşağıdaki
    # guard'lar da boş dizeden geçtiği için kullanıcı BOŞ bir yanıt kutusu
    # görüyor. Kullanıcı bunu "model bir şey demedi" diye değil "sistem bozuk"
    # diye okur — oysa sıralı kanıtlar geçerlidir, yalnızca cümle yoktur.
    if not metin.strip():
        logger.warning("model_bos_yanit_dondu", model=model_name)
        return GeneratedAnswer(
            text=_sablon_yanit(plan, hits),
            source="template",
            model_error="Model boş yanıt döndürdü.",
            model_name=model_name,
            latency_ms=latency,
            direction_note=direction,
        )

    # Atıfları UI metninden silmeden önce çıkar (strip sonrası citations boş kalırdı).
    baglam_kimlikleri = {vurus.doc.campaign_id for vurus in hits}
    atiflar = tuple(
        sorted(
            {
                int(eslesme)
                for eslesme in _ATIF_RE.findall(metin)
                if int(eslesme) in baglam_kimlikleri
            }
        )
    )
    metin = strip_citation_markers(metin)

    # Guard 5 — yön denetimi.
    if _yon_bozuk_mu(metin, plan.rate_type):
        logger.info("yon_denetimi_sablona_dustu", rate_type=plan.rate_type)
        return GeneratedAnswer(
            text=_sablon_yanit(plan, hits),
            source="template",
            model_name=model_name,
            latency_ms=latency,
            direction_note=direction,
        )

    # Guard 6 — terminoloji; yalnızca gerçekten yasaklı varsa yeniden yaz.
    uyarilar = check_terminology(metin, forbidden_terms, source_text=baglam)
    if uyarilar:
        yasaklar = ", ".join(sorted({u.term for u in uyarilar}))
        yeniden_istem = (
            f"{istem}\n\nÖNCEKİ YANIT (yasaklı terim içeriyor: {yasaklar}):\n{metin}\n\n"
            "Aynı içeriği katılım bankacılığı terimleriyle, yasaklı sözcükleri "
            "kullanmadan yeniden yaz. Köşeli parantez atıf koyma."
        )
        try:
            metin2, model_name2, latency2 = await _model_cagir(
                provider, yeniden_istem, system=system
            )
            atiflar = (
                tuple(
                    sorted(
                        {
                            int(eslesme)
                            for eslesme in _ATIF_RE.findall(metin2)
                            if int(eslesme) in baglam_kimlikleri
                        }
                    )
                )
                or atiflar
            )
            metin2 = strip_citation_markers(metin2)
            latency = (latency or 0) + (latency2 or 0)
            model_name = model_name2 or model_name
            uyarilar2 = check_terminology(metin2, forbidden_terms, source_text=baglam)
            if uyarilar2 or _yon_bozuk_mu(metin2, plan.rate_type):
                return GeneratedAnswer(
                    text=_sablon_yanit(plan, hits),
                    source="template",
                    terminology_warnings=tuple(uyarilar2 or uyarilar),
                    model_name=model_name,
                    latency_ms=latency,
                    direction_note=direction,
                )
            metin = metin2
            uyarilar = []
        except LLMProviderError:
            return GeneratedAnswer(
                text=_sablon_yanit(plan, hits),
                source="template",
                terminology_warnings=tuple(uyarilar),
                model_name=model_name,
                latency_ms=latency,
                direction_note=direction,
            )

    return GeneratedAnswer(
        text=metin,
        source="model",
        citations=atiflar,
        unverified_numbers=_sayilari_dogrula(metin, hits, atiflar),
        terminology_warnings=tuple(uyarilar),
        model_name=model_name,
        latency_ms=latency,
        direction_note=direction,
    )


# Testlerin yön denetimine doğrudan erişmesi için.
def check_direction(text: str, rate_type: str | None) -> bool:
    """True = yön bozuk (şablona düşmeli)."""
    return _yon_bozuk_mu(text, rate_type)


__all__ = [
    "GeneratedAnswer",
    "UnverifiedNumber",
    "check_direction",
    "generate_answer",
]
