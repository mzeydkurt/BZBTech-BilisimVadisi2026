"""Çıkarılacak alanlar ve JSON şeması.

Bu liste iki yerin ORTAK sözleşmesidir: gold set etiketleme arayüzü (KAPI A3)
ve çıkarım motoru (KAPI A4-A6) aynı alanları kullanır. Ayrışırlarsa
değerlendirme, sistemin hiç üretmediği bir alanı "kaçırılmış" sayar ya da
ürettiği bir alanı hiç ölçmez.

⚠️ HER ALAN İÇİN BİRİM ZORUNLUDUR. `2.05` tek başına oran mı tutar mı belli
değildir; `campaign_extractions.unit` bu belirsizliği kapatır ve
değerlendirmede karşılaştırma toleransını belirler (oran ±0.01, tutar tam
eşleşme).
"""

from __future__ import annotations

from typing import Any, Final

from app.core.taxonomy import AUDIENCES, PRODUCT_TYPES, SECTORS

# Ödülün türü. Kaynak: kural tabanlı çıkarıcının eşleme tablosu —
# "nakit iade" → nakit_iade, "puan/lira/parafpara" → puan, "çek/hediye" → hediye.
REWARD_TYPES: Final[tuple[str, ...]] = (
    "nakit_iade",
    "puan",
    "indirim",
    "taksit",
    "hediye",
    "ucret_muafiyeti",
)

# Alan adı → birim. Birimler `campaign_extractions.unit` ile aynı sözlükten.
EXTRACTABLE_FIELDS: Final[dict[str, str]] = {
    # ── Kâr payı ve maliyet ───────────────────────────────
    # ⚠️ Katılım terminolojisi: "faiz" değil "kâr payı".
    "profit_rate_pct": "pct",
    # Katılma hesabında bankanın müşteriye dağıttığı pay — finansmandaki
    # kâr payıyla KARIŞTIRILMAMALI, yönü terstir.
    "profit_share_rate_pct": "pct",
    "allocation_fee_pct": "pct",
    "file_fee_try": "TRY",
    "has_no_fee": "bool",
    # ⚠️ Şartname Örnek Temsili Senaryo-1'in B Bankası satırı: "Ekspertiz
    # ücretsiz". Konut finansmanında ayırt edici maliyet kalemi; `has_no_fee`
    # ile karıştırılmaz — o kampanyanın GENEL masrafsızlığını söyler, bu
    # yalnızca değerleme ücretini.
    "appraisal_fee_covered": "bool",
    # ── Vade ve taksit ────────────────────────────────────
    # ⚠️ "4 aya varan TAKSİT" taksit sayısıdır, vade değil. İkisi ayrı alan.
    "term_months_min": "month",
    "term_months_max": "month",
    "installment_count": "count",
    # ── Tutar ─────────────────────────────────────────────
    "financing_amount_min": "TRY",
    "financing_amount_max": "TRY",
    "min_spend_try": "TRY",
    "max_spend_try": "TRY",
    # ── Ödül ──────────────────────────────────────────────
    "reward_amount_try": "TRY",
    "reward_type": "enum",
    # ⚠️ KAMPANYANIN TAVANI, TEK ÖDÜLÜ DEĞİL. "3 ay boyunca her ay 500 TL,
    # toplamda 1.500 TL" metninde `reward_amount_try`=500 ve
    # `max_total_benefit_try`=1500; ikisi AYRI soruyu yanıtlıyor ve
    # karşılaştırma motoru ikincisini `azami toplam fayda` olarak sunuyor
    # (`app/retrieval/aggregate.py`).
    "max_total_benefit_try": "TRY",
    "cashback_pct": "pct",
    "discount_pct": "pct",
    "loyalty_points": "count",
    # ── Tarih ─────────────────────────────────────────────
    # ⚠️ Bulunamazsa null. Türkiye Finans'ın TÜM kampanyaları böyle olacak;
    # tarih yokluğu "süresi dolmuş" DEĞİLDİR.
    "start_date": "date",
    "end_date": "date",
    # ── Sınıflandırma ─────────────────────────────────────
    "target_customer": "enum",
    "product_type": "enum",
    "sector": "enum",
    # ── Kademeli ödül ─────────────────────────────────────
    # ⚠️ TEK ALANA SIĞMAYAN YAPI. "5.000 TL ve üzeri 250 TL, 10.000 TL ve
    # üzeri 500 TL" iki eşik iki ödül demek; `min_spend_try` +
    # `reward_amount_try` çiftine sıkıştırılırsa alt kademe kaybolur ve
    # kullanıcı yanlış eşiği görür. JSON olarak saklanır.
    #
    # ⚠️ BİRİMİ `json` ve bu BİLİNÇLİ: sayı doğrulaması (KAPI A7 katman 4)
    # tek bir sayı bekler, JSON gövdesini sayıya çeviremez. `NUMERIC_UNITS`
    # dışında kaldığı için o katmandan muaf; kanıt zorunluluğu (katman 2-3)
    # yine geçerli.
    "tier_structure": "json",
}

