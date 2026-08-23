"""Ürün açıklama çıkarımı birim testleri."""

from __future__ import annotations

from app.processing.product_description import extract_product_description


def test_nedir_paragrafi_alinir() -> None:
    metin = (
        "Taşıt Finansmanı (Taşıt Kredisi)*\n"
        "Araç / Taşıt Finansmanı (Taşıt Kredisi)* Nedir?\n"
        "Araç / Taşıt Finansmanı (bankacılık kanununa göre taşıt kredisi)* "
        "0 km ya da 2. el araç alımı için katılım bankaları tarafından gerçek "
        "kişilere sağlanan finansman desteğidir.\n"
        "Çerez politikası\n"
    )
    aciklama = extract_product_description(metin, title="Taşıt Finansmanı (Taşıt Kredisi)*")
    assert aciklama is not None
    assert "finansman desteğidir" in aciklama
    assert "çerez" not in aciklama.casefold()


def test_internet_subesi_gecerken_paragraf_elenmez() -> None:
    """'internet şubesinden başvur' ürün metninde geçebilir — tüm paragraf atılmaz."""
    metin = (
        "İhtiyaç Finansmanı\n"
        "İhtiyaç finansmanına şubelerden, mobilden, internet şubesinden veya "
        "çağrı merkezinden başvur, sunduğu avantajlardan sen de yararlan. "
        "36 aya varan vade seçenekleri ile bütçene uygun ödeme koşulları sunar.\n"
    )
    aciklama = extract_product_description(metin, title="İhtiyaç Finansmanı")
    assert aciklama is not None
    assert "36 aya varan" in aciklama


def test_sadece_menu_none() -> None:
    assert extract_product_description("Hesaplar | Kartlar | Finansmanlar | ATM") is None


def test_aciklama_cumle_ortasinda_kesilmez() -> None:
    """Uzun metin azamiyi aşsa bile son tam cümlede biter; '…' eklenmez."""
    cumle = (
        "Konut finansmanı, katılım bankaları tarafından gerçek kişilere "
        "konut edinimleri için sağlanan finansman desteğidir. "
    )
    metin = "Konut Finansmanı Nedir?\n" + (cumle * 80)
    aciklama = extract_product_description(metin, title="Konut Finansmanı")
    assert aciklama is not None
    assert not aciklama.endswith("…")
    assert not aciklama.endswith("...")
    assert aciklama.rstrip()[-1] in ".!?"


def test_yumusak_satir_kirigi_birlesir() -> None:
    metin = (
        "İhtiyaç Finansmanı Nedir?\n"
        "İhtiyaç finansmanı, bireysel ihtiyaçlarınız için sağlanan\n"
        "finansman desteğidir. Şubelerden başvurabilirsiniz.\n"
        "İhtiyaç Finansmanı Başvurusu Nasıl Yapılır?\n"
        "Kimlik belgesi ile başvurun.\n"
    )
    aciklama = extract_product_description(metin, title="İhtiyaç Finansmanı")
    assert aciklama is not None
    assert "finansman desteğidir" in aciklama
    assert "Kimlik belgesi" not in aciklama
