"""Halüsinasyon guard'ı — altı katmanlı savunma (Şartname §8).

    1  Grounding            LLM'e her zaman kaynak metin verilir (prompt katmanı)
    2  Kanıt zorunluluğu    `evidence` boşsa alan reddedilir
    3  Alt dize doğrulama   kanıt kaynakta FİİLEN geçiyor mu?          ⭐
    4  Sayısal doğrulama    üretilen rakam varyantlarıyla kaynakta var mı?
    4b Birim uyumu         rakam DOĞRU BÜYÜKLÜĞÜ mü ölçüyor?
    5  Mantık kuralları     alanlar birbiriyle tutarlı mı?
    6  Terminoloji          ürettiğimiz metinde konvansiyonel terim var mı?

⚠️ REDDEDİLEN KAYIT SİLİNMEZ. `rejected_reason` ile saklanır. Halüsinasyon
oranı ancak reddedilenler kayıtlıysa raporlanabilir; silinen bir hata
ölçülemez ve ölçülemeyen bir hata düzeltilemez.

⚠️ KATMAN 3 VE 4 YALNIZCA LLM ÇIKTISINA UYGULANIR. Kural ve tablo katmanı
kanıtını kaynaktan DİLİMLEYEREK üretir (`clean_text[bas:son]`); onları
kaynakta aramak, tanımı gereği doğru olan bir şeyi doğrulamaktır. Katman 5
ise HER kaynağa uygulanır: kuralın bulduğu iki değer de birbiriyle
çelişebilir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from app.ai.extraction.rule_based import ExtractedField
from app.ai.validation.evidence import validate_evidence
from app.ai.validation.logic import check_logic
from app.ai.validation.merger import Conflict, MergeResult, merge_extractions
from app.ai.validation.numbers import validate_number_in_source
from app.ai.validation.terminology import (
    TerminologyWarning,
    check_terminology,
    load_forbidden_terms,
)
from app.core.normalization.text import lower_tr

# Red gerekçeleri — `campaign_extractions.rejected_reason` değerleri.
REASON_NO_EVIDENCE: Final[str] = "evidence_missing"
REASON_EVIDENCE_NOT_FOUND: Final[str] = "evidence_not_found"
REASON_NUMBER_NOT_IN_SOURCE: Final[str] = "number_not_in_source"
REASON_TERM_IS_INSTALLMENT: Final[str] = "taksit_vade_karismasi"

# Guard'ın denetlediği kaynaklar. Tablo ve kural katmanı kanıtını kaynaktan
# dilimleyerek ürettiği için katman 3-4'ten muaftır (bkz. modül açıklaması).
GUARDED_METHODS: Final[frozenset[str]] = frozenset({"llm"})


@dataclass
class GuardResult:
    """Guard sonrası kabul edilen ve reddedilen kayıtlar."""

    accepted: list[ExtractedField] = field(default_factory=list)
    # (kayıt, red gerekçesi)
    rejected: list[tuple[ExtractedField, str]] = field(default_factory=list)
    # Mantık kuralı ihlali olan alanlar: alan adı → açıklama.
    logic_violations: dict[str, str] = field(default_factory=dict)
    # Katman bazında red sayısı — halüsinasyon raporunun kaynağı.
    rejected_by_layer: dict[str, int] = field(default_factory=dict)

    @property
    def hallucination_rate(self) -> float:
        """Üretilen kayıtların ne kadarı reddedildi?"""
        toplam = len(self.accepted) + len(self.rejected)
        return len(self.rejected) / toplam if toplam else 0.0


def _taksit_vade_karismasi(alan_adi: str, kanit: str | None) -> bool:
    """Vade alanının kanıtı taksitten söz edip aydan söz etmiyor mu?

    Katman 4 bu hatayı YAKALAYAMAZ: rakam kaynakta gerçekten geçiyor,
    ama BAŞKA BİR BÜYÜKLÜĞÜ ölçüyor. "Vade farksız 5 taksit" ifadesindeki 5,
    taksit SAYISIDIR; vade DEĞİLDİR (bkz. `patterns.py::INSTALLMENT`).

    Kural katmanı bu ayrımı zaten yapıyor, LLM yapmıyordu. Ölçüldü (canlı
    veritabanı): LLM kaynaklı 229 vade değerinin **221'inin** kanıtı "taksit"
    diyor ve "ay" demiyor.
    """
    if not alan_adi.startswith("term_months"):
        return False
    metin = lower_tr(kanit or "")
    return "taksit" in metin and not re.search(r"\d\s*(?:ay|yıl|yil)\b", metin)


def _reject(sonuc: GuardResult, alan: ExtractedField, gerekce: str) -> None:
    """Kaydı reddedilenlere işler ve katman sayacını artırır."""
    sonuc.rejected.append((alan, gerekce))
    sonuc.rejected_by_layer[gerekce] = sonuc.rejected_by_layer.get(gerekce, 0) + 1


def guard_fields(fields: list[ExtractedField], clean_text: str) -> GuardResult:
    """Çıkarımları altı katmanlı savunmadan geçirir.

    Args:
        fields: Bir kampanyanın tüm çıkarımları.
        clean_text: Kaynak metin.

    Returns:
        Kabul edilenler, reddedilenler ve mantık ihlalleri.
    """
    sonuc = GuardResult()

    for alan in fields:
        if alan.method not in GUARDED_METHODS:
            sonuc.accepted.append(alan)
            continue

        # Katman 2 — kanıt zorunluluğu.
        if not (alan.evidence_text or "").strip():
            _reject(sonuc, alan, REASON_NO_EVIDENCE)
            continue

        # Katman 3 — kanıt kaynakta geçiyor mu?
        gecerli, _, _ = validate_evidence(alan.evidence_text, clean_text)
        if not gecerli:
            _reject(sonuc, alan, REASON_EVIDENCE_NOT_FOUND)
            continue

        # Katman 4 — üretilen rakam kaynakta geçiyor mu?
        if not validate_number_in_source(alan.value_normalized, alan.unit, clean_text):
            _reject(sonuc, alan, REASON_NUMBER_NOT_IN_SOURCE)
            continue

        # Katman 4b — birim uyumu: taksit sayısı vade alanına yazılamaz.
        if _taksit_vade_karismasi(alan.field_name, alan.evidence_text):
            _reject(sonuc, alan, REASON_TERM_IS_INSTALLMENT)
            continue

        sonuc.accepted.append(alan)

    # Katman 5 — mantık kuralları KABUL EDİLENLER üzerinde, her kaynağa.
    # ⚠️ Alan başına tek değer gerekir; çakışma varsa en öncelikli alınır.
    from app.ai.validation.merger import METHOD_PRIORITY

    en_iyi: dict[str, ExtractedField] = {}
    for alan in sonuc.accepted:
        mevcut = en_iyi.get(alan.field_name)
        if mevcut is None or METHOD_PRIORITY.get(alan.method, 0) > METHOD_PRIORITY.get(
            mevcut.method, 0
        ):
            en_iyi[alan.field_name] = alan

    sonuc.logic_violations = check_logic({ad: alan.value_normalized for ad, alan in en_iyi.items()})

    return sonuc


__all__ = [
    "GUARDED_METHODS",
    "REASON_EVIDENCE_NOT_FOUND",
    "REASON_NO_EVIDENCE",
    "REASON_NUMBER_NOT_IN_SOURCE",
    "REASON_TERM_IS_INSTALLMENT",
    "Conflict",
    "GuardResult",
    "MergeResult",
    "TerminologyWarning",
    "check_logic",
    "check_terminology",
    "guard_fields",
    "load_forbidden_terms",
    "merge_extractions",
    "validate_evidence",
    "validate_number_in_source",
]
