"""Çıkarım çalıştırma komutu.

AĞA ÇIKMAZ. Kayıtlı `clean_text` üzerinde çalışır; bankalara istek gitmez.

Çalıştırma:
    python dev.py cikarim --sadece-kural
    python dev.py cikarim --sadece-kural --banka ziraat_katilim
    python dev.py cikarim --sadece-kural --limit 20
"""

from __future__ import annotations

import argparse
import sys

from app.ai.pipeline import run_extraction
from app.db.session import SessionLocal
from app.logging_config import configure_logging


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(description="Kampanya bilgi çıkarımı")
    ayristirici.add_argument(
        "--sadece-kural",
        action="store_true",
        help="Kural tabanlı çıkarım (SPRINT 3A'da tek uygulanan kip)",
    )
    ayristirici.add_argument("--banka", help="Yalnızca bu bankayı işle")
    ayristirici.add_argument("--limit", type=int, help="En fazla bu kadar kampanya")
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # ⚠️ Varsayılan kip yok: LLM katmanı gelene kadar (KAPI A6) kullanıcı
    # hangi kipi çalıştırdığını AÇIKÇA belirtmeli.
    if not argumanlar.sadece_kural:
        print("SPRINT 3A'da yalnızca kural tabanlı çıkarım var. Kullanım:")
        print("    python dev.py cikarim --sadece-kural")
        return 1

    with SessionLocal() as session:
        ozet = run_extraction(
            session, mode="rule_only", bank_code=argumanlar.banka, limit=argumanlar.limit
        )

    if ozet.campaigns_processed == 0:
        print("İşlenecek kampanya bulunamadı. Önce 'python dev.py scrape' çalıştırın.")
        return 1

    print(f"\nÇalıştırma       : #{ozet.run_id}  ({ozet.mode})")
    print(f"İşlenen kampanya : {ozet.campaigns_processed}")
    print(f"Çıkarılan alan   : {ozet.fields_extracted}")
    print(f"Hata             : {ozet.errors_count}")
    print(f"Süre             : {ozet.duration_seconds} sn")

    if ozet.by_field:
        print("\nAlan bazında:")
        for alan, sayi in ozet.by_field.items():
            print(f"  {alan:24} {sayi}")

    print("\nSonraki adım: python dev.py degerlendir --mod rule_only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
