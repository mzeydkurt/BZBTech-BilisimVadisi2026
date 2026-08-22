"""Getirilen kanıttan Türkçe yanıt üretir ve üretileni denetler.

MODELİN ÜRETTİĞİ HİÇBİR SAYI DENETİMSİZ GEÇMEZ. Yanıt metnindeki her
rakam, atıf verilen kampanyanın kartında ya da `campaign_metrics` satırında
bulunmak zorundadır. Bulunmuyorsa cümle "doğrulanamadı" işaretiyle döner ve
arayüzde ayrı gösterilir. Bu, `app/ai/validation/` altındaki halüsinasyon
guard'ının aynı ilkesi; yeniden yazılmadı, yeniden kullanıldı.

KART YOKSA MODEL HİÇ ÇAĞRILMAZ. Bağlamı boş bırakıp "yanıt yaz" demek,
modeli kendi parametrik belleğinden uydurmaya davet etmektir — ve uydurduğu
şey banka kampanyası olur. Boş sonuçta şablon reddetme cümlesi döner.

MODEL ERİŞİLEMEZSE SİSTEM ÇÖKMEZ. `LLM_PROVIDER=mock`, airgap kipi ve
Ollama kapalıyken şablon yanıt üretilir; sıralı sonuçlar yine döner. Yanıtın
model tarafından mı şablondan mı geldiği çıktıda bildirilir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.ai.providers.base import LLMProvider, LLMProviderError
from app.ai.validation.terminology import TerminologyWarning, check_terminology
from app.logging_config import get_logger
from app.retrieval.query import QueryPlan
from app.retrieval.search import SearchHit

logger = get_logger(__name__)

# Yanıtta en fazla kaç kart bağlama konur. 4096 token bağlamda 5 kart
# (~1.500 karakter) güvenli sınır; fazlası istemi kırpılma riskine sokar.
MAX_CONTEXT_CARDS: Final[int] = 5

# Modelden istenecek en fazla token. Yanıt 3 cümle olduğu için düşük tutulur;
# yüksek tutmak yavaşlatır ve modeli gevezeliğe iter.
MAX_ANSWER_TOKENS: Final[int] = 320

SYSTEM_PROMPT: Final[str] = (
    "Sen katılım bankacılığı kampanyalarını inceleyen bir analiz asistanısın. "
    "SADECE sana verilen KAYNAK kartlarına dayanarak TÜRKÇE yanıt ver.\n"
    "KURALLAR:\n"
    "1. Kaynakta olmayan hiçbir sayı, tarih, banka adı veya marka yazma.\n"
    "2. Her cümlenin sonuna dayandığın kartın numarasını [N] biçiminde koy. "
    "Sadece köşeli parantez ve sayı; başka işaret yok.\n"
    "3. Kaynakta yanıt yoksa yalnızca şunu yaz: "
    "Bu soruya elimizdeki veriyle yanıt verilemiyor.\n"
    "4. Katılım bankacılığı terimleri kullan: kâr payı (faiz DEĞİL), "
    "finansman (kredi DEĞİL), katılım fonu (mevduat DEĞİL).\n"
    "5. En fazla 3 cümle yaz. Yorum ekleme, tavsiye verme.\n"
    "6. Sadece Türkçe yaz."
)

# Yanıttaki atıf işaretleri: [3], [12] …
_ATIF_RE: Final[re.Pattern[str]] = re.compile(r"\[(\d+)\]")
# Yanıttaki sayılar (yüzde ve binlik ayırıcı dahil).
_SAYI_RE: Final[re.Pattern[str]] = re.compile(r"\d[\d.,]*")
# Kaynakta aranırken göz ardı edilecek kısa sayılar (atıf numaralarıyla
# karışan tek haneliler ve yıl benzeri kısa değerler denetim dışıdır).
MIN_CHECKED_NUMBER_LENGTH: Final[int] = 2


@dataclass(frozen=True)
class UnverifiedNumber:
    """Yanıtta geçen ama kaynakta bulunamayan sayı."""

    value: str
    cited: tuple[int, ...]


@dataclass(frozen=True)
class GeneratedAnswer:
    """Üretilen yanıt ve denetim sonuçları."""

    text: str
    # "model" | "template" | "refusal"
    source: str
    # Yanıtta atıf verilen kampanya kimlikleri (bağlamda gerçekten bulunanlar).
    citations: tuple[int, ...] = ()
    # Kaynakta doğrulanamayan sayılar — arayüzde ayrı gösterilir.
    unverified_numbers: tuple[UnverifiedNumber, ...] = ()
    # Konvansiyonel terim uyarıları (faiz / kredi / mevduat).
    terminology_warnings: tuple[TerminologyWarning, ...] = ()
    # Model çağrısı başarısız olduysa nedeni.
    model_error: str | None = None
    model_name: str | None = None
    latency_ms: int | None = None

    @property
    def is_grounded(self) -> bool:
        """Yanıtın tamamı kaynağa dayanıyor mu?"""
        return not self.unverified_numbers and not self.terminology_warnings


def _baglam(hits: tuple[SearchHit, ...]) -> str:
    """Getirilen kartları numaralı bağlama çevirir.

    Numara olarak `campaign_id` kullanılır: model atıf verdiğinde hangi
    kampanyayı gösterdiği doğrudan çözülür ve arayüzde ilgili satır
    vurgulanabilir. Sıra numarası kullanılsaydı eşleme kaybolurdu.
    """
    parcalar: list[str] = []
    for vurus in hits[:MAX_CONTEXT_CARDS]:
        doc = vurus.doc
        parcalar.append(f"[{doc.campaign_id}] {doc.bank_name} — {doc.card_text.strip()}")
    return "\n\n".join(parcalar)


def _sayilari_dogrula(
    text: str, hits: tuple[SearchHit, ...], citations: tuple[int, ...]
) -> tuple[UnverifiedNumber, ...]:
    """Yanıttaki sayıların kaynakta geçtiğini doğrular.

    ⚠️ ATIF NUMARALARI DENETİM DIŞIDIR. `[496]` ifadesindeki 496 bir veri
    değeri değil, kaynak göstergesidir; kartta geçmediği için "uydurma"
    sayılırsa her yanıt sahte uyarı üretir.

    ⚠️ SAYI, ATIF VERİLEN KARTLARDA ARANIR — TÜM BAĞLAMDA DEĞİL. Model
    [496]'ya atıf verip [497]'nin tutarını yazıyorsa bu da bir hatadır;
    tüm bağlamda arasak fark etmezdik.
    """
    atifsiz = _ATIF_RE.sub(" ", text)
    kart_metni = {vurus.doc.campaign_id: vurus.doc.card_text for vurus in hits}
    # Atıf yoksa tüm bağlam kabul edilir; atıf eksikliği ayrı bir sorundur ve
    # sayıyı iki kez cezalandırmak gereksiz.
    aranacak = [kart_metni[k] for k in citations if k in kart_metni] or list(kart_metni.values())
    havuz = " ".join(aranacak)
    # Sayı biçimi kartta farklı yazılmış olabilir ("5.000" / "5000"); ayırıcılar
    # atılarak karşılaştırılır.
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


def _sablon_yanit(plan: QueryPlan, hits: tuple[SearchHit, ...]) -> str:
    """Model olmadan üretilen yanıt.

    ⚠️ ŞABLON YANIT SAYI ÜRETMEZ, yalnızca ne bulunduğunu sayar. Modelsiz
    kipte "en avantajlı kampanya şu" gibi bir yorum üretmek, hesaplanmamış bir
    iddia olurdu.
    """
    bankalar: list[str] = []
    for vurus in hits:
        if vurus.doc.bank_name not in bankalar:
            bankalar.append(vurus.doc.bank_name)
    banka_metni = ", ".join(bankalar[:4])
    if len(bankalar) > 4:
        banka_metni += f" ve {len(bankalar) - 4} banka daha"
    _ = plan
    return (
        f"Sorgunuzla eşleşen {len(hits)} kampanya bulundu ({banka_metni}). "
        "Ayrıntılar ve kanıt metinleri sağdaki listede; yanıt metni yerel model "
        "kapalı olduğu için üretilmedi."
    )


async def generate_answer(
    plan: QueryPlan,
    hits: tuple[SearchHit, ...],
    *,
    provider: LLMProvider | None,
    forbidden_terms: dict[str, str | None],
) -> GeneratedAnswer:
    """Getirilen kartlardan Türkçe yanıt üretir.

    Args:
        plan: Sorgu planı.
        hits: Erişim sonuçları; boşsa model çağrılmaz.
        provider: LLM sağlayıcısı; `None` ise şablon yanıt döner.
        forbidden_terms: `load_forbidden_terms()` çıktısı.

    Returns:
        Yanıt metni, atıflar ve denetim sonuçları. Model hata verirse
        `source="template"` ve `model_error` dolu döner — istisna YÜKSELMEZ,
        çünkü sıralı sonuçlar hâlâ kullanıcıya gösterilebilir durumda.
    """
    if not hits:
        return GeneratedAnswer(
            text=(
                "Bu soruya elimizdeki veriyle yanıt verilemiyor: sorgu süzgeçlerini "
                "sağlayan kampanya bulunamadı."
            ),
            source="refusal",
        )

    if provider is None:
        return GeneratedAnswer(text=_sablon_yanit(plan, hits), source="template")

    baglam = _baglam(hits)
    istem = f"KAYNAK KARTLARI:\n{baglam}\n\nSORU: {plan.raw}"

    try:
        yanit = await provider.generate(
            istem,
            system=SYSTEM_PROMPT,
            temperature=0.0,
            max_tokens=MAX_ANSWER_TOKENS,
        )
    except LLMProviderError as exc:
        logger.warning("yanit_uretilemedi", hata=str(exc), tip=type(exc).__name__)
        return GeneratedAnswer(
            text=_sablon_yanit(plan, hits),
            source="template",
            model_error=str(exc),
        )

    metin = yanit.text.strip()
    baglam_kimlikleri = {vurus.doc.campaign_id for vurus in hits}
    # ⚠️ Bağlamda OLMAYAN atıf sayılmaz: model kart numarası uydurmuş olabilir.
    atiflar = tuple(
        sorted(
            {
                int(eslesme)
                for eslesme in _ATIF_RE.findall(metin)
                if int(eslesme) in baglam_kimlikleri
            }
        )
    )

    return GeneratedAnswer(
        text=metin,
        source="model",
        citations=atiflar,
        unverified_numbers=_sayilari_dogrula(metin, hits, atiflar),
        terminology_warnings=tuple(check_terminology(metin, forbidden_terms, source_text=baglam)),
        model_name=yanit.model_name,
        latency_ms=yanit.latency_ms,
    )
