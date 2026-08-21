"""Kontrollü sözlük testleri (SPRINT 2)

Buradaki testlerin çoğu "sözlük ile onu kullanan tablo birbirinden kopmasın"
diye vardır: bir kaynak eklenip güven katsayısı unutulursa oran sessizce 0
güvenle kaydedilir ve karşılaştırmadan düşer.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.vocab import (
    CATEGORY_SOURCES,
    RATE_SOURCE_CONFIDENCE,
    RATE_SOURCES,
    RATE_SOURCES_NOT_COMPARABLE,
    TAXONOMY_AXES,
    VARIANT_DIMENSIONS,
    VARIANT_KEYS,
    VARIANT_VOCAB,
    is_comparable,
    is_valid_variant,
    rate_confidence,
)


class TestVaryantSozlugu:
    """VARIANT_VOCAB tutarlılığı."""

    def test_sartnamedeki_alti_boyut_tanimli(self) -> None:
        """Şartnamenin 6 boyutu + KATİP'in eklediği 2 yeni boyut (alım sırası, marka/model)."""
        assert set(VARIANT_DIMENSIONS) == {
            "arac_durumu",
            "konut_durumu",
            "enerji_sinifi",
            "sigorta",
            "musteri_tipi",
            "ozel",
            "alim_sirasi",
            "marka_model",
        }

    def test_hicbir_boyut_bos_degil(self) -> None:
        """`marka_model` KASITLI OLARAK istisnadır — bkz. VARIANT_VOCAB yorumu.

        Marka/model anahtarları (`togg_t10x` gibi) `brand`/`model` kolonlarından
        türetilir, önceden bilinen sabit bir liste değildir.
        """
        for boyut, anahtarlar in VARIANT_VOCAB.items():
            if boyut == "marka_model":
                continue
            assert anahtarlar, f"{boyut} boş"

    def test_anahtarlar_boyutlar_arasinda_tekil(self) -> None:
        """Aynı anahtar iki boyutta geçerse `variant_key` tek başına anlamsızlaşır.

        Karşılaştırma `variant_key` üzerinden yapıldığı için, bir anahtarın
        hangi boyuta ait olduğu belirsiz kalırsa "sigortalı konut" ile
        "sigortalı taşıt" aynı kovaya düşer.
        """
        tum = [anahtar for anahtarlar in VARIANT_VOCAB.values() for anahtar in anahtarlar]
        assert len(tum) == len(set(tum))

    def test_anahtarlar_kanonik_bicimde(self) -> None:
        """Türkçe karakter ve büyük harf içermez; slug biçimindedir."""
        for anahtar in VARIANT_KEYS:
            assert anahtar == anahtar.lower()
            assert anahtar.replace("_", "").isalnum()
            assert anahtar.isascii()

    @pytest.mark.parametrize(
        ("boyut", "anahtar"),
        [
            ("arac_durumu", "sifir_arac"),
            ("konut_durumu", "ikinci_el_konut"),
            ("sigorta", "sigortali"),
            ("enerji_sinifi", "enerji_a"),
        ],
    )
    def test_gecerli_varyant_kabul_edilir(self, boyut: str, anahtar: str) -> None:
        assert is_valid_variant(boyut, anahtar)

    @pytest.mark.parametrize(
        ("boyut", "anahtar"),
        [
            # Doğru anahtar ama YANLIŞ boyut.
            ("arac_durumu", "sifir_konut"),
            ("sigorta", "enerji_a"),
            # Hiç tanımlı olmayanlar.
            ("arac_durumu", "ucan_araba"),
            ("bilinmeyen_boyut", "sifir_arac"),
        ],
    )
    def test_gecersiz_varyant_reddedilir(self, boyut: str, anahtar: str) -> None:
        assert not is_valid_variant(boyut, anahtar)


class TestOranKaynagi:
    """RATE_SOURCES ve güven katsayıları."""

    def test_her_kaynagin_guven_katsayisi_var(self) -> None:
        """Katsayısı unutulan bir kaynak, oranı sessizce 0 güvene düşürür."""
        assert set(RATE_SOURCE_CONFIDENCE) == set(RATE_SOURCES)

    def test_katsayilar_sifir_bir_araliginda(self) -> None:
        for kaynak, katsayi in RATE_SOURCE_CONFIDENCE.items():
            assert Decimal("0") <= katsayi <= Decimal("1"), kaynak

    def test_html_tablosu_en_guvenilir(self) -> None:
        """Bankanın kendi yayımladığı tablo birincil kaynaktır.

        ⚠️ `seed_manual`/`pdf_table` İSTİSNADIR: `seed_manual` kullanıcının
        otomasyonun çalışmadığı bir ortamda bankanın kendi yayımladığı
        tabloyu bizzat tarayıp birebir elle girdiği veridir (KATİP KAPI 4);
        `pdf_table` bankanın aynı yapısal tabloyu PDF paketinde yayımladığı
        durumdur (TOM Bank). İkisi de `html_table` ile AYNI nihai kaynağın
        farklı bir toplama/paketleme yöntemi, tahmin değil. Bu yüzden
        1.000'e eşit tutulur; yalnızca gerçekten daha zayıf/dolaylı kaynaklar
        (ödeme planı türetimi, hesaplayıcı, metin, js varsayılanı) kesin
        olarak düşüktür.
        """
        assert RATE_SOURCE_CONFIDENCE["html_table"] == Decimal("1.000")
        digerleri = [
            k
            for ad, k in RATE_SOURCE_CONFIDENCE.items()
            if ad not in ("html_table", "seed_manual", "pdf_table")
        ]
        assert all(katsayi < Decimal("1.000") for katsayi in digerleri)

    def test_guven_sirasi_sartnameye_uygun(self) -> None:
        """§2.6'daki sıralama: tablo > ödeme planı > api > playwright > metin > js."""
        sirali = [
            "html_table",
            "payment_plan_derived",
            "calculator_api",
            "calculator_playwright",
            "text",
            "js_default",
            "none",
        ]
        katsayilar = [RATE_SOURCE_CONFIDENCE[ad] for ad in sirali]
        assert katsayilar == sorted(katsayilar, reverse=True)

    def test_bilinmeyen_kaynak_sifir_doner(self) -> None:
        assert rate_confidence("uydurma_kaynak") == Decimal("0.000")

    def test_js_varsayilani_karsilastirmaya_girmez(self) -> None:
        """JS bundle'ındaki sabit, bankanın uyguladığı oran DEĞİLDİR."""
        assert not is_comparable("js_default")
        assert not is_comparable("none")

    def test_gercek_kaynaklar_karsilastirmaya_girer(self) -> None:
        for kaynak in RATE_SOURCES:
            if kaynak in RATE_SOURCES_NOT_COMPARABLE:
                continue
            assert is_comparable(kaynak), kaynak


class TestTaksonomiSozlugu:
    """Taksonomi eksenleri ve etiket kaynakları."""

    def test_dort_dik_eksen(self) -> None:
        assert TAXONOMY_AXES == ("product_type", "sector", "audience", "benefit")

    def test_llm_kaynagi_tanimli_ama_sprint2de_uretilmez(self) -> None:
        """`llm` şemada geçerlidir; SPRINT 3'te doldurulacak.

        SPRINT 2'de üretilen her etiket kural tabanlıdır.
        """
        assert "llm" in CATEGORY_SOURCES
        kural_tabanli = set(CATEGORY_SOURCES) - {"llm"}
        assert kural_tabanli == {"url", "bank_category", "keyword", "merchant"}
