"""Toplama sorularının deterministik yanıtı.

TOPLAMA ERİŞİME GİRMEZ. "En düşük kâr payı hangi bankada?" sorusunda en
benzer 8 kart getirilip modele okutulursa, model yalnızca o 8 kartın en
küçüğünü söyler — 608 kampanyanın gerçek en küçüğünü değil. Yanıt makul
görünür, kaynak da gösterir, ama YANLIŞTIR ve yanlışlığı hiçbir yerde
bildirilmez.

`NULL` "SIFIR" DEĞİLDİR. Kâr payı oranı çıkarılamamış 460 kampanya
hesaba KATILMAZ ve kaç kaydın dışarıda kaldığı yanıtta YAZILIR. Bu, veri
setinin en dürüst rakamı: "en düşük oran %0" cümlesi, 148 kayıt üzerinden mi
608 kayıt üzerinden mi söylendiği bilinmeden değersizdir.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.retrieval.corpus import CampaignDoc
from app.retrieval.query import AggregateSpec

# Alan adı → yanıt cümlesinde kullanılacak Türkçe ifade ve birim.
# Katılım terminolojisi: "kâr payı", "finansman" — asla "faiz"/"kredi".
FIELD_LABELS: dict[str, tuple[str, str]] = {
    "profit_rate_pct": ("kâr payı oranı", "%"),
    "profit_share_rate_pct": ("katılma hesabı kâr payı oranı", "%"),
    "term_months_max": ("vade", " ay"),
    "term_months_min": ("asgari vade", " ay"),
    "installment_count": ("taksit sayısı", ""),
    "financing_amount_max": ("finansman tutarı", " TL"),
    "financing_amount_min": ("asgari finansman tutarı", " TL"),
    "min_spend_try": ("asgari harcama", " TL"),
    "max_spend_try": ("azami harcama", " TL"),
    "reward_amount_try": ("ödül", " TL"),
    "cashback_pct": ("nakit iade oranı", "%"),
    "discount_pct": ("indirim oranı", "%"),
    "loyalty_points": ("puan", ""),
    "max_total_benefit_try": ("azami toplam fayda", " TL"),
}


@dataclass(frozen=True)
class AggregateAnswer:
    """Toplama sorusunun hesaplanmış yanıtı."""

    kind: str
    # Üstünlük sorusunda kazanan kampanya; sayma sorusunda `None`.
    winner: CampaignDoc | None = None
    field: str | None = None
    value: Decimal | None = None
    # Hesaba giren ve girmeyen kayıt sayısı.
    with_value: int = 0
    without_value: int = 0
    total: int = 0
    # Sayma sorusunda banka bazında döküm.
    by_bank: dict[str, int] | None = None
    # Berabere kalan kampanyalar (aynı değeri taşıyanlar), kazanan hariç.
    ties: tuple[CampaignDoc, ...] = ()


def _bicimle(value: Decimal, birim: str) -> str:
    """Sayıyı Türkçe biçimde yazar.

    ⚠️ `Decimal` KORUNUR, `float`a çevrilmez (CLAUDE.md). Yalnızca gösterim
    için dizeye dönüştürülür; ondalık ayırıcı virgül, binlik ayırıcı nokta.
    """
    kirpik = value.normalize()
    # `normalize()` büyük tam sayıları bilimsel gösterime çevirebiliyor
    # (1E+4); bu, kullanıcıya "10000" yerine "1E+4" göstermek olurdu.
    if kirpik == kirpik.to_integral_value():
        metin = f"{int(kirpik):,}".replace(",", ".")
    else:
        metin = f"{kirpik:,f}".rstrip("0").rstrip(".")
        tam, _, ondalik = metin.partition(".")
        metin = f"{tam.replace(',', '.')},{ondalik}" if ondalik else tam.replace(",", ".")
    return f"{birim}{metin}" if birim == "%" else f"{metin}{birim}"


def compute(docs: list[CampaignDoc], spec: AggregateSpec) -> AggregateAnswer:
    """Toplama sorusunu süzgeçten geçmiş TÜM kayıtlar üzerinde hesaplar.

    Args:
        docs: Sert süzgeci geçen kampanyaların tamamı (örneklem DEĞİL).
        spec: `parse_query()` içinden gelen hesap tarifi.

    Returns:
        Hesaplanmış yanıt. Değeri olan kayıt yoksa `winner=None` döner ve
        `without_value` kaç kaydın veri taşımadığını bildirir.
    """
    if spec.kind == "count":
        dokum: dict[str, int] = {}
        for doc in docs:
            dokum[doc.bank_name] = dokum.get(doc.bank_name, 0) + 1
        return AggregateAnswer(
            kind="count",
            total=len(docs),
            by_bank=dict(sorted(dokum.items(), key=lambda ikili: (-ikili[1], ikili[0]))),
        )

    alan = spec.field
    if alan is None:
        return AggregateAnswer(kind="extremum", total=len(docs), without_value=len(docs))

    degerli = [doc for doc in docs if alan in doc.metrics]
    if not degerli:
        return AggregateAnswer(
            kind="extremum",
            field=alan,
            total=len(docs),
            without_value=len(docs),
        )

    ters = spec.direction == "max"
    sirali = sorted(
        degerli,
        key=lambda doc: (doc.metrics[alan], -doc.campaign_id),
        reverse=ters,
    )
    kazanan = sirali[0]
    uc_deger = kazanan.metrics[alan]
    # ⚠️ BERABERLİK GİZLENMEZ. "En düşük kâr payı %0" diyen 60 kampanya varsa
    # bunlardan birini tek kazanan göstermek, diğerlerini yok saymaktır.
    berabere = tuple(doc for doc in sirali[1:] if doc.metrics[alan] == uc_deger)

    return AggregateAnswer(
        kind="extremum",
        winner=kazanan,
        field=alan,
        value=uc_deger,
        with_value=len(degerli),
        without_value=len(docs) - len(degerli),
        total=len(docs),
        ties=berabere,
    )


def describe(answer: AggregateAnswer) -> str:
    """Hesaplanmış yanıtı Türkçe cümleye çevirir.

    ⚠️ BU CÜMLE LLM'E YAZDIRILMAZ. Sayılar hesaplanmış durumda; modele
    yazdırmak yalnızca yanlış aktarma riski ekler. Model bu katmanda hiç
    çağrılmaz (mimari §5).
    """
    if answer.kind == "count":
        if answer.total == 0:
            return "Bu kriterlere uyan kampanya bulunmuyor."
        dokum = answer.by_bank or {}
        ilk_uc = ", ".join(f"{banka} ({adet})" for banka, adet in list(dokum.items())[:3])
        kuyruk = f" ve {len(dokum) - 3} banka daha" if len(dokum) > 3 else ""
        return f"Bu kriterlere uyan {answer.total} kampanya var: {ilk_uc}{kuyruk}."

    if answer.winner is None or answer.field is None or answer.value is None:
        # ⚠️ "Veri yok" ile "sonuç yok" ayrı: kayıt VAR ama o alan çıkarılamamış.
        if answer.without_value:
            return (
                f"Bu kriterlere uyan {answer.total} kampanya var ancak hiçbirinde "
                "bu alan çıkarılamadı; karşılaştırma yapılamıyor."
            )
        return "Bu kriterlere uyan kampanya bulunmuyor."

    etiket, birim = FIELD_LABELS.get(answer.field, (answer.field, ""))
    cumle = (
        f"{etiket.capitalize()} bakımından uç değer {_bicimle(answer.value, birim)} "
        f"ve {answer.winner.bank_name} bankasının "
        f"“{answer.winner.title}” kampanyasına ait."
    )
    if answer.ties:
        cumle += f" Aynı değeri taşıyan {len(answer.ties)} kampanya daha var."
    # ⚠️ KAPSAM HER ZAMAN YAZILIR. 148 kayıt üzerinden söylenen bir uç değer,
    # 608 kayıt üzerinden söylenmiş gibi okunursa yanlış bilgi olur.
    cumle += (
        f" Hesap, bu alanda değeri bulunan {answer.with_value} kampanya üzerinden "
        f"yapıldı; {answer.without_value} kampanyada alan çıkarılamadığı için "
        "hesaba katılmadı."
    )
    return cumle
