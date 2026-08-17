"""Veri setini KARARLI ANAHTARLARLA dışa aktarır (ağa çıkmaz).

Kampanya verisi silinmeden önce çalıştırılması ZORUNLUDUR. Amaç yedek almak
değil, `campaign_id` bağımlılığını kırmaktır: `gold_annotations` 880 satırlık
elle etiketleme işidir ve autoincrement id'ye bağlıdır; veri yeniden
kazındığında id'ler değişir.

⚠️ `Decimal` alanlar DİZE olarak serileştirilir. float'a düşerse oranlar
sessizce bozulur (CLAUDE.md: para ve oran için float yasak).

Çıktı: `data/exports/{utc_zaman}/` + `manifest.json`
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    Bank,
    Campaign,
    CampaignCategory,
    CampaignExtraction,
    EntityCard,
    GoldAnnotation,
    SourceDocument,
)
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger

logger = get_logger(__name__)

EXPORT_ROOT = Path("data/exports")


def _json_degeri(deger: Any) -> Any:
    """Değeri JSON'a güvenli biçimde çevirir.

    `Decimal` DİZE olur; float'a çevrilmesi finansal değerlerde yuvarlama
    hatası üretir.
    """
    if isinstance(deger, Decimal):
        return str(deger)
    if isinstance(deger, datetime | date):
        return deger.isoformat()
    return deger


def _satir(nesne: Any, alanlar: Iterable[str]) -> dict[str, Any]:
    """ORM nesnesinden seçili alanları JSON'a hazır sözlüğe çevirir."""
    return {ad: _json_degeri(getattr(nesne, ad)) for ad in alanlar}


def _yaz_jsonl(yol: Path, satirlar: Iterable[Mapping[str, Any]]) -> int:
    """Satırları JSONL olarak yazar ve adet döndürür."""
    adet = 0
    with yol.open("w", encoding="utf-8", newline="\n") as dosya:
        for satir in satirlar:
            dosya.write(json.dumps(satir, ensure_ascii=False) + "\n")
            adet += 1
    return adet


def _sha256(yol: Path) -> str:
    """Dosyanın içerik özetini döndürür."""
    ozet = hashlib.sha256()
    ozet.update(yol.read_bytes())
    return ozet.hexdigest()


def _kampanya_anahtarlari(session: Session) -> dict[int, str]:
    """campaign_id → "{bank_code}:{external_slug}" haritası (tek sorgu)."""
    satirlar = session.execute(
        select(Campaign.id, Bank.code, Campaign.external_slug).join(
            Bank, Campaign.bank_id == Bank.id
        )
    ).all()
    return {cid: f"{kod}:{slug}" for cid, kod, slug in satirlar}


CAMPAIGN_FIELDS = (
    "id",
    "external_slug",
    "title",
    "description",
    "summary_ai",
    "category",
    "bank_category",
    "segment",
    "target_customer",
    "start_date",
    "end_date",
    "date_precision",
    "date_evidence_text",
    "date_evidence_source",
    "status",
    "block_index",
    "slug_source",
    "participation_channel",
    "participation_method",
    "sms_keyword",
    "sms_number",
    "coupon_code",
    "conditions_text",
    "exclusions_text",
    "source_url",
    "first_seen_at",
    "last_seen_at",
    "is_archived",
)

GOLD_FIELDS = (
    "campaign_key",
    "field_name",
    "gold_value",
    "unit",
    "evidence_text",
    "annotator",
    "method",
    "is_difficult",
    "note",
    "created_at",
)

EXTRACTION_FIELDS = (
    "field_name",
    "value_raw",
    "value_normalized",
    "unit",
    "evidence_text",
    "evidence_char_start",
    "evidence_char_end",
    "evidence_source_url",
    "confidence",
    "extraction_method",
    "model_name",
    "model_version",
    "prompt_version",
    "is_validated",
    "validation_note",
    "rejected_reason",
    "extracted_at",
)

DOCUMENT_FIELDS = (
    "url",
    "canonical_url",
    "url_hash",
    "doc_type",
    "http_status",
    "fetched_at",
    "raw_html_path",
    "raw_html_sha256",
    "clean_text_sha256",
    "scraper_name",
    "scraper_version",
    "robots_allowed",
    "is_soft_404",
    "discovery_method",
)


