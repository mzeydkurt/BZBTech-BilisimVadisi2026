"""Gold set örnekleme ve etiket kaydı.

GOLD SET NEDİR: Bir insanın kampanya metnini okuyup doğru cevapları elle
yazdığı CEVAP ANAHTARI. Sistemin çıktısı buna karşı ölçülür. Sistem kendi
cevap anahtarını üretemez — üretirse her ölçümde %100 alır.

⚠️ ÖRNEKLEM DETERMİNİSTİKTİR (`random.Random(42)`). Aynı veritabanında aynı
kayıtlar seçilir; aksi hâlde iki değerlendirme çalıştırması farklı kümeler
üzerinde ölçüm yapar ve F1 değerleri karşılaştırılamaz.

⚠️ ZOR VAKALAR AYRI SEÇİLİR VE AYRI RAPORLANIR. Kolay kayıtlarla ortalanan bir
F1, sistemin gerçek zayıf noktalarını gizler: "tarihi olmayan kampanyada tarih
uydurmuyor mu?" sorusu ancak zor vaka alt kümesinde yanıtlanır.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.prompts import contains_few_shot_example
from app.db.models import Bank, Campaign, CampaignCategory, GoldAnnotation, SourceDocument

# Hedefler (SPRINT 3A §4).
TARGET_SIZE: Final[int] = 100
MIN_DIFFICULT: Final[int] = 35
BLIND_COUNT: Final[int] = 30
MIN_PER_BANK: Final[int] = 6
MIN_PER_PRODUCT_TYPE: Final[int] = 4

# ⚠️ Örneklem tohumu SABİT: yinelenebilirlik ölçümün ön koşuludur.
SAMPLE_SEED: Final[int] = 42

# Kısa metin de bir zor vakadır: çıkarılacak bilgi neredeyse yoktur ve
# sistemin "bilgi yok" demesi beklenir.
SHORT_TEXT_CHARS: Final[int] = 400

# Dolaylı ifadeler: sayı vermeden değer ima ederler. Etiketleyicinin en çok
# yanıldığı yer burasıdır ("avantajlı kâr payı" 0 DEĞİLDİR, bilinmeyendir).
INDIRECT_PHRASES: Final[tuple[str, ...]] = (
    "vade farksız",
    "peşin fiyatına",
    "masrafsız",
    "avantajlı kâr payı",
    "ücret alınmaz",
    "dosya masrafı alınma",
)

# Kademeli ödül: "5.000 TL ve üzeri ... 10.000 TL ve üzeri ...".
TIERED_RE: Final[re.Pattern[str]] = re.compile(r"ve üzeri", re.IGNORECASE)

# Saat bilgili tarih (Dünya Katılım): "15 Haziran 2026 saat 00.01".
TIME_IN_DATE_RE: Final[re.Pattern[str]] = re.compile(r"saat\s*\d{1,2}[.:]\d{2}", re.IGNORECASE)

# Birden fazla oran ya da tutar aynı metinde: hangisinin hangi kaleme ait
# olduğu belirsizleşir.
RATE_RE: Final[re.Pattern[str]] = re.compile(r"%\s*\d")
AMOUNT_RE: Final[re.Pattern[str]] = re.compile(r"\d[\d.]*\s*(?:TL|₺)", re.IGNORECASE)


@dataclass(frozen=True)
class GoldCandidate:
    """Örnekleme adayı: kampanya ve zorluk gerekçesi."""

    campaign_id: int
    bank_code: str
    title: str
    source_url: str
    clean_text: str
    product_types: tuple[str, ...]
    difficulty_reasons: tuple[str, ...]

    @property
    def is_difficult(self) -> bool:
        """En az bir zorluk gerekçesi var mı?"""
        return bool(self.difficulty_reasons)


@dataclass
class SampleResult:
    """Örnekleme özeti."""

    candidates: list[GoldCandidate] = field(default_factory=list)
    total_available: int = 0
    excluded_few_shot: int = 0
    excluded_empty_text: int = 0

    @property
    def difficult_count(self) -> int:
        """Zor vaka sayısı."""
        return sum(1 for aday in self.candidates if aday.is_difficult)

    @property
    def by_bank(self) -> Counter[str]:
        """Banka bazında dağılım."""
        return Counter(aday.bank_code for aday in self.candidates)

    @property
    def by_product_type(self) -> Counter[str]:
        """Ürün türü bazında dağılım (bir kampanya birden çok tür taşıyabilir)."""
        sayac: Counter[str] = Counter()
        for aday in self.candidates:
            sayac.update(aday.product_types or ("(etiketsiz)",))
        return sayac


def _difficulty_reasons(bank_code: str, text: str, has_date: bool) -> tuple[str, ...]:
    """Kampanyanın neden zor vaka olduğunu belirler.

    Args:
        bank_code: Banka kodu.
        text: Temizlenmiş metin.
        has_date: Kampanyada tarih çıkarılabilmiş mi?

    Returns:
        Gerekçeler; kolay vakada boş demet.
    """
    gerekceler: list[str] = []

    # ⚠️ Türkiye Finans'ın HİÇBİR kampanyasında tarih yok. Sistemin bu
    # kayıtlarda tarih UYDURMAMASI gerekir; ölçümün can alıcı noktası.
    if not has_date:
        gerekceler.append("tarih verisi yok")

    if len(text) < SHORT_TEXT_CHARS:
        gerekceler.append("kısa/eksik metin")

    if len(TIERED_RE.findall(text)) >= 2:
        gerekceler.append("kademeli ödül yapısı")

    dolayli = [ifade for ifade in INDIRECT_PHRASES if ifade in text.casefold()]
    if dolayli:
        gerekceler.append(f"dolaylı ifade: {dolayli[0]}")

    if TIME_IN_DATE_RE.search(text):
        gerekceler.append("saat bilgili tarih")

    if len(RATE_RE.findall(text)) >= 2:
        gerekceler.append("birden fazla oran")
    elif len(AMOUNT_RE.findall(text)) >= 3:
        gerekceler.append("birden fazla tutar")

    del bank_code  # Zorluk metinden türetilir; banka adı ön yargı yaratmasın.
    return tuple(gerekceler)


def collect_candidates(session: Session) -> tuple[list[GoldCandidate], int, int]:
    """Etiketlenebilir tüm kampanyaları zorluk bilgisiyle toplar.

    Returns:
        (adaylar, few-shot nedeniyle elenen, metni boş olduğu için elenen).
    """
    satirlar = session.execute(
        select(
            Campaign.id,
            Bank.code,
            Campaign.title,
            Campaign.source_url,
            Campaign.start_date,
            Campaign.end_date,
            SourceDocument.clean_text,
        )
        .join(Bank, Bank.id == Campaign.bank_id)
        .outerjoin(SourceDocument, Campaign.source_document_id == SourceDocument.id)
        .order_by(Campaign.id)
    ).all()

    # Ürün türü etiketleri tek sorguda toplanır (kampanya başına sorgu atılmaz).
    turler: dict[int, list[str]] = defaultdict(list)
    for kampanya_id, deger in session.execute(
        select(CampaignCategory.campaign_id, CampaignCategory.value).where(
            CampaignCategory.axis == "product_type"
        )
    ):
        turler[kampanya_id].append(deger)

    adaylar: list[GoldCandidate] = []
    few_shot = 0
    bos_metin = 0

    for kimlik, banka, baslik, url, baslangic, bitis, metin in satirlar:
        if not metin or not metin.strip():
            bos_metin += 1
            continue
        # ⚠️ SIZINTI KORUMASI: few-shot örneği olarak modele gösterilen metin,
        # aynı zamanda test kaydı OLAMAZ.
        if contains_few_shot_example(metin):
            few_shot += 1
            continue

        adaylar.append(
            GoldCandidate(
                campaign_id=kimlik,
                bank_code=banka,
                title=baslik,
                source_url=url,
                clean_text=metin,
                product_types=tuple(sorted(turler.get(kimlik, ()))),
                difficulty_reasons=_difficulty_reasons(
                    banka, metin, has_date=bool(baslangic or bitis)
                ),
            )
        )

    return adaylar, few_shot, bos_metin


def _take(
    havuz: list[GoldCandidate], secilen: dict[int, GoldCandidate], adet: int
) -> list[GoldCandidate]:
    """Havuzdan henüz seçilmemiş `adet` kadar aday alır."""
    alinan: list[GoldCandidate] = []
    for aday in havuz:
        if len(alinan) >= adet:
            break
        if aday.campaign_id not in secilen:
            alinan.append(aday)
            secilen[aday.campaign_id] = aday
    return alinan


def sample_gold_set(
    session: Session,
    *,
    size: int = TARGET_SIZE,
    seed: int = SAMPLE_SEED,
) -> SampleResult:
    """Dengeli ve zor vaka ağırlıklı bir gold set örneklemi seçer.

    Seçim sırası (her adım bir öncekini bozmadan tamamlar):
      1. Her bankadan en az `MIN_PER_BANK` kayıt — tek bankaya yığılma olmasın
      2. Her ürün türünden en az `MIN_PER_PRODUCT_TYPE` kayıt
      3. Zor vaka sayısı `MIN_DIFFICULT`e çıkarılır
      4. Kalan kontenjan rastgele doldurulur

    Args:
        session: Veritabanı oturumu.
        size: Hedef kayıt sayısı.
        seed: Karıştırma tohumu (yinelenebilirlik için sabit).

    Returns:
        Seçilen adaylar ve dağılım özeti.
    """
    adaylar, few_shot, bos_metin = collect_candidates(session)
    rastgele = random.Random(seed)
    karistirilmis = adaylar[:]
    rastgele.shuffle(karistirilmis)

    secilen: dict[int, GoldCandidate] = {}

    # 1. Banka dengesi — zor vakalar önce denenir ki kota onlarla dolsun.
    banka_havuzu: dict[str, list[GoldCandidate]] = defaultdict(list)
    for aday in karistirilmis:
        banka_havuzu[aday.bank_code].append(aday)
    for havuz in banka_havuzu.values():
        havuz.sort(key=lambda a: not a.is_difficult)
        _take(havuz, secilen, MIN_PER_BANK)

    # 2. Ürün türü dengesi.
    tur_havuzu: dict[str, list[GoldCandidate]] = defaultdict(list)
    for aday in karistirilmis:
        for tur in aday.product_types:
            tur_havuzu[tur].append(aday)
    for havuz in tur_havuzu.values():
        mevcut = sum(1 for a in secilen.values() if havuz[0].product_types[0] in a.product_types)
        if mevcut < MIN_PER_PRODUCT_TYPE:
            _take(havuz, secilen, MIN_PER_PRODUCT_TYPE - mevcut)

    # 3. Zor vaka kotası.
    zor_eksik = MIN_DIFFICULT - sum(1 for a in secilen.values() if a.is_difficult)
    if zor_eksik > 0:
        _take([a for a in karistirilmis if a.is_difficult], secilen, zor_eksik)

    # 4. Kalan kontenjan.
    if len(secilen) < size:
        _take(karistirilmis, secilen, size - len(secilen))

    # ⚠️ Kota adımları hedefi aşabilir (10 banka × 6 = 60 taban). Kırpma
    # yapılırken ZOR VAKALAR KORUNUR: kolay kayıtlar önce atılır.
    sonuc = list(secilen.values())
    if len(sonuc) > size:
        sonuc.sort(key=lambda a: not a.is_difficult)
        sonuc = sonuc[:size]

    # Sıra deterministik olsun: kör/ön-doldurmalı ayrımı sıraya göre yapılıyor.
    sonuc.sort(key=lambda a: a.campaign_id)
    rastgele.shuffle(sonuc)

    return SampleResult(
        candidates=sonuc,
        total_available=len(adaylar),
        excluded_few_shot=few_shot,
        excluded_empty_text=bos_metin,
    )


def annotation_method(index: int) -> str:
    """Örneklemdeki sıraya göre etiketleme yöntemini belirler.

    ⚠️ İLK `BLIND_COUNT` KAYIT KÖRDÜR. Ön-doldurma hızlandırır ama yanlılık
    yaratır: sistemin cevabını gören etiketleyici ona meyleder ve F1 sahte
    şişer. Kör alt küme, bu yanlılığın ölçülebilmesi için ayrılır.

    Args:
        index: Örneklemdeki sıra (0 tabanlı).

    Returns:
        `blind` | `assisted`.
    """
    return "blind" if index < BLIND_COUNT else "assisted"


def load_sample(path: Path) -> list[dict[str, Any]]:
    """Diske yazılmış gold örneklemini okur.

    Args:
        path: `gold_sample.jsonl` yolu.

    Returns:
        Sıraya göre kayıtlar; dosya yoksa boş liste.
    """
    if not path.is_file():
        return []
    satirlar: list[dict[str, Any]] = [
        json.loads(satir)
        for satir in path.read_text(encoding="utf-8").splitlines()
        if satir.strip()
    ]
    return sorted(satirlar, key=lambda k: int(k.get("order", 0)))


@dataclass
class GoldProgress:
    """Etiketleme ilerlemesi."""

    annotated_campaigns: int = 0
    total_annotations: int = 0
    blind_campaigns: int = 0
    assisted_campaigns: int = 0
    difficult_campaigns: int = 0
    explicit_null_fields: int = 0


def gold_progress(session: Session) -> GoldProgress:
    """Etiketleme ilerlemesini özetler.

    ⚠️ `explicit_null_fields` AYRI SAYILIR: "metinde yok" diye işaretlenmiş
    alanlar, halüsinasyon ölçümünün paydasıdır. Hiç etiketlenmemiş alanla
    karıştırılamaz.
    """
    kampanya_sayisi = (
        session.scalar(select(func.count(func.distinct(GoldAnnotation.campaign_id)))) or 0
    )
    toplam = session.scalar(select(func.count()).select_from(GoldAnnotation)) or 0

    def _kampanya_sayisi_ile(yontem: str) -> int:
        return (
            session.scalar(
                select(func.count(func.distinct(GoldAnnotation.campaign_id))).where(
                    GoldAnnotation.method == yontem
                )
            )
            or 0
        )

    zor = (
        session.scalar(
            select(func.count(func.distinct(GoldAnnotation.campaign_id))).where(
                GoldAnnotation.is_difficult.is_(True)
            )
        )
        or 0
    )
    bos = (
        session.scalar(
            select(func.count())
            .select_from(GoldAnnotation)
            .where(GoldAnnotation.gold_value.is_(None))
        )
        or 0
    )

    return GoldProgress(
        annotated_campaigns=kampanya_sayisi,
        total_annotations=toplam,
        blind_campaigns=_kampanya_sayisi_ile("blind"),
        assisted_campaigns=_kampanya_sayisi_ile("assisted"),
        difficult_campaigns=zor,
        explicit_null_fields=bos,
    )


def campaign_key(bank_code: str, external_slug: str) -> str:
    """Gold ve kart kayıtlarının KARARLI kimliğini üretir.

    `campaign_id` autoincrement olduğu için veri yeniden kazındığında değişir;
    bu anahtar değişmez ve yeniden bağlamanın temelidir.

    Args:
        bank_code: Banka kodu.
        external_slug: Kampanyanın slug'ı.

    Returns:
        `"{bank_code}:{external_slug}"`.
    """
    return f"{bank_code}:{external_slug}"
