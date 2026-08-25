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
    # Sayma sorusunda banka bazında döküm. ⚠️ SIFIR sayılı bankalar da
    # bulunur (bkz. `compute`, `tum_bankalar`): "veri yok" bilgisi de bir
    # bulgudur ve gizlenmez.
    by_bank: dict[str, int] | None = None
    # Yokluk / banka sayımı sorularında kümeler (banka ADLARI, sıralı).
    banks_with: tuple[str, ...] = ()
    banks_without: tuple[str, ...] = ()
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


def compute(
    docs: list[CampaignDoc],
    spec: AggregateSpec,
    *,
    tum_bankalar: tuple[str, ...] = (),
) -> AggregateAnswer:
    """Toplama sorusunu süzgeçten geçmiş TÜM kayıtlar üzerinde hesaplar.

    Args:
        docs: Sert süzgeci geçen kampanyaların tamamı (örneklem DEĞİL).
        spec: `parse_query()` içinden gelen hesap tarifi.
        tum_bankalar: Banka EVRENİ (adlar). Yokluk ve banka sayımı sorularında
            zorunludur: kaydı olmayan banka `docs` içinde hiç görünmez, bu
            yüzden yalnızca `docs`a bakan bir hesap "hangi bankada X yok?"
            sorusunu YANITLAYAMAZ. Boş geçilirse yokluk kümesi boş döner ve
            bu durum çağıran katmanda görünür kalır.

    Returns:
        Hesaplanmış yanıt. Değeri olan kayıt yoksa `winner=None` döner ve
        `without_value` kaç kaydın veri taşımadığını bildirir.
    """
    if spec.kind in {"count", "count_banks", "absence"}:
        dokum: dict[str, int] = {}
        for doc in docs:
            dokum[doc.bank_name] = dokum.get(doc.bank_name, 0) + 1

        # ⚠️ Sıfır sayılı bankalar dökümde KALIR. Ölçüldü: `adil_katilim`
        # 0 kampanyayla dökümde hiç görünmüyordu; CLAUDE.md "veri yok bilgisi
        # de başlı başına bir bulgudur, gizlenmez" diyor.
        for ad in tum_bankalar:
            dokum.setdefault(ad, 0)

        olan = tuple(sorted(ad for ad, n in dokum.items() if n > 0))
        olmayan = tuple(sorted(ad for ad in tum_bankalar if dokum.get(ad, 0) == 0))

        return AggregateAnswer(
            kind=spec.kind,
            total=len(docs),
            with_value=len(olan),
            without_value=len(olmayan),
            by_bank=dict(sorted(dokum.items(), key=lambda ikili: (-ikili[1], ikili[0]))),
            banks_with=olan,
            banks_without=olmayan,
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
    if answer.kind == "count_banks":
        # ⚠️ Sayı SQL'den gelir. Ölçüldü: bu soru daha önce `search`e düşüyor
        # ve modelin kendi ürettiği "iki banka" yanıtı dönüyordu; gerçek 7'ydi.
        if not answer.banks_with:
            return "Bu kriterleri karşılayan banka bulunmuyor."
        adet = len(answer.banks_with)
        liste = ", ".join(answer.banks_with)
        cumle = f"Bu kriterleri {adet} banka karşılıyor: {liste}."
        if answer.banks_without:
            cumle += (
                f" Karşılamayan {len(answer.banks_without)} banka: "
                f"{', '.join(answer.banks_without)}."
            )
        return cumle

    if answer.kind == "absence":
        # ⚠️ Yokluk sorusunun yanıtı, VAR olanların listesi DEĞİLDİR.
        # Ölçüldü: "hangi bankada taşıt finansmanı kampanyası yok" sorusuna
        # taşıt finansmanı oranları listeleniyordu — tam ters yanıt.
        if not answer.banks_without:
            evren = len(answer.banks_with)
            return (
                f"Bu kriterleri karşılamayan banka yok — kapsanan {evren} bankanın "
                "tamamında en az bir kayıt var."
            )
        liste = ", ".join(answer.banks_without)
        return (
            f"Bu kriterleri karşılayan kaydı OLMAYAN {len(answer.banks_without)} banka: "
            f"{liste}. Kaydı olan {len(answer.banks_with)} banka: "
            f"{', '.join(answer.banks_with)}."
        )

    if answer.kind == "count":
        if answer.total == 0:
            return "Bu kriterlere uyan kampanya bulunmuyor."
        dokum = answer.by_bank or {}
        ilk_uc = ", ".join(f"{banka} ({adet})" for banka, adet in list(dokum.items())[:3])
        kuyruk = f" ve {len(dokum) - 3} banka daha" if len(dokum) > 3 else ""
        cumle = f"Bu kriterlere uyan {answer.total} kampanya var: {ilk_uc}{kuyruk}."
        # ⚠️ SIFIR görünür kalır: "veri yok" da bir bulgudur.
        sifirlar = [banka for banka, adet in dokum.items() if adet == 0]
        if sifirlar:
            cumle += f" Hiç kaydı olmayan: {', '.join(sorted(sifirlar))}."
        return cumle

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
