"""Prompt altyapısı: yükleme, sürüm yönetimi, şema ve bölümleme.

Buradaki testlerin ortak amacı, MODELE EKSİK YA DA BOZUK İSTEM GİTMESİNİ
engellemektir. Doldurulmamış bir `{clean_text}` yer tutucusu ya da sessizce
kırpılmış bir metin, hata vermeden yalnızca F1'i düşürür — ve nedeni
bulunamaz.
"""

from __future__ import annotations

import json

import pytest

from app.ai.chunking import chunk_for_llm
from app.ai.fields import (
    EXTRACTABLE_FIELDS,
    EXTRACTION_SCHEMA,
    MAX_PROMPT_CHARS,
    build_extraction_schema,
    unit_of,
)
from app.ai.prompts import (
    FEW_SHOT_MARKERS,
    PROMPT_NAMES,
    PromptError,
    available_versions,
    contains_few_shot_example,
    load_prompt,
)

# ── Prompt yükleme ────────────────────────────────────────


def test_tanimli_tum_promptlar_diskte_var() -> None:
    """Her prompt adı için en az bir sürüm dosyası bulunmalı."""
    for ad in PROMPT_NAMES:
        assert available_versions(ad), f"{ad} için sürüm dosyası yok"


def test_sistem_prompt_katilim_terminolojisini_dayatiyor() -> None:
    """⚠️ Sistem istemi yasaklı terimleri açıkça saymalı.

    Model "faiz" yazarsa çıktı alan gereğine aykırıdır; kuralın prompt'ta
    bulunması bu davranışın tek dayanağıdır.
    """
    metin = load_prompt("system", "v1")

    assert "kâr payı" in metin
    assert 'asla "faiz"' in metin
    assert "finansman" in metin


def test_sistem_prompt_dil_kilidi_iceriyor() -> None:
    """⚠️ Qwen ailesi belirsizlikte ÇİNCEYE KAYIYOR.

    Türkçe bu modeller için düşük kaynaklı bir dil; model emin olmadığında
    eğitim verisinin ağırlıklı diline dönüyor. Açık dil kilidi bunun ilk
    savunma katmanı (ikincisi: kanıtın kaynakta birebir aranması, KAPI A7).
    """
    metin = load_prompt("system", "v1")

    assert "TAMAMI Türkçe" in metin
    assert "Çince" in metin


def test_sistem_prompt_bilgi_yoksa_null_diyor() -> None:
    """ "Bilgi yokken bilgi üretme" kuralı prompt'ta yazılı olmalı (şartname 7)."""
    metin = load_prompt("system", "v1")

    assert "null döndür" in metin
    assert "tahmin etme" in metin


def test_cikarim_prompti_yer_tutuculari_doldurulur() -> None:
    """`{requested_fields}` ve `{clean_text}` yerine gerçek değerler geçer."""
    metin = load_prompt(
        "extract", "v1", requested_fields="profit_rate_pct, end_date", clean_text="ÖRNEK METİN"
    )

    assert "profit_rate_pct, end_date" in metin
    assert "ÖRNEK METİN" in metin
    assert "{clean_text}" not in metin


def _json_bloklari(metin: str) -> list[str]:
    """Metindeki en dış düzey JSON nesnelerini parantez eşleyerek çıkarır."""
    bloklar: list[str] = []
    derinlik = 0
    bas = -1

    for indeks, karakter in enumerate(metin):
        if karakter == "{":
            if derinlik == 0:
                bas = indeks
            derinlik += 1
        elif karakter == "}" and derinlik:
            derinlik -= 1
            if derinlik == 0:
                bloklar.append(metin[bas : indeks + 1])
    return bloklar


def test_cikarim_promptindeki_json_ornekleri_gecerli_kalir() -> None:
    """⚠️ `.format()` sonrası JSON örnekleri BOZULMAMALI.

    Örneklerdeki süslü parantezler `{{ }}` ile kaçırılmazsa `.format()` onları
    yer tutucu sanar; ya hata verir ya da örnekleri sessizce siler ve model
    beklenen çıktı biçimini hiç görmez.
    """
    metin = load_prompt("extract", "v1", requested_fields="x", clean_text="y")

    bloklar = _json_bloklari(metin)
    assert len(bloklar) == 3, "üç few-shot örneğinin çıktısı da bulunmalı"

    ayristirilan = [json.loads(blok) for blok in bloklar]
    # Örnek 2 "bilgi yok" örneğidir: tüm alanları null olmalı.
    assert all(alan == {"value": None, "evidence": None} for alan in ayristirilan[1].values())


