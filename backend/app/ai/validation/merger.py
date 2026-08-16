"""Merger — aynı alan için birden çok kaynağın uzlaştırılması.

ÖNCELİK: `table` (1.00) > `rule` (0.90) > `llm` (0.70)

⚠️ KAYBEDEN KAYIT SİLİNMEZ. Her kaynak kendi satırında kalır; merger
yalnızca hangisinin KAZANDIĞINI işaretler. Silinirse "kural ve model aynı
fikirde miydi?" sorusu sonradan yanıtlanamaz ve ablasyon tablosu (KAPI A9)
kurulamaz.

⚠️ ÇAKIŞMA SESSİZ GEÇİLMEZ. Kural %2,05 derken model %2,50 diyorsa
ikisinden biri yanılıyordur. Kazanan yüksek önceliklidir ama güveni
düşürülür ve çakışma `docs/conflicts.md`ye yazılır: prompt ince ayarında
(SPRINT 3B) bakılacak ilk yer burasıdır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from app.ai.extraction.rule_based import ExtractedField

# Yöntem → öncelik. Büyük olan kazanır.
METHOD_PRIORITY: Final[dict[str, int]] = {"table": 3, "rule": 2, "llm": 1}

# Çakışmada kazananın güveninden düşülen miktar.
CONFLICT_PENALTY: Final[Decimal] = Decimal("0.15")

# Güven bu değerin altına indirilmez.
MIN_CONFIDENCE: Final[Decimal] = Decimal("0.10")


@dataclass
class Conflict:
    """Aynı alanda farklı kaynakların farklı değer üretmesi."""

    campaign_id: int | None
    field_name: str
    winner_method: str
    winner_value: str
    loser_method: str
    loser_value: str

    def as_row(self) -> str:
        """Markdown tablo satırı."""
        return (
            f"| {self.campaign_id} | `{self.field_name}` | "
            f"{self.winner_method} = `{self.winner_value}` | "
            f"{self.loser_method} = `{self.loser_value}` |"
        )


@dataclass
class MergeResult:
    """Merger çıktısı."""

    fields: list[ExtractedField] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)


def _priority(alan: ExtractedField) -> int:
    """Kaydın öncelik puanı; bilinmeyen yöntem en düşük sayılır."""
    return METHOD_PRIORITY.get(alan.method, 0)


def merge_extractions(
    fields: list[ExtractedField], *, campaign_id: int | None = None
) -> MergeResult:
    """Alan başına kazananı seçer ve çakışmaları raporlar.

    ⚠️ KAZANAN KAYIT DÖNDÜRÜLÜR, kaybedenler döndürülmez — ama çağıran
    hepsini veritabanına yazmaya devam eder. Bu fonksiyon `campaign_metrics`
    için tek değer üretmekle görevlidir.

    Args:
        fields: Aynı kampanyanın tüm çıkarımları (guard'ı geçmiş olanlar).
        campaign_id: Çakışma raporu için kampanya kimliği.

    Returns:
        Alan başına kazanan kayıtlar ve çakışma listesi.
    """
    gruplar: dict[str, list[ExtractedField]] = {}
    for alan in fields:
        gruplar.setdefault(alan.field_name, []).append(alan)

    kazananlar: list[ExtractedField] = []
    catismalar: list[Conflict] = []

    for alan_adi, adaylar in gruplar.items():
        # En yüksek öncelik, eşitlikte en yüksek güven.
        sirali = sorted(adaylar, key=lambda a: (_priority(a), a.confidence), reverse=True)
        kazanan = sirali[0]

        # ⚠️ Yalnızca DEĞERİ FARKLI olan aday çakışmadır. Aynı değeri iki
        # kaynağın birden bulması bir uyumdur, sorun değil.
        farklilar = [
            aday for aday in sirali[1:] if aday.value_normalized != kazanan.value_normalized
        ]

        if farklilar:
            kaybeden = farklilar[0]
            catismalar.append(
                Conflict(
                    campaign_id=campaign_id,
                    field_name=alan_adi,
                    winner_method=kazanan.method,
                    winner_value=kazanan.value_normalized,
                    loser_method=kaybeden.method,
                    loser_value=kaybeden.value_normalized,
                )
            )
            not_metni = (
                f"çakışma: {kazanan.method}={kazanan.value_normalized}, "
                f"{kaybeden.method}={kaybeden.value_normalized}"
            )
            kazanan = ExtractedField(
                **{
                    **kazanan.__dict__,
                    "confidence": max(MIN_CONFIDENCE, kazanan.confidence - CONFLICT_PENALTY),
                    "validation_note": not_metni,
                }
            )

        kazananlar.append(kazanan)

    return MergeResult(fields=kazananlar, conflicts=catismalar)
