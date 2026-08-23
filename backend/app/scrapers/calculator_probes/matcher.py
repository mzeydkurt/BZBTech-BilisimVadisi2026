"""Hesaplayıcı probe sonucunu DB ürününe eşleştir."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.normalization.text import ascii_fold_tr, lower_tr
from app.db.models.bank import Bank
from app.db.models.product import Product
from app.scrapers.calculator_probes.common import ProbeReading


# Hesaplayıcı etiketi → ürün adında aranacak anahtarlar
_VARIANT_ANAHTAR: dict[str, tuple[str, ...]] = {
    "sifir km": ("tasit", "arac"),
    "2. el": ("tasit", "arac"),
    "binek": ("tasit", "arac"),
    "motosiklet": ("motosiklet", "tasit"),
    "konut": ("konut",),
    "ilk evim": ("konut",),
    "arsa": ("arsa",),
    "is yeri": ("is yeri", "isyeri"),
    "isyeri": ("is yeri", "isyeri"),
    "ihtiyac": ("ihtiyac",),
    "tuketici ihtiyac": ("ihtiyac",),
    "alisveris": ("ihtiyac", "alisveris"),
    "egitim": ("egitim",),
    "hac": ("hac", "umre"),
    "umre": ("hac", "umre"),
    "pratik finansman kart": ("pratik",),
    "hepsiburada": ("hepsiburada", "alisveris"),
    "waikiki": ("waikiki", "alisveris"),
    "taksitlio": ("taksitlio", "alisveris"),
    "trendyol": ("trendyol", "alisveris"),
    "arac binek": ("arac", "tasit"),
    "arac": ("arac", "tasit"),
    "prefabrik": ("prefabrik",),
    "yurt": ("yurt",),
    "kira": ("kira",),
}


def _skor(ad: str, etiket: str) -> int:
    ad_k = ascii_fold_tr(lower_tr(ad))
    et_k = ascii_fold_tr(lower_tr(etiket))
    if not ad_k or not et_k:
        return 0
    if ad_k == et_k or ad_k in et_k or et_k in ad_k:
        return 100
    ad_tok = set(ad_k.split())
    et_tok = set(et_k.split())
    ortak = ad_tok & et_tok
    anahtar = {"finansman", "finansmani", "konut", "tasit", "ihtiyac", "arac", "arsa", "isyeri"}
    puan = sum(3 for t in ortak if t in anahtar or len(t) > 4)
    puan += len(ortak)
    for parca, aranan in _VARIANT_ANAHTAR.items():
        if parca in et_k and any(a in ad_k for a in aranan):
            puan += 8
    return puan


def urun_bul(session: Session, okuma: ProbeReading) -> Product | None:
    banka = session.scalar(select(Bank).where(Bank.code == okuma.bank_code))
    if banka is None:
        return None
    stmt = (
        select(Product)
        .where(Product.bank_id == banka.id, Product.parent_product_id.is_(None))
        .order_by(Product.id)
    )
    if okuma.product_type_hint:
        stmt = stmt.where(Product.product_type == okuma.product_type_hint)

    adaylar = list(session.scalars(stmt))
    if not adaylar:
        adaylar = list(
            session.scalars(
                select(Product)
                .where(
                    Product.bank_id == banka.id,
                    Product.parent_product_id.is_(None),
                )
                .order_by(Product.id)
            )
        )

    en_iyi: Product | None = None
    en_yuksek = 0
    for urun in adaylar:
        s = _skor(urun.name or "", okuma.variant_label)
        if s > en_yuksek:
            en_yuksek = s
            en_iyi = urun
    return en_iyi if en_yuksek >= 3 else None
