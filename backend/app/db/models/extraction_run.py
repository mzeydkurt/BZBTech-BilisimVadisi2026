"""Çıkarım çalıştırması — hangi kipte, ne kadar veri, ne kadar red.

Kazımadaki `scrape_runs` ile aynı amacı taşır: her çalıştırma ölçülebilir
olmalıdır. Buradaki sayaçlar SPRINT 3'ün ablasyon tablosunu besler —
`rule_only` ile `hybrid` çalıştırmalarının maliyeti ve kapsamı ancak bu
kayıtlar üzerinden karşılaştırılabilir.

⚠️ `fields_rejected` AYRI TUTULUR. Halüsinasyon guard'ının reddettiği çıkarım
sayısı, sistemin "bilgi yokken bilgi üretmeme" yeteneğinin doğrudan ölçüsüdür;
`fields_extracted` içine karıştırılırsa bu yetenek raporlanamaz.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.vocab import EXTRACTION_MODES, EXTRACTION_RUN_STATUSES
from app.db.base import Base, UtcDateTime, in_check, utc_now


class ExtractionRun(Base):
    """Tek bir çıkarım çalıştırmasının özeti ve sayaçları."""

    __tablename__ = "extraction_runs"
    __table_args__ = (
        CheckConstraint(in_check("mode", EXTRACTION_MODES), name="mode_valid"),
        CheckConstraint(in_check("status", EXTRACTION_RUN_STATUSES), name="status_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    mode: Mapped[str] = mapped_column(Text, nullable=False)
    # Neyin üzerinde çalıştığı: banka kodu, kampanya kimliği aralığı ya da NULL
    # (tümü). Ablasyon karşılaştırmasında aynı kapsam kullanılmalıdır.
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")

    campaigns_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fields_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Guard tarafından reddedilen alan sayısı — halüsinasyon oranının payı.
    fields_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # LLM maliyeti: kaç çağrı yapıldı, kaçı önbellekten karşılandı.
    llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ⚠️ Model ve prompt sürümü kayda yazılır: prompt değişince eski sonuçların
    # hangi sürümle üretildiği bilinmezse ablasyon karşılaştırması anlamsızdır.
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)

    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