# ⚠️ LLM'E HİÇ SORULMAYAN ALANLAR. Bu dosyanın kardeşi
# `extraction/llm_extractor.py` şu kuralı yazıyor: *"Aynı alanı bir de modele
# sormak, kesin bir sonucu olasılıklı bir sonuçla değiştirme riski taşır."*
# Üç alan için bu risk kesin:
#
#   `tier_structure`         JSON gövdesi + KARAKTER ARALIĞI istiyor. Guard
#                            `clean_text[start:end] == evidence_text`
#                            değişmezini uyguluyor; model bir JSON listesi
#                            için bu ofseti üretemez, ürettiğini iddia ederse
#                            guard reddeder. Kural katmanı `TIER` kalıbıyla
#                            eşiği ve ödülü ham metinden dilimliyor.
#   `max_total_benefit_try`  "toplamda 5 kişi için maksimum 25.000 TL" ile
#                            "toplamda 2.000 TL" ayrımı SÖZDİZİMSEL; modele
#                            sormak 12,5 kat hatalı değer riski demek.
#   `appraisal_fee_covered`  Olumsuzluk çekimi kararı ("yansıtılmayacaktır"
#                            olumsuz, "yansıtılmaktadır" OLUMLU). Kalıp bu
#                            ayrımı sayarak yapıyor; model karıştırdığında
#                            hata sessiz olur.
#
# ⚠️ YAN FAYDA: PROMPT DEĞİŞMEZ. Şema bu üç alanı içermediği için istem metni
# eskisiyle birebir aynı kalıyor ve `llm_cache` GEÇERLİ kalıyor. Alanları
# şemaya eklemek 482 kampanyanın tamamını yeniden modele sormak demekti.
RULE_ONLY_FIELDS: Final[frozenset[str]] = frozenset(
    {"tier_structure", "max_total_benefit_try", "appraisal_fee_covered"}
)


# 6000 karakterden uzun metinler bölünür (bkz. `app/ai/chunking.py`).
# Küçük yerel modellerin bağlam penceresi 4096 token; Türkçe metinde
# ~2.5 karakter/token oranıyla bu sınır güvenli tarafta kalır.
MAX_PROMPT_CHARS: Final[int] = 6000


# ⚠️ ENUM ALANLAR KONTROLLÜ SÖZLÜKTEN SEÇİLİR, serbest yazılmaz.
# Etiketleyici `eticaret_pazaryeri` yerine `e-ticaret` yazarsa değerlendirme
# bunu "sistem yanlış buldu" sayar; hata sistemde değil gold set'tedir ve
# fark edilmesi neredeyse imkânsızdır.
ENUM_VOCAB: Final[dict[str, tuple[str, ...]]] = {
    "reward_type": REWARD_TYPES,
    "target_customer": AUDIENCES,
    "product_type": PRODUCT_TYPES,
    "sector": SECTORS,
}


def options_for(field: str) -> tuple[str, ...]:
    """Alanın izin verilen değerlerini döndürür.

    Args:
        field: Alan adı.

    Returns:
        Kontrollü sözlük; alan enum değilse boş demet.
    """
    return ENUM_VOCAB.get(field, ())


def build_extraction_schema(fields: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    """İstenen alanlar için JSON şeması üretir.

    ⚠️ ALT KÜME DESTEKLENİR. KAPI A6'da kuralın çözdüğü alanlar prompt'tan
    çıkarılır (`already_found`); şema da daralmalıdır, aksi hâlde model zaten
    bilinen alanları yeniden üretmeye çalışır ve çıktı token'ı boşa gider.

    Args:
        fields: İstenen alan adları; verilmezse tüm alanlar.

    Returns:
        JSON Schema nesnesi.

    Raises:
        ValueError: Tanımsız alan adı verildiyse. Sessizce yok sayılırsa,
            yazım hatası olan bir alan hiç çıkarılmadığı hâlde "çıkarılamadı"
            gibi görünür.
    """
    secilen = tuple(fields) if fields is not None else tuple(EXTRACTABLE_FIELDS)

    bilinmeyen = [alan for alan in secilen if alan not in EXTRACTABLE_FIELDS]
    if bilinmeyen:
        raise ValueError(f"Tanımsız çıkarım alanı: {bilinmeyen}")

    return {
        "type": "object",
        "properties": {
            alan: {
                "type": "object",
                "properties": {
                    # Değer tipi alana göre değişir; şema hepsini kabul eder,
                    # tip doğrulaması normalizasyon katmanında yapılır.
                    "value": {"type": ["number", "string", "boolean", "array", "null"]},
                    # ⚠️ Kanıt null OLABİLİR ama alan da o zaman null olmalıdır:
                    # bu tutarlılık halüsinasyon guard'ında (KAPI A7) denetlenir.
                    "evidence": {"type": ["string", "null"]},
                },
                "required": ["value", "evidence"],
            }
            for alan in secilen
        },
        "required": list(secilen),
    }


EXTRACTION_SCHEMA: Final[dict[str, Any]] = build_extraction_schema()


def unit_of(field: str) -> str:
    """Alanın birimini döndürür.

    Args:
        field: Alan adı.

    Returns:
        `pct` | `TRY` | `month` | `count` | `bool` | `date` | `enum`.

    Raises:
        KeyError: Alan tanımlı değilse.
    """
    return EXTRACTABLE_FIELDS[field]
