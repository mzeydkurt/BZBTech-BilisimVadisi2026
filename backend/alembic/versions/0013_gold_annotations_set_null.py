"""`gold_annotations.campaign_id` FK'sini SET NULL'a düzeltir.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-21

⚠️ GERÇEK VERİ KAYBI SONRASI YAZILDI. `app/db/models/gold_annotation.py`
`campaign_id` FK'sini `ondelete="SET NULL"` olarak tanımlıyor — migration
0008'in niyeti tam olarak buydu: "kolon nullable'a çevrilir ki yeniden
bağlanamayan satır SİLİNMEK zorunda kalmasın, kimlik `campaign_key`'de
durur". Ama 0008 yalnızca KOLONU nullable yaptı; FK kısıtının `ondelete`
sözcüğünü hiç değiştirmedi. Canlı veritabanında kısıt hâlâ migration
0004'ten kalma `ON DELETE CASCADE`.

Ölçüldü (21 Ağustos 2026): `delete_expired_campaigns.py` 231 süresi kesin
dolmuş kampanyayı silince bu CASCADE tetiklendi ve 886 elle etiketlenmiş
`gold_annotations` satırı SESSİZCE silindi — `reset_campaign_data.py`'nin
kendi docstring'inin tam olarak önlemeye çalıştığı senaryo ("880 satırlık
elle etiketleme işi kazara silinmesin"). Veri, silmeden hemen önce alınan
SQLite yedeğinden (`data/backups/`) `campaign_id=NULL` ile geri yüklendi;
bu göç yalnızca kısıtı modelin zaten beyan ettiği şeye getirir ki aynı hata
`sifirla`/`delete_expired_campaigns` her çalıştığında TEKRARLANMASIN.

Veri değiştirmez, yalnızca kısıtları düzeltir.

⚠️ `method_valid` CHECK'i AYNI BATCH'TE AÇIKÇA YENİDEN KURULUR. 0011'in
docstring'inin belgelediği mekanizma burada da tekrarlıyor: `recreate="always"`
+ `naming_convention` aktifken bir tabloyu yeniden kuran HER `batch_alter_table`
çağrısı, o çağrıda hiç dokunulmayan yansıtılmış (reflected) kısıtların adını
bile kendi güncel adı üzerinden yeniden işleyip bir kat daha önek ekliyor
(ölçüldü: bu göçü ilk yazışımda yalnızca FK'yi değiştirdim ve
`ck_gold_annotations_method_valid` tek seferde
`ck_gold_annotations_ck_gold_annotations_ck_gold_annotations_method_valid`
oldu). Çözüm 0011'deki ile aynı: dokunulmayan kısıt da AÇIKÇA düşürülüp temiz
adla yeniden kurulur ki tek recreate'te bozulmasın.
"""

from __future__ import annotations

from alembic import op
from app.db.base import NAMING_CONVENTION

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_FK_ADI = "fk_gold_annotations_campaign_id_campaigns"
_CHECK_ADI = "ck_gold_annotations_method_valid"


def upgrade() -> None:
    """FK'yi `ON DELETE CASCADE`'ten `ON DELETE SET NULL`'a çevirir."""
    with op.batch_alter_table(
        "gold_annotations", naming_convention=NAMING_CONVENTION, recreate="always"
    ) as batch:
        batch.drop_constraint(_FK_ADI, type_="foreignkey")
        batch.create_foreign_key(_FK_ADI, "campaigns", ["campaign_id"], ["id"], ondelete="SET NULL")
        # ⚠️ Dokunulmuyor gibi görünse de recreate bunu da yeniden adlandırır;
        # açıkça düşürüp temiz adla kurmak tek yol.
        batch.drop_constraint(_CHECK_ADI, type_="check")
        # ⚠️ TAM AD AÇIKÇA VERİLİR (kısa ad DEĞİL). Bu ad blok içinde
        # `naming_convention`'ın otomatik önek eklemesine güvenmez — ölçüldü,
        # bu bağlamda tutarsız davranıyor (bazen ekliyor, bazen eklemiyor).
        # Açık ad, sonucu diğer tüm `ck_<tablo>_<kısıt>` adlarıyla tutarlı
        # ve deterministik kılar.
        batch.create_check_constraint(_CHECK_ADI, "method IN ('blind', 'assisted')")


def downgrade() -> None:
    """FK'yi eski (hatalı) `ON DELETE CASCADE` hâline geri döndürür.

    ⚠️ Geri alma önerilmez: bu, düzeltilen veri kaybı riskini geri getirir.
    """
    with op.batch_alter_table(
        "gold_annotations", naming_convention=NAMING_CONVENTION, recreate="always"
    ) as batch:
        batch.drop_constraint(_FK_ADI, type_="foreignkey")
        batch.create_foreign_key(_FK_ADI, "campaigns", ["campaign_id"], ["id"], ondelete="CASCADE")
        batch.drop_constraint(_CHECK_ADI, type_="check")
        # ⚠️ TAM AD AÇIKÇA VERİLİR (kısa ad DEĞİL). Bu ad blok içinde
        # `naming_convention`'ın otomatik önek eklemesine güvenmez — ölçüldü,
        # bu bağlamda tutarsız davranıyor (bazen ekliyor, bazen eklemiyor).
        # Açık ad, sonucu diğer tüm `ck_<tablo>_<kısıt>` adlarıyla tutarlı
        # ve deterministik kılar.
        batch.create_check_constraint(_CHECK_ADI, "method IN ('blind', 'assisted')")
