"""Kanıtı doğrulanamayan gold etiketlerini yeniden etiketleme kuyruğuna alır.

Etiketleme arayüzündeki iki hata (seçim tüketilmemesi ve seçim uzunluğunun
sınırsız olması) düzeltildi ama ÖNCEDEN kaydedilmiş etiketler düzelmez.
Ayrıca ön işleme sonradan iyileştirildiği için bazı kanıtlar bugünkü
`clean_text` içinde hiç bulunmuyor.

⚠️ HİÇBİR ETİKET SİLİNMEZ. Bu betik yalnızca güvenilmez etiketleri tespit eder
ve `docs/gold_recheck.md`'ye yazar; ne etiketleneceğine insan karar verir.

Çıkış kodu daima 0 — bu bir denetim raporudur, kapı değildir.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.normalization.text import normalize_text
from app.db.models import Bank, Campaign, GoldAnnotation, SourceDocument
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger

logger = get_logger(__name__)

RAPOR_YOLU = Path("../docs/gold_recheck.md")

# Kanıt bu uzunluğu aşarsa arayüzdeki "tüm sayfayı seçme" hatasının izidir.
KANIT_UST_SINIR = 220
# Bu uzunluğun altındaki kanıt doğrulanamaz.
KANIT_ALT_SINIR = 10


@dataclass
class Bulgu:
    """Tek bir kampanya için kanıt denetimi sonucu."""

    campaign_key: str
    baslik: str
    nedenler: list[str] = field(default_factory=list)
    etiket_sayisi: int = 0


def denetle(session: Session) -> list[Bulgu]:
    """Gold etiketlerinin kanıtlarını bugünkü metne karşı denetler.

    Args:
        session: Veritabanı oturumu.

    Returns:
        Sorunlu kampanyaların bulguları.
    """
    satirlar = session.execute(
        select(
            GoldAnnotation.campaign_key,
            GoldAnnotation.field_name,
            GoldAnnotation.gold_value,
            GoldAnnotation.evidence_text,
            Campaign.title,
            SourceDocument.clean_text,
        )
        .join(Campaign, GoldAnnotation.campaign_id == Campaign.id)
        .join(Bank, Campaign.bank_id == Bank.id)
        .outerjoin(SourceDocument, Campaign.source_document_id == SourceDocument.id)
    ).all()

    gruplar: dict[str, list[tuple[str, str | None, str | None, str, str | None]]] = defaultdict(
        list
    )
    for anahtar, alan, deger, kanit, baslik, metin in satirlar:
        gruplar[anahtar].append((alan, deger, kanit, baslik, metin))

    bulgular: list[Bulgu] = []
    for anahtar, kayitlar in gruplar.items():
        baslik = kayitlar[0][3]
        bulgu = Bulgu(campaign_key=anahtar, baslik=baslik, etiket_sayisi=len(kayitlar))
        metin = kayitlar[0][4] or ""
        temiz = normalize_text(metin)

        # Yalnızca DEĞERİ olan etiketlerin kanıtı zorunludur; ∅ (metinde yok)
        # etiketlerinde kanıt beklenmez.
        degerli = [(a, d, k) for a, d, k, _b, _m in kayitlar if d is not None]

        kanitsiz = [a for a, _d, k in degerli if not k or len(k.strip()) < KANIT_ALT_SINIR]
        if kanitsiz:
            bulgu.nedenler.append(f"kanıtı yok/çok kısa: {len(kanitsiz)} alan")

        uzun = [a for a, _d, k in degerli if k and len(k) > KANIT_UST_SINIR]
        if uzun:
            bulgu.nedenler.append(f"kanıt {KANIT_UST_SINIR} karakterden uzun: {len(uzun)} alan")

        kanitlar = {k.strip() for _a, _d, k in degerli if k and k.strip()}
        if len(degerli) > 1 and len(kanitlar) == 1:
            # Arayüz hatası: bir seçim tüm alanlara kopyalanmış.
            bulgu.nedenler.append("tüm alanların kanıtı AYNI metin")

        bulunamayan = [
            a for a, _d, k in degerli if k and k.strip() and normalize_text(k) not in temiz
        ]
        if bulunamayan:
            bulgu.nedenler.append(f"kanıt bugünkü metinde bulunamıyor: {len(bulunamayan)} alan")

        if bulgu.nedenler:
            bulgular.append(bulgu)

    return sorted(bulgular, key=lambda b: (-len(b.nedenler), b.campaign_key))


def rapor_yaz(bulgular: list[Bulgu], *, toplam_kampanya: int, yol: Path = RAPOR_YOLU) -> None:
    """Denetim raporunu yazar."""
    yol.parent.mkdir(parents=True, exist_ok=True)
    satirlar = [
        "# Gold Set Kanıt Denetimi",
        "",
        f"- Etiketli kampanya: **{toplam_kampanya}**",
        f"- Yeniden etiketlenmesi gereken: **{len(bulgular)}**",
        "",
        "⚠️ Hiçbir etiket silinmedi. Bu liste, kanıtı bugünkü `clean_text`'e karşı",
        "doğrulanamayan kayıtları gösterir; ölçüm bunlara dayandığı sürece F1",
        "gerçek başarıyı yansıtmaz.",
        "",
        "| Kampanya | Başlık | Sorun |",
        "|---|---|---|",
    ]
    for bulgu in bulgular:
        baslik = bulgu.baslik[:60].replace("|", "\\|")
        satirlar.append(f"| `{bulgu.campaign_key}` | {baslik} | {'; '.join(bulgu.nedenler)} |")
    satirlar.append("")
    yol.write_text("\n".join(satirlar), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Denetimi çalıştırır."""
    parser = argparse.ArgumentParser(
        prog="gold_recheck", description="Kanıtı doğrulanamayan gold etiketlerini raporlar."
    )
    parser.parse_args(argv)
    configure_logging()

    with SessionLocal() as session:
        toplam = session.scalar(select(GoldAnnotation.campaign_key).distinct().order_by(None))
        anahtarlar = set(session.scalars(select(GoldAnnotation.campaign_key)))
        bulgular = denetle(session)

    rapor_yaz(bulgular, toplam_kampanya=len(anahtarlar))
    del toplam

    print("\nGold kanit denetimi:")  # noqa: T201
    print(f"  etiketli kampanya           {len(anahtarlar)}")  # noqa: T201
    print(f"  yeniden etiketlenmesi geren {len(bulgular)}")  # noqa: T201
    print(f"\nRapor: {RAPOR_YOLU}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
