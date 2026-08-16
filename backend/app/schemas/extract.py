"""Canlı çıkarım ucunun şemaları (`POST /api/v1/extract`).

⚠️ HER ALAN KANITIYLA BİRLİKTE DÖNER. Kanıtsız bir değer, kullanıcının
"bu nereden çıktı?" sorusunu yanıtlayamaz; açıklanabilirlik iddiası da o
noktada biter. `method` alanı hangi katmanın ürettiğini söyler.

⚠️ REDDEDİLENLER DE DÖNER (`rejected`). Guard'ın neyi elediğini gizlemek,
sistemi olduğundan temiz gösterirdi.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ⚠️ Metin sınırı. Sınırsız girdi hem yerel modeli kilitler hem de
# bağlam penceresini aşan bir istem SESSİZCE kırpılır.
MAX_TEXT_CHARS: int = 20_000


class ExtractRequest(BaseModel):
    """Çıkarım isteği."""

    text: str = Field(
        min_length=1,
        max_length=MAX_TEXT_CHARS,
        description=f"Kampanya metni (en fazla {MAX_TEXT_CHARS} karakter)",
    )
    # ⚠️ Varsayılan `hybrid`: uçtan uca davranışı gösteren kip budur.
    mode: str = Field(default="hybrid", description="rule_only | hybrid | llm_only")


class ExtractedFieldOut(BaseModel):
    """Tek bir alanın çıkarım sonucu."""

    model_config = ConfigDict(from_attributes=True)

    value: str
    unit: str
    confidence: float
    method: str = Field(description="table | rule | llm")
    evidence: str | None = None
    # ⚠️ Kanıt kaynaktan dilimlenemediyse None: LLM'in ürettiği kanıt
    # metinde birebir bulunamamış olabilir.
    evidence_span: tuple[int, int] | None = None
    validation_note: str | None = None


class RejectedFieldOut(BaseModel):
    """Guard'ın elediği çıkarım."""

    field_name: str
    value: str
    method: str
    reason: str
    evidence: str | None = None


class ModelInfoOut(BaseModel):
    """Yanıtı üreten modelin kimliği."""

    name: str
    license: str
    local: bool


class ExtractResponse(BaseModel):
    """Çıkarım yanıtı."""

    fields: dict[str, ExtractedFieldOut]
    labels: dict[str, list[str]] = Field(default_factory=dict)
    summary: str | None = None
    rejected: list[RejectedFieldOut] = Field(default_factory=list)
    logic_violations: dict[str, str] = Field(default_factory=dict)
    model: ModelInfoOut
    latency_ms: int
    # Uygulanan kip; istekte verilenden farklı olamaz ama yanıtta
    # görünmesi hata ayıklamayı kolaylaştırır.
    mode: str
    extras: dict[str, Any] = Field(default_factory=dict)
