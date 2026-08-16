"""LLM yanıt önbelleği — yerel modelde bile zorunlu.

Yerel model ücretsizdir ama YAVAŞTIR: 500 kampanya × birkaç saniye, her
yeniden çalıştırmada saatler demektir. Önbellek olmadan prompt üzerinde
yineleme yapmak pratikte imkânsız hâle gelir.

⚠️ ANAHTAR DÖRT PARÇADAN OLUŞUR: metin özeti + görev + prompt sürümü + model
adı. Model ya da prompt değişince önbellek KENDİLİĞİNDEN geçersizleşir —
bu istenen davranıştır. Anahtar yalnızca metinden türetilseydi, prompt
iyileştirmesinden sonra eski yanıtlar geri gelir ve değişikliğin etkisi
ölçülemezdi.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.vocab import LLM_TASKS
from app.db.base import Base, UtcDateTime, in_check, utc_now


class LLMCache(Base):
    """Tek bir LLM çağrısının önbelleğe alınmış yanıtı."""

    __tablename__ = "llm_cache"
    __table_args__ = (
        UniqueConstraint("cache_key", name="uq_llm_cache_cache_key"),
        CheckConstraint(in_check("task", LLM_TASKS), name="task_valid"),
        Index("ix_llm_cache_model_name_prompt_version", "model_name", "prompt_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # sha256(metin_özeti | görev | prompt_sürümü | model_adı)
    cache_key: Mapped[str] = mapped_column(Text, nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)

    # Ham yanıt metni (JSON dizesi olarak). Ayrıştırma sonradan düzeltilebilsin
    # diye modelin döndürdüğü hâliyle saklanır.
    response_json: Mapped[str] = mapped_column(Text, nullable=False)

    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utc_now)
