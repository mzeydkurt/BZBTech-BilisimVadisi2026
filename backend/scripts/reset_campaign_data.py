"""Kampanya verisini sıfırlar (ağa çıkmaz).

⚠️ VERİ SİLER. Üç güvenlik kilidi vardır ve hiçbiri atlanamaz:
    1. `--onay SIL` yazılmalı
    2. `--export <dizin>` DOĞRULANMIŞ olmalı (`verify_export` damgası)
    3. SQLite dosyası önce `data/backups/` altına kopyalanır

⚠️ `source_documents` VARSAYILAN OLARAK SİLİNMEZ. 344 MB'lık ham HTML arşivi
dururken indeksini silmek, "hangi adres ne zaman hangi özetle çekildi"
kaydını yok eder; biten kampanyalar bankaların sitesinden kalkıyor ve o bilgi
bir daha elde edilemez. Ayrıca indeks kalırsa `dev.py yeniden-isle` ağa
çıkmadan çalışmaya devam eder — geri dönüş noktası bedavaya gelir.

`--banka` ile tek banka sıfırlanabilir; yeniden kazıma banka banka yürütülür
ki bir bankanın erişilemez olması diğerlerinin verisini götürmesin.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    Bank,
    Campaign,
    CampaignCategory,
    CampaignExtraction,
    CampaignMetric,
    Embedding,
    EntityCard,
    GoldAnnotation,
    ScrapeRun,
)
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger

from scripts.verify_export import cozumle_dizin

logger = get_logger(__name__)

BACKUP_DIR = Path("data/backups")

# FK sırası: çocuklar önce.
SILME_SIRASI: tuple[str, ...] = (
    "embeddings",
    "entity_cards",
    "campaign_extractions",
    "campaign_categories",
    "campaign_metrics",
    "campaigns",
    "scrape_runs",
)


@dataclass
class ResetOzeti:
    """Sıfırlama sonucu."""

    yedek: Path | None = None
    silinen: dict[str, int] = field(default_factory=dict)
    kuru: bool = False


def _yedek_al(database_url: str) -> Path | None:
    """SQLite dosyasını kopyalar (taşımaz, silmez).

    Args:
        database_url: Ayarlardaki bağlantı adresi.

    Returns:
        Yedek dosyanın yolu; SQLite değilse None.
    """
    onek = "sqlite:///"
    if not database_url.startswith(onek):
        logger.warning("yedek_atlandi", neden="SQLite değil", url=database_url)
        return None

    kaynak = Path(get_settings().sqlalchemy_url[len(onek) :])
    if not kaynak.exists():
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    zaman = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    hedef = BACKUP_DIR / f"{zaman}_pre_reset.sqlite3"
    shutil.copy2(kaynak, hedef)
    return hedef


def sifirla(
    session: Session,
    *,
    export_dizini: Path,
    banka: str | None = None,
    kapsam: str = "kampanya",
    gold_sil: bool = False,
    kuru: bool = False,
) -> ResetOzeti:
    """Kampanya tablolarını boşaltır.

    Args:
        session: Veritabanı oturumu.
        export_dizini: Doğrulanmış dışa aktarma dizini.
        banka: Yalnızca bu banka kodu; None ise tümü.
        kapsam: `kampanya` (varsayılan) veya `tam` (+ source_documents).
        gold_sil: True ise gold etiketleri de silinir. VARSAYILAN FALSE —
            880 satırlık elle etiketleme işi kazara silinmesin.
        kuru: True ise yalnızca sayar, silmez.

    Returns:
        Sıfırlama özeti.

    Raises:
        PermissionError: Dışa aktarma doğrulanmamışsa.
    """
    from scripts.verify_export import dogrulanmis_mi

    if not dogrulanmis_mi(export_dizini):
        raise PermissionError(
            f"Dışa aktarma doğrulanmamış: {export_dizini}. "
            "Önce: python dev.py disa-aktar-dogrula --dizin <dizin>"
        )

    ozeti = ResetOzeti(kuru=kuru)

    bank_id: int | None = None
    if banka is not None:
        bank_id = session.scalar(select(Bank.id).where(Bank.code == banka))
        if bank_id is None:
            raise ValueError(f"Banka bulunamadı: {banka}")

    kampanya_idleri = list(
        session.scalars(
            select(Campaign.id).where(Campaign.bank_id == bank_id)
            if bank_id is not None
            else select(Campaign.id)
        )
    )

    ozeti.silinen = {
        "campaigns": len(kampanya_idleri),
        "campaign_extractions": _say(session, CampaignExtraction, kampanya_idleri),
        "campaign_categories": _say(session, CampaignCategory, kampanya_idleri),
        "campaign_metrics": _say(session, CampaignMetric, kampanya_idleri),
        # Polimorfik kayıtlar: yalnızca kampanya türündekiler.
        "entity_cards (campaign)": _say_polimorfik(session, EntityCard, kampanya_idleri),
        "embeddings (campaign)": _say_polimorfik(session, Embedding, kampanya_idleri),
        "scrape_runs": _say_scrape_runs(session, bank_id),
    }
    if gold_sil:
        ozeti.silinen["gold_annotations"] = _say_gold(session, kampanya_idleri)

    if kuru:
        return ozeti

    if not kampanya_idleri:
        logger.info("silinecek_kampanya_yok", banka=banka)
        return ozeti

    if gold_sil:
        # ⚠️ SIRA ÖNEMLİ: kampanyalardan ÖNCE. `gold_annotations.campaign_id`
        # FK'si `SET NULL` olduğu için kampanyalar önce silinirse bağ kopar ve
        # bu sorgu hiçbir satır bulamaz.
        #
        # Elle etiketleme işi; yalnızca açık `--gold-sil` ile ve doğrulanmış
        # dışa aktarma varken silinir. Dosyada kararlı anahtarla duruyor.
        logger.warning("gold_etiketleri_siliniyor", banka=banka)
        session.execute(
            delete(GoldAnnotation).where(GoldAnnotation.campaign_id.in_(kampanya_idleri))
        )

    # Polimorfik kayıtlar FK taşımıyor; elle temizlenir.
    session.execute(
        delete(EntityCard).where(
            EntityCard.entity_type == "campaign", EntityCard.entity_id.in_(kampanya_idleri)
        )
    )
    session.execute(
        delete(Embedding).where(
            Embedding.entity_type == "campaign", Embedding.entity_id.in_(kampanya_idleri)
        )
    )
    # `campaigns` CASCADE ile metrik/kategori/çıkarımı da götürür.
    session.execute(delete(Campaign).where(Campaign.id.in_(kampanya_idleri)))
    session.execute(
        delete(ScrapeRun).where(ScrapeRun.bank_id == bank_id)
        if bank_id is not None
        else delete(ScrapeRun)
    )

    if kapsam == "tam":
        # ⚠️ Ham HTML dosyaları SİLİNMEZ; yalnızca indeks kaydı düşer.
        logger.warning("source_documents_siliniyor", banka=banka)
        session.execute(text("DELETE FROM source_documents"))

    session.commit()
    return ozeti


def _say(session: Session, model: type, kampanya_idleri: list[int]) -> int:
    """Kampanyalara bağlı satır sayısını döndürür."""
    from sqlalchemy import func

    if not kampanya_idleri:
        return 0
    return (
        session.scalar(
            select(func.count()).select_from(model).where(model.campaign_id.in_(kampanya_idleri))
        )
        or 0
    )


def _say_polimorfik(session: Session, model: type, kampanya_idleri: list[int]) -> int:
    """Polimorfik tabloda kampanya türündeki satır sayısını döndürür."""
    from sqlalchemy import func

    if not kampanya_idleri:
        return 0
    return (
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.entity_type == "campaign", model.entity_id.in_(kampanya_idleri))
        )
        or 0
    )


def _say_gold(session: Session, kampanya_idleri: list[int]) -> int:
    """Silinecek gold etiketi sayısını döndürür."""
    from sqlalchemy import func

    if not kampanya_idleri:
        return 0
    return (
        session.scalar(
            select(func.count())
            .select_from(GoldAnnotation)
            .where(GoldAnnotation.campaign_id.in_(kampanya_idleri))
        )
        or 0
    )


def _say_scrape_runs(session: Session, bank_id: int | None) -> int:
    """Silinecek kazıma çalıştırması sayısını döndürür."""
    from sqlalchemy import func

    sorgu = select(func.count()).select_from(ScrapeRun)
    if bank_id is not None:
        sorgu = sorgu.where(ScrapeRun.bank_id == bank_id)
    return session.scalar(sorgu) or 0


def main(argv: list[str] | None = None) -> int:
    """Sıfırlamayı çalıştırır."""
    parser = argparse.ArgumentParser(
        prog="reset_campaign_data", description="Kampanya verisini sıfırlar (VERİ SİLER)."
    )
    parser.add_argument("--export", required=True, help="Doğrulanmış dışa aktarma dizini")
    parser.add_argument("--onay", help="Silmek için 'SIL' yazın")
    parser.add_argument("--banka", help="Yalnızca bu banka")
    parser.add_argument(
        "--kapsam",
        choices=("kampanya", "tam"),
        default="kampanya",
        help="'tam' source_documents'i de siler (ÖNERİLMEZ)",
    )
    parser.add_argument(
        "--gold-sil",
        action="store_true",
        help="Gold etiketlerini de sil (VARSAYILAN HAYIR — elle etiketleme işi)",
    )
    parser.add_argument("--kuru", action="store_true", help="Ne silineceğini yazar, silmez")
    args = parser.parse_args(argv)
    configure_logging()

    if not args.kuru and args.onay != "SIL":
        print("Silme için --onay SIL gerekli. Ne silineceğini görmek için --kuru kullanın.")  # noqa: T201
        return 2

    export_dizini = cozumle_dizin(args.export)
    yedek: Path | None = None
    if not args.kuru:
        yedek = _yedek_al(get_settings().database_url)
        if yedek:
            print(f"Yedek alındı: {yedek}")  # noqa: T201

    try:
        with SessionLocal() as session:
            ozeti = sifirla(
                session,
                export_dizini=export_dizini,
                banka=args.banka,
                kapsam=args.kapsam,
                gold_sil=args.gold_sil,
                kuru=args.kuru,
            )
    except (PermissionError, ValueError) as exc:
        print(f"HATA: {exc}")  # noqa: T201
        return 2

    ozeti.yedek = yedek
    baslik = "SİLİNECEK (kuru çalıştırma)" if args.kuru else "SİLİNDİ"
    print(f"\n{baslik}:")  # noqa: T201
    for ad, adet in ozeti.silinen.items():
        print(f"  {ad:24} {adet:6}")  # noqa: T201
    if args.kapsam == "kampanya":
        print("\n  source_documents      KORUNDU (ham arşiv indeksi)")  # noqa: T201
    if not args.gold_sil:
        print("  gold_annotations      KORUNDU (--gold-sil ile silinir)")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
