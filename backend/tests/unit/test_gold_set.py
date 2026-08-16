"""Gold set örnekleme ve etiketleme uçları.

⚠️ BURADAKİ EN ÖNEMLİ TEST "∅ ile boş bırakma ayrımı"dır. Ayrım kaybolursa
sistemin halüsinasyonu ölçülemez: metinde bilgi yokken üretilen bir değer,
"etiketleyici atlamış" ile aynı görünür.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Bank, Campaign, GoldAnnotation, SourceDocument
from app.services.gold_service import (
    BLIND_COUNT,
    annotation_method,
    collect_candidates,
    gold_progress,
    sample_gold_set,
)

UZUN_METIN = "Kampanya koşulu cümlesi burada yer alıyor. " * 20


def _kampanya(
    session: Session,
    bank: Bank,
    slug: str,
    metin: str,
    *,
    baslangic: date | None = None,
    bitis: date | None = None,
) -> Campaign:
    """Kaynak belgesiyle birlikte kampanya oluşturur."""
    belge = SourceDocument(
        bank_id=bank.id,
        url=f"https://ornek.com.tr/{slug}",
        url_hash=slug,
        doc_type="campaign",
        clean_text=metin,
    )
    session.add(belge)
    session.flush()

    kampanya = Campaign(
        bank_id=bank.id,
        source_document_id=belge.id,
        external_slug=slug,
        title=f"Kampanya {slug}",
        source_url=belge.url,
        start_date=baslangic,
        end_date=bitis,
        date_precision="exact" if baslangic else "unknown",
        status="active" if baslangic else "unknown",
    )
    session.add(kampanya)
    session.flush()
    return kampanya


@pytest.fixture
def banka(db_session: Session) -> Bank:
    """Test bankası."""
    bank = Bank(code="ornek_katilim", name="Örnek Katılım", website="https://ornek.com.tr")
    db_session.add(bank)
    db_session.flush()
    return bank


# ── Zorluk tespiti ────────────────────────────────────────


def test_tarihsiz_kampanya_zor_vaka(db_session: Session, banka: Bank) -> None:
    """⚠️ Türkiye Finans'ın TÜM kampanyaları böyle.

    Sistemin bu kayıtlarda tarih UYDURMAMASI gerekir; ölçümün can alıcı
    noktası budur.
    """
    _kampanya(db_session, banka, "tarihsiz", UZUN_METIN)

    adaylar, _, _ = collect_candidates(db_session)

    assert adaylar[0].is_difficult
    assert "tarih verisi yok" in adaylar[0].difficulty_reasons


def test_dolayli_ifade_zor_vaka(db_session: Session, banka: Bank) -> None:
    """ "avantajlı kâr payı" bir oran DEĞİLDİR; etiketleyicinin en çok yanıldığı yer."""
    _kampanya(
        db_session,
        banka,
        "dolayli",
        "Konut finansmanında avantajlı kâr payı fırsatı. " + UZUN_METIN,
        baslangic=date(2026, 1, 1),
        bitis=date(2026, 12, 31),
    )

    adaylar, _, _ = collect_candidates(db_session)

    assert any("dolaylı ifade" in gerekce for gerekce in adaylar[0].difficulty_reasons)


def test_kademeli_odul_zor_vaka(db_session: Session, banka: Bank) -> None:
    """Kademeli ödülde hangi tutarın eşik hangisinin ödül olduğu karışır."""
    _kampanya(
        db_session,
        banka,
        "kademeli",
        # ⚠️ Bilinçli olarak few-shot örneğinden FARKLI tutarlar: aynı metin
        # kullanılsaydı sızıntı filtresi kaydı eler ve test hiçbir şey ölçmezdi.
        "3.000 TL ve üzeri harcamalarda 150 TL, 7.500 TL ve üzeri harcamalarda 400 TL. "
        + UZUN_METIN,
        baslangic=date(2026, 1, 1),
        bitis=date(2026, 12, 31),
    )

    adaylar, _, _ = collect_candidates(db_session)

    assert "kademeli ödül yapısı" in adaylar[0].difficulty_reasons


def test_kisa_metin_zor_vaka(db_session: Session, banka: Bank) -> None:
    """Kısa metinde çıkarılacak bilgi yoktur; sistemin susması beklenir."""
    _kampanya(
        db_session,
        banka,
        "kisa",
        "Kısa kampanya.",
        baslangic=date(2026, 1, 1),
        bitis=date(2026, 12, 31),
    )

    adaylar, _, _ = collect_candidates(db_session)

    assert "kısa/eksik metin" in adaylar[0].difficulty_reasons


def test_kolay_kampanya_zor_isaretlenmez(db_session: Session, banka: Bank) -> None:
    """Zorluk gerekçesi yoksa kayıt kolay vakadır."""
    _kampanya(
        db_session,
        banka,
        "kolay",
        "Bu kampanyada özel bir durum bulunmuyor. " * 15,
        baslangic=date(2026, 1, 1),
        bitis=date(2026, 12, 31),
    )

    adaylar, _, _ = collect_candidates(db_session)

    assert not adaylar[0].is_difficult


# ── Sızıntı koruması ──────────────────────────────────────


def test_few_shot_metni_ornekleme_girmez(db_session: Session, banka: Bank) -> None:
    """⚠️ Modele örnek olarak gösterilen metin, test kaydı OLAMAZ.

    Aynı kaydı hem few-shot örneği hem gold set kaydı yapmak sızıntıdır:
    model cevabı ezberler ve F1 gerçekte olduğundan yüksek çıkar.
    """
    _kampanya(
        db_session,
        banka,
        "sizintili",
        "Colin's mağazalarında Kuveyt Türk kredi kartınızla alışveriş. " + UZUN_METIN,
    )
    _kampanya(db_session, banka, "temiz", UZUN_METIN)

    adaylar, few_shot, _ = collect_candidates(db_session)

    assert few_shot == 1
    assert [a.campaign_id for a in adaylar] and all("Colin's" not in a.clean_text for a in adaylar)


def test_metni_bos_kampanya_ornekleme_girmez(db_session: Session, banka: Bank) -> None:
    """Okunacak metni olmayan kayıt etiketlenemez."""
    _kampanya(db_session, banka, "bos", "")

    adaylar, _, bos = collect_candidates(db_session)

    assert bos == 1
    assert adaylar == []


# ── Örnekleme ─────────────────────────────────────────────


def test_orneklem_deterministik(db_session: Session, banka: Bank) -> None:
    """⚠️ Aynı veritabanında aynı kayıtlar seçilmeli.

    Örneklem değişirse iki değerlendirme farklı kümeler üzerinde ölçüm yapar
    ve F1 değerleri karşılaştırılamaz.
    """
    for i in range(20):
        _kampanya(db_session, banka, f"k{i}", f"Kampanya {i}. " + UZUN_METIN)

    ilk = sample_gold_set(db_session, size=10)
    ikinci = sample_gold_set(db_session, size=10)

    assert [a.campaign_id for a in ilk.candidates] == [a.campaign_id for a in ikinci.candidates]


def test_orneklem_hedef_boyutu_asmaz(db_session: Session, banka: Bank) -> None:
    """Kota adımları hedefi aşsa bile kırpma yapılır."""
    for i in range(40):
        _kampanya(db_session, banka, f"k{i}", f"Kampanya {i}. " + UZUN_METIN)

    sonuc = sample_gold_set(db_session, size=12)

    assert len(sonuc.candidates) == 12


def test_kirpma_zor_vakalari_korur(db_session: Session, banka: Bank) -> None:
    """⚠️ Hedefe kırparken kolay kayıtlar önce atılır.

    Zor vakalar kırpılırsa sistemin en zayıf olduğu yerler hiç ölçülmez.
    """
    for i in range(10):
        _kampanya(db_session, banka, f"zor{i}", f"Kampanya {i}. " + UZUN_METIN)  # tarihsiz = zor
    for i in range(10):
        _kampanya(
            db_session,
            banka,
            f"kolay{i}",
            f"Sıradan kampanya {i}. " + UZUN_METIN,
            baslangic=date(2026, 1, 1),
            bitis=date(2026, 12, 31),
        )

    sonuc = sample_gold_set(db_session, size=10)

    assert sonuc.difficult_count == 10


def test_ilk_otuz_kayit_kor(db_session: Session) -> None:
    """⚠️ Kör alt küme yanlılık ölçümünün temeli; sıra atlanmamalı."""
    assert annotation_method(0) == "blind"
    assert annotation_method(BLIND_COUNT - 1) == "blind"
    assert annotation_method(BLIND_COUNT) == "assisted"


# ── Etiketleme uçları ─────────────────────────────────────


def test_alan_listesi_cikarim_ile_ayni(api_client: TestClient) -> None:
    """Etiketleme ile çıkarım aynı alan listesini kullanmalı.

    Ayrışırlarsa değerlendirme, sistemin hiç üretmediği bir alanı
    "kaçırılmış" sayar.
    """
    from app.ai.fields import EXTRACTABLE_FIELDS

    yanit = api_client.get("/api/v1/annotate/fields")

    assert yanit.status_code == 200
    veri = yanit.json()
    assert set(veri) == set(EXTRACTABLE_FIELDS)
    assert veri["profit_rate_pct"]["unit"] == "pct"


def test_enum_alanlar_kontrollu_sozluk_sunar(api_client: TestClient) -> None:
    """⚠️ Enum alanlar serbest yazılmamalı.

    Etiketleyici "eticaret_pazaryeri" yerine "e-ticaret" yazarsa değerlendirme
    bunu "sistem yanlış buldu" sayar; hata sistemde değil gold set'tedir ve
    fark edilmesi neredeyse imkânsızdır.
    """
    veri = api_client.get("/api/v1/annotate/fields").json()

    assert "eticaret_pazaryeri" in veri["sector"]["options"]
    assert "konut_finansmani" in veri["product_type"]["options"]
    assert "emekli" in veri["target_customer"]["options"]
    assert "nakit_iade" in veri["reward_type"]["options"]
    # Sayısal alanlarda seçenek listesi olmaz.
    assert veri["profit_rate_pct"]["options"] == []


def test_bos_alan_ile_etiketlenmemis_alan_ayri_kaydedilir(
    api_client: TestClient, db_session: Session, banka: Bank
) -> None:
    """⚠️ BU TESTİN KORUDUĞU AYRIM OLMADAN HALÜSİNASYON ÖLÇÜLEMEZ.

    Gövdede `value=null` ile gönderilen alan ∅'dir ("metinde YOK") ve KAYIT
    OLUŞTURUR. Gövdede hiç bulunmayan alan için kayıt oluşturulmaz.
    """
    kampanya = _kampanya(db_session, banka, "test", UZUN_METIN)
    db_session.commit()

    yanit = api_client.post(
        f"/api/v1/annotate/{kampanya.id}",
        json={
            "annotator": "zeyd",
            "method": "blind",
            "fields": {
                # ∅ — metinde yok
                "profit_rate_pct": {"value": None, "evidence": None, "unit": "pct"},
                # gerçek değer
                "installment_count": {"value": "4", "evidence": "4 aya varan", "unit": "count"},
                # `end_date` HİÇ gönderilmedi = etiketlenmedi
            },
        },
    )

    assert yanit.status_code == 201

    kayitlar = {
        k.field_name: k
        for k in db_session.scalars(
            select(GoldAnnotation).where(GoldAnnotation.campaign_id == kampanya.id)
        )
    }
    assert set(kayitlar) == {"profit_rate_pct", "installment_count"}
    assert kayitlar["profit_rate_pct"].gold_value is None  # ∅ kaydedildi
    assert kayitlar["installment_count"].gold_value == "4"
    assert "end_date" not in kayitlar  # etiketlenmedi → kayıt yok


def test_ayni_alan_tekrar_gonderilince_guncellenir(
    api_client: TestClient, db_session: Session, banka: Bank
) -> None:
    """Düzeltme yeni satır açmaz, mevcut kaydı günceller."""
    kampanya = _kampanya(db_session, banka, "duzeltme", UZUN_METIN)
    db_session.commit()

    govde = {
        "annotator": "zeyd",
        "method": "blind",
        "fields": {"installment_count": {"value": "4", "evidence": "4 aya", "unit": "count"}},
    }
    api_client.post(f"/api/v1/annotate/{kampanya.id}", json=govde)

    govde["fields"]["installment_count"]["value"] = "6"  # type: ignore[index]
    api_client.post(f"/api/v1/annotate/{kampanya.id}", json=govde)

    kayitlar = list(
        db_session.scalars(select(GoldAnnotation).where(GoldAnnotation.campaign_id == kampanya.id))
    )
    assert len(kayitlar) == 1
    assert kayitlar[0].gold_value == "6"


def test_tanimsiz_alan_reddedilir(api_client: TestClient, db_session: Session, banka: Bank) -> None:
    """⚠️ Yazım hatası olan alan sessizce yok sayılmaz.

    Yok sayılırsa etiketlenmiş sanılır ve değerlendirmede "sistem kaçırdı"
    olarak görünür.
    """
    kampanya = _kampanya(db_session, banka, "hatali", UZUN_METIN)
    db_session.commit()

    yanit = api_client.post(
        f"/api/v1/annotate/{kampanya.id}",
        json={
            "annotator": "zeyd",
            "method": "blind",
            "fields": {"kar_payi": {"value": "2.05", "evidence": "x", "unit": "pct"}},
        },
    )

    assert yanit.status_code == 422
    # Proje tek biçimli hata zarfı kullanıyor: {"error": {code, message, detail}}
    assert "kar_payi" in yanit.json()["error"]["message"]


def test_gecersiz_yontem_reddedilir(
    api_client: TestClient, db_session: Session, banka: Bank
) -> None:
    """`blind`/`assisted` dışında bir yöntem yanlılık ölçümünü bozar."""
    kampanya = _kampanya(db_session, banka, "yontem", UZUN_METIN)
    db_session.commit()

    yanit = api_client.post(
        f"/api/v1/annotate/{kampanya.id}",
        json={"annotator": "zeyd", "method": "yarim_kor", "fields": {}},
    )

    assert yanit.status_code == 422


def test_olmayan_kampanya_404(api_client: TestClient) -> None:
    """Var olmayan kampanyaya etiket yazılamaz."""
    yanit = api_client.post(
        "/api/v1/annotate/999999", json={"annotator": "zeyd", "method": "blind", "fields": {}}
    )

    assert yanit.status_code == 404


def test_ilerleme_bos_alanlari_ayri_sayar(
    api_client: TestClient, db_session: Session, banka: Bank
) -> None:
    """∅ işaretli alan sayısı ayrı raporlanır: halüsinasyon ölçümünün paydası."""
    kampanya = _kampanya(db_session, banka, "ilerleme", UZUN_METIN)
    db_session.commit()

    api_client.post(
        f"/api/v1/annotate/{kampanya.id}",
        json={
            "annotator": "zeyd",
            "method": "blind",
            "is_difficult": True,
            "fields": {
                "profit_rate_pct": {"value": None, "evidence": None, "unit": "pct"},
                "end_date": {"value": None, "evidence": None, "unit": "date"},
                "installment_count": {"value": "4", "evidence": "4 aya", "unit": "count"},
            },
        },
    )

    veri = api_client.get("/api/v1/annotate/progress").json()

    assert veri["annotated_campaigns"] == 1
    assert veri["total_annotations"] == 3
    assert veri["explicit_null_fields"] == 2
    assert veri["blind_campaigns"] == 1
    assert veri["difficult_campaigns"] == 1


def test_ilerleme_servisi_bos_veritabaninda_calisir(db_session: Session) -> None:
    """Hiç etiket yokken sıfırlarla döner, hata vermez."""
    ilerleme = gold_progress(db_session)

    assert ilerleme.annotated_campaigns == 0
    assert ilerleme.explicit_null_fields == 0
