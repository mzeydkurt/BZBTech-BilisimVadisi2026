"""TKBB Veri Peteği'nin elle doğrulanmış verisini yükler (KATİP KAPI 4.4).

`python dev.py tkbb-yukle` ile çalıştırılır. Playwright otomasyonu
(`scripts/scrape_tkbb.py`) bu ortamda çalışmadığında ya da henüz
çalıştırılmadığında kullanılan FALLBACK yoldur — SPRINT 2.5'in Kuveyt Türk
PDF'i için izlediği "veri statik ve nadiren değişiyor, elle seed meşru
mühendislik kararı" ilkesiyle aynı.

Kaynak: `data/seed/tkbb_veripetegi_2026_08.json` — kullanıcının kendi
tarayıcısında API JSON'unu + dashboard Excel export'unu çapraz kontrol ederek
doğruladığı veri (bkz. `docs/TKBB_VERI_PETEGI_BULGULARI.md`).

İdempotenttir: tekrar çalıştırıldığında var olan satırları GÜNCELLER, çoğaltmaz.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.vocab import KATILIM_HESABI_VADE_ETIKETI
from app.db.models import Bank, Product, ProductRate
from app.db.session import SessionLocal
from app.logging_config import get_logger
from app.scrapers.models import RawProductRate
from app.scrapers.products import band_key

logger = get_logger(__name__)

SEED_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "seed" / "tkbb_veripetegi_2026_08.json"
)

# "aylik" -> 1 ay gibi; KATILIM_HESABI_VADE_ETIKETI'nin tersi.
_ETIKET_AY: dict[str, int] = {etiket: ay for ay, etiket in KATILIM_HESABI_VADE_ETIKETI.items()}

_DEGER_ALANI: dict[str, str] = {
    "participation_yield": "profit_rate_pct",
    "profit_sharing_ratio": "investor_share_pct",
}


def _urun_bul_veya_olustur(
    session: Session,
    bank: Bank,
    *,
    variant: str | None,
    product_type: str,
    availability_status: str,
) -> Product:
    """TKBB kaynaklı ürünü external_key üzerinden upsert eder."""
    external_key = f"tkbb-{bank.code}#{variant or 'base'}"
    urun = session.scalar(
        select(Product).where(Product.bank_id == bank.id, Product.external_key == external_key)
    )
    if urun is None:
        urun = Product(
            bank_id=bank.id,
            external_key=external_key,
            name=(
                "Ara Ödemeli Katılma Hesabı" if variant == "ara_odemeli" else "Katılma Hesabı"
            )
            + " (TKBB Veri Peteği)",
            product_type=product_type,
            variant_key=variant,
            variant_label="Ara Ödemeli" if variant == "ara_odemeli" else None,
            variant_dimension="ozel" if variant == "ara_odemeli" else None,
            variant_source="text" if variant == "ara_odemeli" else None,
            availability_status=availability_status,
            is_binding=True,
        )
        session.add(urun)
        session.flush()
    else:
        urun.availability_status = availability_status
    return urun


def _yaz_oranlar(
    session: Session,
    urun: Product,
    *,
    rate_type: str,
    values: dict[str, str],
    evidence_text: str | None,
) -> int:
    """Bir bankanın hücrelerini `ProductRate` satırlarına yazar; yazılan sayıyı döner."""
    yazilan = 0

    # ⚠️ USD=EUR tutarlılık denetimi (KAPI 4.5) — hata FIRLATMAZ, yalnızca
    # loglar. Neredeyse her bankada bu ikisi birebir eşit; farklıysa erken
    # sinyal olarak kayda geçer.
    for vade_etiketi in {k.split("|")[0] for k in values}:
        usd = values.get(f"{vade_etiketi}|USD")
        eur = values.get(f"{vade_etiketi}|EUR")
        if usd is not None and eur is not None and usd != eur:
            logger.warning(
                "tkbb_usd_eur_farkli",
                banka=urun.bank_id,
                vade=vade_etiketi,
                usd=usd,
                eur=eur,
            )

    for hucre_anahtari, ham_deger in values.items():
        vade_etiketi, para_birimi = hucre_anahtari.split("|")
        ay = _ETIKET_AY.get(vade_etiketi)
        if ay is None:
            logger.warning("tkbb_bilinmeyen_vade", etiket=vade_etiketi)
            continue

        deger = Decimal(ham_deger)
        raw = RawProductRate(
            rate_source="seed_manual",
            data_source="tkbb_veripetegi",
            rate_type=rate_type,
            term_months=ay,
            term_label=vade_etiketi,
            currency=para_birimi,
            variant=urun.variant_key,
            evidence_text=evidence_text or f"TKBB Veri Peteği — {vade_etiketi}: {ham_deger}",
        )
        if rate_type == "profit_sharing_ratio":
            raw.investor_share_pct = deger
            raw.bank_share_pct = Decimal("100") - deger
        else:
            raw.profit_rate_pct = deger

        # ⚠️ CANONİK ANAHTAR. `app.scrapers.products.band_key()`'in aynısı
        # kullanılır — elle paralel bir kodlama, `_BAND_FIELDS` sırası
        # değişirse sessizce ıraksardı.
        anahtar = band_key(raw)

        mevcut = session.scalar(
            select(ProductRate).where(
                ProductRate.product_id == urun.id,
                ProductRate.rate_source == "seed_manual",
                ProductRate.band_key == anahtar,
            )
        )
        if mevcut is None:
            session.add(
                ProductRate(
                    product_id=urun.id,
                    band_key=anahtar,
                    rate_source=raw.rate_source,
                    data_source=raw.data_source,
                    rate_type=raw.rate_type,
                    term_months=raw.term_months,
                    term_label=raw.term_label,
                    currency=raw.currency,
                    variant=raw.variant,
                    profit_rate_pct=raw.profit_rate_pct,
                    investor_share_pct=raw.investor_share_pct,
                    bank_share_pct=raw.bank_share_pct,
                    evidence_text=raw.evidence_text,
                )
            )
            yazilan += 1
        else:
            mevcut.profit_rate_pct = raw.profit_rate_pct
            mevcut.investor_share_pct = raw.investor_share_pct
            mevcut.bank_share_pct = raw.bank_share_pct
            mevcut.evidence_text = raw.evidence_text

    return yazilan


def load_tkbb_seed(session: Session, *, seed_path: Path = SEED_PATH) -> dict[str, int]:
    """Seed JSON'unu okuyup `Product`/`ProductRate` satırlarına yazar.

    Returns:
        Özet sayaçlar: {"urun": N, "oran": N, "not_offered": N}.
    """
    veri = json.loads(seed_path.read_text(encoding="utf-8"))
    ozet = {"urun": 0, "oran": 0, "not_offered": 0}

    bankalar = {b.code: b for b in session.scalars(select(Bank))}

    for veri_seti in veri["datasets"]:
        rate_type = veri_seti["rate_type"]
        variant = veri_seti.get("variant")
        variant = None if variant == "normal" else variant
        product_type = (
            "ara_donem_kar_odemeli" if variant == "ara_odemeli" else "birikim_katilma_hesabi"
        )

        for satir in veri_seti["rows"]:
            bank = bankalar.get(satir["bank_code"])
            if bank is None:
                logger.warning("tkbb_bilinmeyen_banka", kod=satir["bank_code"])
                continue

            urun = _urun_bul_veya_olustur(
                session,
                bank,
                variant=variant,
                product_type=product_type,
                availability_status="offered",
            )
            ozet["urun"] += 1
            ozet["oran"] += _yaz_oranlar(
                session,
                urun,
                rate_type=rate_type,
                values=satir["values"],
                evidence_text=satir.get("evidence_text"),
            )

        # ⚠️ "Ürün yok" (`not_offered`) — veri eksik değil, banka bu ürünü hiç
        # sunmuyor. Oran satırı YAZILMAZ, yalnızca ürün iskeleti açılır.
        for bank_code in veri_seti.get("not_offered_banks", []):
            bank = bankalar.get(bank_code)
            if bank is None:
                continue
            _urun_bul_veya_olustur(
                session,
                bank,
                variant=variant,
                product_type=product_type,
                availability_status="not_offered",
            )
            ozet["not_offered"] += 1

    session.commit()
    return ozet


def main() -> int:
    """CLI girişi: `python dev.py tkbb-yukle`."""
    if not SEED_PATH.exists():
        print(f"Seed dosyası bulunamadı: {SEED_PATH}")
        return 1

    with SessionLocal() as session:
        ozet = load_tkbb_seed(session)

    print(
        f"TKBB seed yüklendi — ürün: {ozet['urun']}, yeni oran: {ozet['oran']}, "
        f"not_offered: {ozet['not_offered']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
