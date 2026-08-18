"""Kampanya taksonomisinin veritabanına uygulanması.

⚠️ AĞA ÇIKMAZ. Sınıflandırma tamamen kayıtlı veriden üretilir; sözlük her
genişletildiğinde bankalara yeniden istek atmak gerekmez. Bu, hem etik kazıma
kuralının hem de "sözlüğü geliştirerek `genel` oranını düşür" döngüsünün ön
şartıdır.

⚠️ TEKRAR ÇALIŞTIRILABİLİR. Her çalıştırmada kampanyanın önceki etiketleri
silinip yeniden yazılır. Aksi hâlde sözlükten çıkarılan bir kelimenin ürettiği
etiket veritabanında sonsuza dek kalırdı.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.taxonomy import FALLBACK_SECTOR
from app.db.models import Bank, Campaign, CampaignCategory
from app.logging_config import get_logger
from app.processing.categorizer import categorize

logger = get_logger(__name__)


@dataclass
class TaxonomyResult:
    """Sınıflandırma çalıştırmasının özeti."""

    campaigns: int = 0
    labels: int = 0
    by_axis: Counter[str] = field(default_factory=Counter)
    by_source: Counter[str] = field(default_factory=Counter)
    by_value: dict[str, Counter[str]] = field(default_factory=dict)
    fallback_only: int = 0
    """Yalnızca `sector='genel'` alan kampanya sayısı."""

    missing_product_type: int = 0

    @property
    def fallback_ratio(self) -> float:
        """Sektörü çıkarılamayan kampanyaların oranı."""
        return self.fallback_only / self.campaigns if self.campaigns else 0.0


def categorize_campaigns(session: Session, *, bank_code: str | None = None) -> TaxonomyResult:
    """Kampanyaları sınıflandırır ve `campaign_categories`'i yeniden yazar.

    Args:
        session: Veritabanı oturumu.
        bank_code: Yalnızca bu bankayı sınıflandır; verilmezse tümü.

    Returns:
        Çalıştırma özeti.
    """
    statement = select(Campaign)
    if bank_code:
        statement = statement.join(Bank, Campaign.bank_id == Bank.id).where(Bank.code == bank_code)

    sonuc = TaxonomyResult()

    for campaign in session.scalars(statement):
        etiketler = categorize(
            title=campaign.title,
            description=campaign.description,
            conditions_text=campaign.conditions_text,
            # ⚠️ Kampanyaların %46'sında `conditions_text` boş; gövde metni
            # olmadan yalnızca başlıktan sınıflandırılıyorlardı.
            body_text=campaign.source_document.clean_text if campaign.source_document else None,
            source_url=campaign.source_url,
            bank_category=campaign.bank_category,
        )

        # ⚠️ Önce sil: sözlükten çıkan bir kelimenin etiketi kalmasın.
        session.execute(delete(CampaignCategory).where(CampaignCategory.campaign_id == campaign.id))

        for etiket in etiketler:
            session.add(
                CampaignCategory(
                    campaign_id=campaign.id,
                    axis=etiket.axis,
                    value=etiket.value,
                    source=etiket.source,
                    confidence=etiket.confidence,
                    evidence=etiket.evidence,
                )
            )
            sonuc.by_axis[etiket.axis] += 1
            sonuc.by_source[etiket.source] += 1
            sonuc.by_value.setdefault(etiket.axis, Counter())[etiket.value] += 1

        sonuc.campaigns += 1
        sonuc.labels += len(etiketler)

        sektorler = [e for e in etiketler if e.axis == "sector"]
        if len(sektorler) == 1 and sektorler[0].value == FALLBACK_SECTOR:
            sonuc.fallback_only += 1
        if not any(e.axis == "product_type" for e in etiketler):
            sonuc.missing_product_type += 1

    session.commit()

    logger.info(
        "siniflandirma_bitti",
        kampanya=sonuc.campaigns,
        etiket=sonuc.labels,
        genel_orani=round(sonuc.fallback_ratio, 3),
        urun_turu_yok=sonuc.missing_product_type,
    )
    return sonuc


def build_report(sonuc: TaxonomyResult) -> str:
    """Sınıflandırma sonucundan Markdown rapor üretir.

    Args:
        sonuc: `categorize_campaigns()` çıktısı.

    Returns:
        `docs/taxonomy_report.md` içeriği.
    """
    satirlar: list[str] = [
        "# Kampanya Taksonomisi Raporu",
        "",
        "> `python dev.py siniflandir` ile üretilir. Sınıflandırma tamamen kural",
        "> tabanlı ve deterministiktir; yapay zekâ çıkarımı kullanılmaz.",
        "",
        "## Özet",
        "",
        f"- Sınıflandırılan kampanya: **{sonuc.campaigns}**",
        f"- Üretilen etiket: **{sonuc.labels}**",
        f"- Kampanya başına ortalama etiket: **{sonuc.labels / sonuc.campaigns:.1f}**"
        if sonuc.campaigns
        else "- —",
        f"- Sektörü çıkarılamayan (`genel`): **{sonuc.fallback_only}** "
        f"(%{100 * sonuc.fallback_ratio:.1f})",
        f"- Ürün türü etiketi olmayan: **{sonuc.missing_product_type}**",
        "",
        "## Kanıt kaynağına göre dağılım",
        "",
        "| Kaynak | Etiket | Açıklama |",
        "|---|---|---|",
    ]

    aciklama = {
        "url": "Adres yolundaki kategori — bankanın kendi verisi",
        "bank_category": "Bankanın kendi kategori etiketi",
        "merchant": "Marka sözlüğü eşleşmesi",
        "keyword": "Anahtar kelime eşleşmesi",
    }
    for kaynak, adet in sonuc.by_source.most_common():
        satirlar.append(f"| `{kaynak}` | {adet} | {aciklama.get(kaynak, '—')} |")

    satirlar += ["", "## Eksen × değer", ""]
    for eksen in ("product_type", "sector", "audience", "benefit"):
        degerler = sonuc.by_value.get(eksen)
        if not degerler:
            continue
        satirlar += [
            f"### `{eksen}` ({sonuc.by_axis[eksen]} etiket)",
            "",
            "| Değer | Kampanya |",
            "|---|---|",
        ]
        satirlar += [f"| `{deger}` | {adet} |" for deger, adet in degerler.most_common()]
        satirlar.append("")

    return "\n".join(satirlar)
