"""Süresi KESİN OLARAK dolmuş kampanyaları kalıcı siler (KATİP).

⚠️ VERİ SİLER. `reset_campaign_data.sifirla` ile AYNI güvenlik desenini
izler — üç kilit de aynen geçerlidir (`--onay SIL`, doğrulanmış `--export`,
silmeden önce SQLite yedeği) — ama TÜM kampanya verisini değil, yalnızca
`Campaign.status == "expired"` olan kayıtları siler.

Neden ayrı bir betik, `sifirla --banka X` değil: kullanıcının isteği "tarihi
bilinmeyen kampanya kalsın, yalnızca süresi KESİN OLARAK dolmuş olan
dashboard'dan silinsin" — `unknown` ile `expired` BİLİNÇLİ OLARAK ayrı
durumlardır (bkz. `app/services/campaign_service.py::compute_status`).
`sifirla` bankaya göre TÜMÜNÜ siler; bu betik duruma göre süzer.

`source_documents` (ham HTML arşivi) ve `gold_annotations`'a DOKUNULMAZ:
biten bir kampanya bankanın sitesinden kalkmış olabilir ve o kanıt bir daha
elde edilemez.

`python dev.py suresi-dolanlari-temizle --export <dizin> --onay SIL` ile çalışır.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    Campaign,
    CampaignCategory,
    CampaignExtraction,
    CampaignMetric,
    Embedding,
    EntityCard,
)
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger
from scripts.reset_campaign_data import _say, _say_polimorfik, _yedek_al
from scripts.verify_export import cozumle_dizin

logger = get_logger(__name__)


@dataclass
class SuresiDolmusSilmeOzeti:
    """Silme sonucu."""

    yedek: Path | None = None
    silinen: dict[str, int] = field(default_factory=dict)
    kuru: bool = False


def sil(session: Session, *, export_dizini: Path, kuru: bool = False) -> SuresiDolmusSilmeOzeti:
    """`status='expired'` olan kampanyaları (kök + alt) kalıcı siler.

    Args:
        session: Veritabanı oturumu.
        export_dizini: Doğrulanmış dışa aktarma dizini.
        kuru: True ise yalnızca sayar, silmez.

    Returns:
        Silme özeti.

    Raises:
        PermissionError: Dışa aktarma doğrulanmamışsa.
    """
    from scripts.verify_export import dogrulanmis_mi

    if not dogrulanmis_mi(export_dizini):
        raise PermissionError(
            f"Dışa aktarma doğrulanmamış: {export_dizini}. "
            "Önce: python dev.py disa-aktar-dogrula --dizin <dizin>"
        )

    ozeti = SuresiDolmusSilmeOzeti(kuru=kuru)
    kampanya_idleri = list(session.scalars(select(Campaign.id).where(Campaign.status == "expired")))

    ozeti.silinen = {
        "campaigns": len(kampanya_idleri),
        "campaign_extractions": _say(session, CampaignExtraction, kampanya_idleri),
        "campaign_categories": _say(session, CampaignCategory, kampanya_idleri),
        "campaign_metrics": _say(session, CampaignMetric, kampanya_idleri),
        "entity_cards (campaign)": _say_polimorfik(session, EntityCard, kampanya_idleri),
        "embeddings (campaign)": _say_polimorfik(session, Embedding, kampanya_idleri),
    }

    if kuru or not kampanya_idleri:
        if not kampanya_idleri:
            logger.info("silinecek_suresi_dolmus_kampanya_yok")
        return ozeti

    # ⚠️ Polimorfik kayıtlar FK taşımıyor; elle temizlenir (bkz. `reset_campaign_data.sifirla`).
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
    # `source_documents`/`gold_annotations`/`scrape_runs` BİLİNÇLİ OLARAK
    # DOKUNULMAZ — bu betik tüm bankayı değil, tek tek süresi dolmuş
    # kampanyaları hedefler.
    session.execute(delete(Campaign).where(Campaign.id.in_(kampanya_idleri)))
    session.commit()
    return ozeti


def main(argv: list[str] | None = None) -> int:
    """CLI girişi: `python dev.py suresi-dolanlari-temizle`."""
    parser = argparse.ArgumentParser(
        prog="delete_expired_campaigns",
        description="Süresi KESİN OLARAK dolmuş kampanyaları kalıcı siler (VERİ SİLER).",
    )
    parser.add_argument("--export", required=True, help="Doğrulanmış dışa aktarma dizini")
    parser.add_argument("--onay", help="Silmek için 'SIL' yazın")
    parser.add_argument("--kuru", action="store_true", help="Ne silineceğini yazar, silmez")
    args = parser.parse_args(argv)
    configure_logging()

    if not args.kuru and args.onay != "SIL":
        print("Silme için --onay SIL gerekli. Ne silineceğini görmek için --kuru kullanın.")  # noqa: T201
        return 2

    export_dizini = cozumle_dizin(args.export)
    yedek: Path | None = None
    if not args.kuru:
        from app.config import get_settings

        yedek = _yedek_al(get_settings().database_url)
        if yedek:
            print(f"Yedek alındı: {yedek}")  # noqa: T201

    try:
        with SessionLocal() as session:
            ozeti = sil(session, export_dizini=export_dizini, kuru=args.kuru)
    except PermissionError as exc:
        print(f"HATA: {exc}")  # noqa: T201
        return 2

    ozeti.yedek = yedek
    baslik = "SİLİNECEK (kuru çalıştırma)" if args.kuru else "SİLİNDİ"
    print(f"\n{baslik}:")  # noqa: T201
    for ad, adet in ozeti.silinen.items():
        print(f"  {ad:24} {adet:6}")  # noqa: T201
    print("\n  source_documents        KORUNDU (ham arşiv indeksi)")  # noqa: T201
    print("  gold_annotations        KORUNDU")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