def disa_aktar(session: Session, *, hedef: Path) -> dict[str, Any]:
    """Veri setini `hedef` dizinine aktarır ve manifesti döndürür.

    Args:
        session: Veritabanı oturumu.
        hedef: Çıktı dizini (oluşturulur).

    Returns:
        Manifest sözlüğü.
    """
    hedef.mkdir(parents=True, exist_ok=True)
    anahtarlar = _kampanya_anahtarlari(session)
    sayilar: dict[str, int] = {}

    # ── campaigns ──
    kampanyalar = list(session.scalars(select(Campaign)))
    sayilar["campaigns"] = _yaz_jsonl(
        hedef / "campaigns.jsonl",
        [
            {
                **_satir(k, CAMPAIGN_FIELDS),
                "campaign_key": anahtarlar[k.id],
                "bank_code": anahtarlar[k.id].split(":", 1)[0],
                "parent_key": anahtarlar.get(k.parent_campaign_id or -1),
            }
            for k in kampanyalar
        ],
    )

    # ── gold_annotations: campaign_id YERİNE campaign_key ──
    # `source_url` ve `title` yedek eşleştirme çıpası olarak taşınır.
    kampanya_by_key = {anahtarlar[k.id]: k for k in kampanyalar}
    sayilar["gold_annotations"] = _yaz_jsonl(
        hedef / "gold_annotations.jsonl",
        [
            {
                **_satir(g, GOLD_FIELDS),
                "source_url": getattr(kampanya_by_key.get(g.campaign_key), "source_url", None),
                "title": getattr(kampanya_by_key.get(g.campaign_key), "title", None),
            }
            for g in session.scalars(select(GoldAnnotation))
        ],
    )

    # ── campaign_extractions ──
    # Ölçüldü: `is_validated` 2883/2883 satırda True; bu alanı HALÜSİNASYON
    # GUARD'ı yazıyor, insan değil. Yani ayrı bir "insan dokunuşu" alt kümesi
    # yoktur. Çıkarımlar tümüyle türetilmiş veridir ve `dev.py cikarim` ile
    # yeniden üretilir; buradaki dosya arşiv ve karşılaştırma amaçlıdır.
    sayilar["campaign_extractions"] = _yaz_jsonl(
        hedef / "campaign_extractions.jsonl",
        [
            {**_satir(c, EXTRACTION_FIELDS), "campaign_key": anahtarlar.get(c.campaign_id)}
            for c in session.scalars(select(CampaignExtraction))
        ],
    )

    # ── campaign_categories ──
    sayilar["campaign_categories"] = _yaz_jsonl(
        hedef / "campaign_categories.jsonl",
        [
            {
                "campaign_key": anahtarlar.get(k.campaign_id),
                "axis": k.axis,
                "value": k.value,
                "confidence": _json_degeri(k.confidence),
                "source": k.source,
                "evidence": k.evidence,
            }
            for k in session.scalars(select(CampaignCategory))
        ],
    )

    # ── entity_cards ──
    sayilar["entity_cards"] = _yaz_jsonl(
        hedef / "entity_cards.jsonl",
        [
            {
                "entity_type": k.entity_type,
                "entity_id": k.entity_id,
                "entity_key": k.entity_key
                or (anahtarlar.get(k.entity_id) if k.entity_type == "campaign" else None),
                "card_text": k.card_text,
                "card_hash": k.card_hash,
                "generated_at": _json_degeri(k.generated_at),
            }
            for k in session.scalars(select(EntityCard))
        ],
    )

    # ── source_documents: ham arşivin indeksi ──
    sayilar["source_documents"] = _yaz_jsonl(
        hedef / "source_documents.jsonl",
        [_satir(b, DOCUMENT_FIELDS) for b in session.scalars(select(SourceDocument))],
    )

    manifest: dict[str, Any] = {
        "uretildi": datetime.now().astimezone().isoformat(),
        "alembic_revision": _alembic_revision(session),
        "satir_sayilari": sayilar,
        "dosya_ozetleri": {
            yol.name: _sha256(yol) for yol in sorted(hedef.glob("*.jsonl"))
        },
        "verified_at": None,
    }
    (hedef / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _alembic_revision(session: Session) -> str | None:
    """Şema sürümünü okur; hangi şemadan aktarıldığı manifeste yazılır."""
    from sqlalchemy import text

    try:
        return session.scalar(text("SELECT version_num FROM alembic_version"))
    except Exception:  # noqa: BLE001 — sürüm okunamazsa aktarma engellenmez
        return None


def main(argv: list[str] | None = None) -> int:
    """Dışa aktarmayı çalıştırır."""
    parser = argparse.ArgumentParser(
        prog="export_dataset", description="Veri setini kararlı anahtarlarla dışa aktarır."
    )
    parser.add_argument("--hedef", help="Çıktı dizini; verilmezse zaman damgalı dizin")
    args = parser.parse_args(argv)
    configure_logging()

    zaman = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")
    hedef = Path(args.hedef) if args.hedef else EXPORT_ROOT / zaman

    settings = get_settings()
    logger.info("disa_aktarma_basladi", hedef=str(hedef), veritabani=settings.database_url)

    with SessionLocal() as session:
        manifest = disa_aktar(session, hedef=hedef)

    print(f"\nDışa aktarıldı: {hedef}")  # noqa: T201
    for ad, adet in manifest["satir_sayilari"].items():
        print(f"  {ad:32} {adet:6}")  # noqa: T201
    print("\nUYARI: Silme öncesi ZORUNLU: python dev.py disa-aktar-dogrula --dizin " + str(hedef))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
