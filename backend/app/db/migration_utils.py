"""Göçlerin ortak yardımcıları.

⚠️ NEDEN VAR: SQLite'ta `batch_alter_table(naming_convention=...)` bir tabloyu
yeniden kurarken, o çağrıda hiç dokunulmayan CHECK kısıtlarının adına da bir
kat daha önek ekliyor. Sonuç, aynı kısıtın veritabanından veritabanına farklı
sayıda katmanlı bir ad taşıması:

    product_rates.rate_source_valid
        sıfırdan kurulan şema : ck_product_rates_ × 3 + rate_source_valid
        geliştirme veritabanı : ck_product_rates_ × 5 + rate_source_valid

Göçler bu adı SABİT yazdığı sürece iki ortamdan biri mutlaka kırılıyordu ve
boş bir veritabanında `alembic upgrade head` hiç tamamlanamıyordu
(`ValueError: No such constraint`). Kısıt adı sabit yazılmaz, veritabanından
okunur.
"""

from __future__ import annotations

import re
from typing import Final

from alembic import op

_CONSTRAINT_RE: Final[re.Pattern[str]] = re.compile(r"CONSTRAINT\s+(\S+)\s+CHECK")


def gercek_check_adi(table: str, suffix: str, default: str) -> str:
    """Bir CHECK kısıtının veritabanındaki GERÇEK adını döndürür.

    ⚠️ AD OLDUĞU GİBİ DÖNER, ÖN EK SOYULMAZ. `batch.drop_constraint()` hem
    verilen dizeye hem yansıtılmış kısıta aynı `naming_convention` katını
    uyguluyor; iki taraf da bir kat aldığı için eşleşme ancak GERÇEK adla
    sağlanır.

    ⚠️ SQLITE DIŞINDA ARAMA YAPILMAZ. Kat katlanması `batch_alter_table`'ın
    SQLite'a özgü "tabloyu yeniden kur" davranışından doğuyor; PostgreSQL'de
    kısıt adı olduğu gibi duruyor ve `default` doğrudur.

    Args:
        table: Kısıtın bulunduğu tablo.
        suffix: Aranan adın bittiği ek (ör. `"rate_source_valid"`).
        default: SQLite dışında ve ad bulunamadığında kullanılacak ad.

    Returns:
        Düşürülecek kısıtın adı.
    """
    baglanti = op.get_bind()
    if baglanti.dialect.name != "sqlite":
        return default

    ddl = baglanti.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).scalar()
    if not ddl:
        return default

    adaylar = [ad for ad in _CONSTRAINT_RE.findall(ddl) if ad.endswith(suffix)]
    # ⚠️ Birden çok aday varsa EN UZUNU seçilir: katmanlı ad, kısa adı sonek
    # olarak içerir; kısa olan seçilirse düşürme yine başarısız olur.
    return max(adaylar, key=len) if adaylar else default