def test_eksik_yer_tutucu_sessizce_gecilmez() -> None:
    """⚠️ `{clean_text}` doldurulmadan istem üretilemez.

    Kaynak metni görmeyen model "bilgi yok" yerine UYDURMAYA yönelir.
    """
    with pytest.raises(PromptError, match="clean_text"):
        load_prompt("extract", "v1", requested_fields="x")


def test_olmayan_prompt_acik_hata_verir() -> None:
    """Yanlış sürüm istendiğinde mevcut sürümler mesajda listelenir."""
    with pytest.raises(PromptError, match=r"extract_v99\.txt"):
        load_prompt("extract", "v99")


def test_surum_ayardan_okunur() -> None:
    """Sürüm verilmezse `PROMPT_VERSION` ayarı kullanılır."""
    assert load_prompt("system") == load_prompt("system", "v1")


# ── Few-shot sızıntı koruması ─────────────────────────────


def test_few_shot_isaretleri_promptta_gercekten_geciyor() -> None:
    """İşaretler prompt metniyle uyumlu olmalı.

    Uyumsuz bir işaret, gold set'ten yanlış kayıtları eler ya da sızıntıyı
    hiç yakalamaz.
    """
    metin = load_prompt("extract", "v1", requested_fields="x", clean_text="y")

    for isaret in FEW_SHOT_MARKERS:
        assert isaret in metin, f"few-shot işareti prompt'ta yok: {isaret!r}"


def test_few_shot_metni_gold_setten_elenebilir() -> None:
    """⚠️ Örnek olarak modele gösterilen metin, test kaydı OLAMAZ.

    Aynı kaydı hem örnek hem test yapmak sızıntıdır: model cevabı ezberler ve
    F1 gerçekte olduğundan yüksek çıkar.
    """
    sizintili = "... Colin's mağazalarında Kuveyt Türk kredi kartınızla alışveriş ..."

    assert contains_few_shot_example(sizintili) is True
    assert contains_few_shot_example("Alakasız bir kampanya metni") is False
    assert contains_few_shot_example(None) is False


# ── Şema ──────────────────────────────────────────────────


def test_sema_tum_alanlari_kapsiyor() -> None:
    """Varsayılan şema, tanımlı her alanı içerir."""
    assert set(EXTRACTION_SCHEMA["properties"]) == set(EXTRACTABLE_FIELDS)


def test_her_alan_deger_ve_kanit_ister() -> None:
    """⚠️ `evidence` şemada ZORUNLU.

    Kanıtsız bir değer doğrulanamaz; halüsinasyon guard'ının (KAPI A7)
    substring denetimi kanıt alanına dayanır.
    """
    for alan, tanim in EXTRACTION_SCHEMA["properties"].items():
        assert tanim["required"] == ["value", "evidence"], alan


def test_alt_kume_semasi_uretilebilir() -> None:
    """KAPI A6: kuralın çözdüğü alanlar şemadan çıkarılır."""
    sema = build_extraction_schema(["profit_rate_pct", "end_date"])

    assert set(sema["properties"]) == {"profit_rate_pct", "end_date"}


def test_tanimsiz_alan_sessizce_yok_sayilmaz() -> None:
    """Yazım hatası olan alan "çıkarılamadı" gibi görünmemeli."""
    with pytest.raises(ValueError, match="kar_payi"):
        build_extraction_schema(["kar_payi"])


def test_her_alanin_birimi_var() -> None:
    """Birimsiz alan olmaz: `2.05` oran mı tutar mı belli olmalı.

    ⚠️ `json` DA GEÇERLİ BİR BİRİMDİR. `tier_structure` tek bir sayı değil
    eşik→ödül çiftlerinin listesi; sayısal bir birim verilirse doğrulama
    katmanı (KAPI A7 katman 4) gövdeyi sayıya çevirmeye çalışır ve alanı
    her seferinde reddeder. Birimin adı, o katmanın alanı MUAF sayması için
    `NUMERIC_UNITS` dışında olmak zorunda.
    """
    gecerli = {"pct", "TRY", "month", "count", "bool", "date", "enum", "json"}

    for alan in EXTRACTABLE_FIELDS:
        assert unit_of(alan) in gecerli, alan


