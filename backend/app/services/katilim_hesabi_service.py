"""Katılım Hesabı sekmesi pivot servisi (KATİP KAPI 7).

TKBB Veri Peteği'nin 4 veri setini (KAPI 4) ve bankaların kendi sitesinden
scrape edilen katılma hesabı verisini (`data_source`'a göre ayrı) aynı
pivot görünümde birleştirir. Yeni bir sıralama algoritması İÇERMEZ; bu
servisin işi yalnızca gruplama/pivot, sıralama `comparison_service.rank_products`'ın işi.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.vocab import KATILIM_HESABI_TIPLERI, KATILIM_HESABI_VADE_ETIKETI, RATE_TYPES
from app.db.models.bank import Bank
from app.db.models.product import Product, ProductRate
from app.schemas.katilim_hesabi import (
    KatilimHesabiCrossCheck,
    KatilimHesabiResponse,
    KatilimHesabiRow,
)

# rate_type -> hangi kolon karşılaştırılabilir değeri taşır (aynı harita
# `app/core/vocab.py::RATE_TYPE_COMPARABLE_FIELD` ile tutarlı).
_DEGER_ALANI: dict[str, str] = {
    "participation_yield": "profit_rate_pct",
    "profit_sharing_ratio": "investor_share_pct",
}

# İki değer arasındaki fark bu eşiğin altındaysa "yakın" sayılır.
_YAKIN_ESIK_PUAN = Decimal("0.5")


def _eslesme(a: Decimal, b: Decimal) -> str:
    if a == b:
        return "ayni"
    if abs(a - b) <= _YAKIN_ESIK_PUAN:
        return "yakin"
    return "farkli"


def build_katilim_hesabi(
    session: Session,
    *,
    rate_type: str,
    variant: str = "normal",
    currency: str | None = None,
    term_months: int | None = None,
) -> KatilimHesabiResponse:
    """TKBB'nin kendi dashboard görünümüne benzer bir pivot üretir.

    Args:
        session: Veritabanı oturumu.
        rate_type: `participation_yield` (getiri) veya `profit_sharing_ratio` (paylaşım).
        variant: `normal` veya `ara_odemeli`.
        currency: Verilirse yalnızca bu para birimindeki hücreler döner.
        term_months: Verilirse yalnızca bu vadedeki hücreler döner.

    Returns:
        Banka × vade|para_birimi pivot tablosu.

    Raises:
        ValueError: `rate_type` bu pivotta anlamlı değilse.
    """
    if rate_type not in _DEGER_ALANI:
        raise ValueError(
            f"Geçersiz rate_type: {rate_type!r}. Geçerli değerler: {', '.join(_DEGER_ALANI)} "
            f"(diğer RATE_TYPES değerleri — {', '.join(RATE_TYPES)} — bu pivotta anlamlı değil)"
        )
    deger_alani = _DEGER_ALANI[rate_type]
    varyant_anahtari = "ara_odemeli" if variant == "ara_odemeli" else None
    varyant_kosulu = (
        Product.variant_key == varyant_anahtari
        if varyant_anahtari is not None
        else Product.variant_key.is_(None)
    )

    stmt = (
        select(ProductRate, Bank)
        .join(Product, ProductRate.product_id == Product.id)
        .join(Bank, Product.bank_id == Bank.id)
        .where(
            Product.product_type.in_(KATILIM_HESABI_TIPLERI),
            varyant_kosulu,
            ProductRate.rate_type == rate_type,
        )
    )
    if currency:
        stmt = stmt.where(ProductRate.currency == currency)
    if term_months is not None:
        stmt = stmt.where(ProductRate.term_months == term_months)

    # banka_kodu -> data_source -> {"aylik|TRY": Decimal, ...}
    banka_adlari: dict[str, str] = {}
    kaynak_hucreleri: dict[str, dict[str, dict[str, Decimal]]] = {}
    anomali_notlari: list[str] = []

    for oran, banka in session.execute(stmt).all():
        if oran.term_months not in KATILIM_HESABI_VADE_ETIKETI:
            continue
        deger = getattr(oran, deger_alani)
        if deger is None:
            continue
        vade_etiketi = KATILIM_HESABI_VADE_ETIKETI[oran.term_months]
        hucre_anahtari = f"{vade_etiketi}|{oran.currency}"

        banka_adlari[banka.code] = banka.name
        kaynak_hucreleri.setdefault(banka.code, {}).setdefault(oran.data_source, {})[
            hucre_anahtari
        ] = deger

        if oran.evidence_text and "anomali" in oran.evidence_text.lower():
            not_metni = f"{banka.name} — {hucre_anahtari}: {oran.evidence_text}"
            if not_metni not in anomali_notlari:
                anomali_notlari.append(not_metni)

    satirlar: list[KatilimHesabiRow] = []
    for banka_kodu, kaynaklar in sorted(kaynak_hucreleri.items()):
        # TKBB varsa birincil kaynak odur (KAPI 4'ün çapraz doğrulama amacı);
        # yoksa bankanın kendi sitesi.
        birincil_kaynak = "tkbb_veripetegi" if "tkbb_veripetegi" in kaynaklar else "bank_site"
        ikincil_kaynak = "bank_site" if birincil_kaynak == "tkbb_veripetegi" else "tkbb_veripetegi"

        degerler = kaynaklar[birincil_kaynak]
        cross_check: KatilimHesabiCrossCheck | None = None
        if ikincil_kaynak in kaynaklar:
            # Sadece HER İKİ kaynakta da bulunan ilk ortak hücre karşılaştırılır.
            ortak_anahtar = next((k for k in degerler if k in kaynaklar[ikincil_kaynak]), None)
            if ortak_anahtar is not None:
                birincil_deger = degerler[ortak_anahtar]
                ikincil_deger = kaynaklar[ikincil_kaynak][ortak_anahtar]
                cross_check = KatilimHesabiCrossCheck(
                    bank_site_value=(
                        birincil_deger if birincil_kaynak == "bank_site" else ikincil_deger
                    ),
                    tkbb_value=(
                        birincil_deger if birincil_kaynak == "tkbb_veripetegi" else ikincil_deger
                    ),
                    match=_eslesme(birincil_deger, ikincil_deger),
                )

        satirlar.append(
            KatilimHesabiRow(
                bank_code=banka_kodu,
                bank_name=banka_adlari[banka_kodu],
                values=degerler,
                data_source=birincil_kaynak,
                cross_check=cross_check,
            )
        )

    not_offered_banks = [
        banka.name
        for banka in session.scalars(
            select(Bank)
            .join(Product, Product.bank_id == Bank.id)
            .where(
                Product.product_type.in_(KATILIM_HESABI_TIPLERI),
                varyant_kosulu,
                Product.availability_status == "not_offered",
            )
            .distinct()
        )
    ]

    return KatilimHesabiResponse(
        rate_type=rate_type,
        variant=variant,
        rows=satirlar,
        not_offered_banks=sorted(not_offered_banks),
        data_quality_notes=anomali_notlari,
    )
