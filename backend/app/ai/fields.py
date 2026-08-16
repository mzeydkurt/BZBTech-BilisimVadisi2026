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
}

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