def test_kar_payi_ve_kar_paylasim_ayri_alanlar() -> None:
    """⚠️ Finansmandaki kâr payı ile katılma hesabındaki pay AYRI.

    Yönleri terstir: biri müşterinin ödediği, diğeri bankanın dağıttığı.
    Tek alanda toplanırsa karşılaştırma anlamsızlaşır.
    """
    assert "profit_rate_pct" in EXTRACTABLE_FIELDS
    assert "profit_share_rate_pct" in EXTRACTABLE_FIELDS


# ── Bölümleme ─────────────────────────────────────────────


def test_kisa_metin_bolunmez() -> None:
    """Sığan metin tek çağrıda gider."""
    assert chunk_for_llm("Kısa bir kampanya metni.") == ["Kısa bir kampanya metni."]


def test_bos_metin_bos_liste_dondurur() -> None:
    """Boş metin için model çağrısı yapılmamalı."""
    assert chunk_for_llm("") == []
    assert chunk_for_llm(None) == []
    assert chunk_for_llm("   \n  ") == []


def test_uzun_metin_bolunur_ve_hicbir_parca_siniri_asmaz() -> None:
    """⚠️ Sınırı aşan istem SESSİZCE KIRPILIR; parça sınırı sert olmalı."""
    metin = "\n\n".join(f"Paragraf {i}. " + "kampanya koşulu " * 40 for i in range(20))

    parcalar = chunk_for_llm(metin, max_chars=1000)

    assert len(parcalar) > 1
    assert all(len(p) <= 1000 for p in parcalar)


def test_bolumler_verilirse_baslik_parcaya_yazilir() -> None:
    """⚠️ Başlıksız madde listesi yanlış alana eşlenir.

    Hariç tutma bölümündeki bir tutar, kampanya ödülü sanılabilir.
    """
    bolumler = {
        "Kampanya Şartları": "koşul metni " * 300,
        "Kampanya Dışı Ürünler": "hariç tutulan " * 300,
    }

    parcalar = chunk_for_llm("uzun " * 3000, bolumler, max_chars=2000)

    assert any("[Kampanya Şartları]" in p for p in parcalar)
    assert any("[Kampanya Dışı Ürünler]" in p for p in parcalar)


def test_uzun_paragraf_cumle_sinirindan_bolunur() -> None:
    """⚠️ Gerçek banka metinlerinin asıl yolu bu.

    Dünya Katılım gibi bankalarda gövde tek bir uzun paragraf hâlinde geliyor.
    Cümle sınırı gözetilmezse parça bir cümlenin ortasında kesilir ve
    "31.12.2026 tarihine kadar" ifadesi ikiye bölünüp tarih hiç bulunamaz.
    """
    paragraf = " ".join(f"Kampanya koşulu numarası {i} geçerlidir." for i in range(200))

    parcalar = chunk_for_llm(paragraf, max_chars=800)

    assert len(parcalar) > 1
    assert all(len(p) <= 800 for p in parcalar)
    # Hiçbir parça cümle ortasında bitmemeli.
    assert all(p.rstrip().endswith(".") for p in parcalar)


def test_tek_dev_paragraf_da_bolunur() -> None:
    """Doğal sınır yoksa bile parça sınırı korunur (bilgi atılmaz)."""
    metin = "a" * 5000

    parcalar = chunk_for_llm(metin, max_chars=1000)

    assert all(len(p) <= 1000 for p in parcalar)
    assert "".join(parcalar) == metin


def test_bolumler_bossa_ham_metne_dusulur() -> None:
    """Bölümler boş gelirse kampanya işlenmeden geçilmemeli."""
    parcalar = chunk_for_llm("uzun " * 3000, {"Başlık": ""}, max_chars=2000)

    assert parcalar
    assert all(len(p) <= 2000 for p in parcalar)


def test_gercekci_uzunlukta_kampanya_tek_parca_kalir() -> None:
    """Tipik kampanya metni (~2.500 karakter) bölünmemeli.

    Gereksiz bölme, aynı kampanya için birden çok model çağrısı demektir ve
    yerel modelde süreyi ikiye katlar.
    """
    metin = "Kampanya koşulu cümlesi. " * 100

    assert len(metin) < MAX_PROMPT_CHARS
    assert len(chunk_for_llm(metin)) == 1
