"""KATİP genişlemeleri — alım sırası, marka/model, TKBB kaynak ayrımı.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-21

KATİP dönüşüm sprintinin (docs/KATIP_DONUSUM_PROMPTU.md KAPI 1) şema
gereksinimleri:

  - `products.purchase_order`  — "ilk_alim" | "sonraki_alim" | NULL. Albaraka
    ve Dünya Katılım'ın konut finansmanında iki ayrı LTV matrisi var (Standart
    / İkinci Alım); `variant_dimension="alim_sirasi"` ile birlikte kullanılır.
  - `products.brand` / `products.model` — Togg gibi marka/model bazlı
    finansman (`variant_dimension="marka_model"`).
  - `products.availability_status` — "ürün yok" (`not_offered`) ile "veri
    henüz toplanmadı" (`unknown`) ayrımı. TKBB'de "ara ödemeli katılma
    hesabı" yalnızca 5 bankada var; diğer 4 bankada satır HİÇ YOK.
  - `product_rates.data_source` — bankanın kendi sitesi (`bank_site`) mi,
    TKBB Veri Peteği'nin resmi API'si (`tkbb_veripetegi`) mi.
  - `rate_type` sözlüğüne `interest_free_benevolent_loan` eklenir (Karz-ı
    Hasen / vade farksız Eğitim Finansmanı — kâr payı KAVRAMI yok, 0 ile
    NULL'dan ayrı bir şey). `rank_products` sıralamasına bilinçli olarak hiç
    girmez (bkz. `app/core/vocab.py::RATE_TYPE_COMPARABLE_FIELD`).
  - `rate_source` sözlüğüne `seed_manual` eklenir — otomasyonun bu ortamda
    çalışmadığı durumlarda kullanıcının bizzat doğruladığı, elle girilen veri
    (tahmin DEĞİL, bankanın yayımladığı değerin birebir transkripsiyonu).

⚠️ TARİHSEL İSİMLENDİRME HATASI. Bu veritabanında `product_rates.rate_source_valid`
CHECK kısıtı önceki göçlerin `batch_alter_table` çağrılarında `naming_convention`
aktifken AYNI tabloya birden fazla ayrı blokla dokunulması yüzünden katmanlı
biçimde yeniden adlandırılmış (`ck_product_rates_ck_product_rates_..._rate_source_valid`)
— her ayrı `batch_alter_table` bloğu SQLite için tabloyu yeniden kurar ve bu
recreate, yansıtılan (reflected) VAR OLAN kısıtların adını kendi güncel adı
üzerinden yeniden işleyip bir kat daha önek ekliyor (ölçüldü: bu göçü ilk
yazışımda `product_rates`'e iki ayrı blokla dokunmak `rate_type_valid`'i TEK
recreate'te bile bulunamaz hâle getirdi). Bunu tekrarlamamak için bu göç HER
tabloya TEK bir `batch_alter_table` bloğuyla dokunur; var olan kısıtlar
`batch.f(...)` ile GERÇEK (hâlihazırdaki) adlarıyla düşürülüp temiz kısa adla
yeniden kurulur. `rate_type_valid` zaten temizdi (0009'da tek blokla
kurulmuştu); yalnızca değer listesi genişler. `rate_source_valid`'in
göç-öncesi katmanlı adı bilinçli olarak geri getirilmez — o isim bir
isimlendirme hatasının izidir, anlamlı bir durum değildir.

⚠️ `server_default` KALICI BIRAKILIR (`availability_status`, `data_source`).
0002/0009'un "geri doldurmadan sonra sunucu varsayılanını temizle" ilkesi
BURADA uygulanmaz: o ilke, varsayılanın YANLIŞ bir varsayım olabileceği
alanlar içindi (ör. `rate_source` boş bırakıldığında `html_table` sanılması
bankanın veri kalitesi hakkında yanlış izlenim verir). Buradaki iki alan
farklı: `data_source` belirtilmeyen HER satır gerçekten bankanın kendi
sitesinden gelir (bu projedeki mevcut TÜM scraper kodu için doğru); `availability_status`
belirtilmeyen her satır gerçekten "henüz araştırılmadı" demektir — ikisi de
alanın kendi tanımı gereği doğru varsayılan, gizlenen bir belirsizlik değil.
Kalıcı varsayılan aynı zamanda `product_rates`'e ikinci bir `batch_alter_table`
dokunuşunu (ve dolayısıyla yukarıdaki isim katmanlama riskini) gerektirmez.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.db.base import NAMING_CONVENTION
from app.db.migration_utils import gercek_check_adi

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


_ESKI_RATE_TYPES = "'financing_rate', 'participation_yield', 'profit_sharing_ratio'"
_YENI_RATE_TYPES = (
    "'financing_rate', 'participation_yield', 'profit_sharing_ratio', "
    "'interest_free_benevolent_loan'"
)

_ESKI_RATE_SOURCES = (
    "'html_table', 'payment_plan_derived', 'calculator_api', "
    "'calculator_playwright', 'text', 'js_default', 'none'"
)
_YENI_RATE_SOURCES = (
    "'html_table', 'payment_plan_derived', 'calculator_api', "
    "'calculator_playwright', 'text', 'js_default', 'none', 'seed_manual'"
)


def upgrade() -> None:
    """Yeni kolonları ve genişletilmiş sözlük kısıtlarını ekler (tablo başına tek recreate)."""
    # ── products ──────────────────────────────────────────
    # ⚠️ `recreate="always"` ZORUNLU. Birden fazla yeni kolon + bir CHECK
    # kısıtı aynı blokta eklendiğinde Alembic'in batch modu, `recreate`
    # varsayılan ("auto") kaldığında sütun sırasını çıkarırken
    # `CircularDependencyError` fırlatıyor (ölçüldü). `insert_after` ipucu
    # KULLANILMAZ — reflected tablo üzerinde art arda `insert_after` zincirlemek
    # bazı çalıştırmalarda `add_col_ordering` sözlüğünde henüz kaydedilmemiş
    # bir sütuna referans vererek `KeyError` fırlatıyor (ölçüldü, kararlı
    # değil); yeni kolonların tabloda hangi sırada durduğu önemli değil,
    # bu yüzden Alembic'in varsayılan (sona ekleme) sırasına bırakılır.
    with op.batch_alter_table(
        "products", naming_convention=NAMING_CONVENTION, recreate="always"
    ) as batch:
        batch.add_column(sa.Column("purchase_order", sa.Text(), nullable=True))
        batch.add_column(sa.Column("brand", sa.Text(), nullable=True))
        batch.add_column(sa.Column("model", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("availability_status", sa.Text(), nullable=False, server_default="unknown")
        )
        batch.create_check_constraint(
            "availability_status_valid",
            "availability_status IN ('offered', 'not_offered', 'unknown')",
        )

    # ── product_rates ─────────────────────────────────────
    with op.batch_alter_table("product_rates", naming_convention=NAMING_CONVENTION) as batch:
        batch.add_column(
            sa.Column("data_source", sa.Text(), nullable=False, server_default="bank_site")
        )
        batch.create_check_constraint(
            "data_source_valid", "data_source IN ('bank_site', 'tkbb_veripetegi')"
        )
        # ⚠️ `.f()` (op.f) KASITLI OLARAK KULLANILMAZ. Reflected (var olan)
        # kısıtlar, `naming_convention` aktifken batch'in iç `named_constraints`
        # sözlüğüne EK BİR KAT önekle işlenerek giriyor (bu göçün en üstteki
        # docstring'inde açıklanan tarihsel hatanın canlı kanıtı, ölçüldü).
        # `.f()` bu ek işlemeyi ATLAR ve DB'deki gerçek (tek katlı) adı arar —
        # ki `named_constraints` artık İKİ katlı anahtar taşıdığı için
        # `.f()` ile bulunamaz. Düz string vermek `drop_constraint`'in kendi
        # dönüşümünü bir kez daha uygulamasını sağlar ve reflected anahtarla
        # eşleşir.
        batch.drop_constraint("ck_product_rates_rate_type_valid", type_="check")
        batch.create_check_constraint("rate_type_valid", f"rate_type IN ({_YENI_RATE_TYPES})")
        batch.drop_constraint(
            gercek_check_adi(
                "product_rates", "rate_source_valid", "ck_product_rates_rate_source_valid"
            ),
            type_="check",
        )
        batch.create_check_constraint("rate_source_valid", f"rate_source IN ({_YENI_RATE_SOURCES})")


def downgrade() -> None:
    """Yeni kolonları ve genişletilmiş kısıtları kaldırır, eski değer listesine döner.

    ⚠️ `.f()` burada da KULLANILMAZ — bkz. `upgrade()` içindeki gerekçe. Düz
    string, reflected kısıtla eşleşmesi için gereken ek dönüşümü tetikler.

    Bu downgrade `rate_source_valid`'i TEMİZ adla yeniden kurar
    (`_ESKI_RATE_SOURCES` değer listesiyle). `upgrade()` düşürülecek kısıtın
    adını artık sabit yazmıyor, `gercek_check_adi()` ile veritabanından
    okuyor; bu yüzden "upgrade → downgrade → tekrar upgrade" döngüsü
    ADI NE OLURSA OLSUN çalışır. Sabit ad kullanıldığı sürece bu döngü
    kırılıyordu ve boş bir veritabanında `alembic upgrade head` hiç
    tamamlanamıyordu.
    """
    with op.batch_alter_table(
        "product_rates", naming_convention=NAMING_CONVENTION, recreate="always"
    ) as batch:
        batch.drop_constraint("ck_product_rates_rate_source_valid", type_="check")
        batch.drop_constraint("ck_product_rates_rate_type_valid", type_="check")
        batch.create_check_constraint("rate_type_valid", f"rate_type IN ({_ESKI_RATE_TYPES})")
        batch.create_check_constraint("rate_source_valid", f"rate_source IN ({_ESKI_RATE_SOURCES})")
        batch.drop_constraint("ck_product_rates_data_source_valid", type_="check")
        batch.drop_column("data_source")

    with op.batch_alter_table(
        "products", naming_convention=NAMING_CONVENTION, recreate="always"
    ) as batch:
        batch.drop_constraint("ck_products_availability_status_valid", type_="check")
        batch.drop_column("availability_status")
        batch.drop_column("model")
        batch.drop_column("brand")
        batch.drop_column("purchase_order")
