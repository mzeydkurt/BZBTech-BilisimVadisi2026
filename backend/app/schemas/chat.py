"""Kanıtlı arama uç noktasının Pydantic şemaları.

YANIT YALNIZCA SONUÇ LİSTESİ DEĞİL. Sistemin soruyu nasıl anladığı
(`understood`), kaç kaydın hangi süzgece takıldığı (`retrieval`), yanıtın
modelden mi şablondan mı geldiği (`answer.source`) ve hangi sayıların
doğrulanamadığı (`answer.unverified_numbers`) da döner. Bunlar arayüz süsü
değil: kaynağı gösterilemeyen bir finansal iddia gösterilemez.

ORAN VE TUTAR ALANLARI `Decimal`. `float` kullanılmaz; Pydantic
JSON çıktısında dize üretir ve arayüz `Number()` ile okur — kayan nokta
yuvarlaması API sınırını geçmez.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Kanıtlı arama isteği."""

    query: str = Field(
        min_length=2,
        max_length=500,
        description="Doğal dil sorusu (Örn: 'En düşük kâr payı oranı hangi bankada?')",
    )
    bank_code: str | None = Field(
        default=None,
        description=(
            "Arayüzden gelen ek banka süzgeci. Sorgu metninde de banka geçiyorsa "
            "ikisi birleştirilmez; bu alan sorgu metnini EZER."
        ),
    )
    limit: int = Field(default=8, ge=1, le=25, description="Döndürülecek en fazla kanıt")


class UnderstoodFilter(BaseModel):
    """Sorgudan çıkarılan tek bir süzgeç ve onu üreten kanıt.

    Arayüzde kaldırılabilir çip olarak gösterilir: kullanıcı sistemin soruyu
    nasıl anladığını görmezse yanlış anlaşılmayı fark edemez ve düzeltemez.
    """

    kind: str = Field(
        description="bank | product_type | sector | audience | benefit | status | numeric"
    )
    value: str
    label: str = Field(description="Arayüzde gösterilecek Türkçe eksen adı")
    display: str = Field(description="Değerin Türkçe karşılığı")
    evidence: str = Field(description="Sorgunun bu süzgeci üreten parçası")


class UnverifiedNumberOut(BaseModel):
    """Yanıtta geçen ama kaynakta bulunamayan sayı."""

    value: str
    cited: list[int] = Field(default_factory=list)


class TerminologyWarningOut(BaseModel):
    """Üretilen yanıtta bulunan konvansiyonel terim."""

    term: str
    suggestion: str | None = None


class AnswerBlock(BaseModel):
    """Üretilen yanıt ve denetim sonuçları."""

    text: str
    source: str = Field(description="model | template | refusal | computed")
    citations: list[int] = Field(
        default_factory=list, description="Yanıtta atıf verilen kampanya kimlikleri"
    )
    unverified_numbers: list[UnverifiedNumberOut] = Field(default_factory=list)
    terminology_warnings: list[TerminologyWarningOut] = Field(default_factory=list)
    is_grounded: bool = Field(
        default=True, description="Yanıttaki her sayı kaynakta doğrulandı mı?"
    )
    model_name: str | None = None
    model_error: str | None = Field(
        default=None,
        description="Model çağrısı başarısız olduysa nedeni; yanıt şablona düşmüştür",
    )
    latency_ms: int | None = None


class ChatMetric(BaseModel):
    """Bir kampanyanın sorguyla ilgili sayısal alanı."""

    field: str
    label: str
    value: Decimal
    unit: str


class ChatResultItem(BaseModel):
    """Getirilen tek bir kampanya kanıtı."""

    campaign_id: int
    bank_code: str
    bank_name: str
    title: str
    status: str = Field(description="Backend'de hesaplanır; arayüz yeniden hesaplamaz")
    source_url: str
    summary: str | None = None
    card_text: str = Field(description="Aranan ve modele verilen kanıt metni")
    metrics: list[ChatMetric] = Field(default_factory=list)
    # Bu kaydın neden döndüğü.
    channels: list[str] = Field(
        default_factory=list, description="lexical | semantic; boşsa yalnızca süzgeçten geldi"
    )
    matched_terms: list[str] = Field(default_factory=list)


class FilterRejection(BaseModel):
    """Bir süzgecin elediği kayıt sayısı."""

    filter: str
    label: str
    count: int


class RelaxationHintOut(BaseModel):
    """Bir süzgeç kaldırılsa kaç sonuç çıkardı?"""

    kind: str
    value: str
    label: str
    hit_count: int


class RetrievalReport(BaseModel):
    """Erişimin şeffaflık şeridi.

    ⚠️ "8 sonuç bulundu" ile "2 kayıt kâr payı eşiğine takıldı, 8 sonuç kaldı"
    kullanıcı için aynı şey değildir.
    """

    corpus_size: int
    returned: int
    lexical_used: bool
    semantic_used: bool
    semantic_note: str | None = None
    rejected: list[FilterRejection] = Field(default_factory=list)
    total_rejected: int = 0
    elapsed_ms: int = 0


class AggregateBlock(BaseModel):
    """Toplama sorusunun hesaplanmış sonucu.

    ⚠️ `without_value` GİZLENMEZ. "En düşük oran %0" cümlesi, 148 kayıt
    üzerinden mi 608 kayıt üzerinden mi söylendiği bilinmeden değersizdir.
    """

    kind: str = Field(description="extremum | count")
    field: str | None = None
    field_label: str | None = None
    value: Decimal | None = None
    unit: str | None = None
    winner_campaign_id: int | None = None
    with_value: int = 0
    without_value: int = 0
    total: int = 0
    tie_count: int = 0
    by_bank: dict[str, int] | None = None


class ChatResponse(BaseModel):
    """Kanıtlı arama yanıtı."""

    query: str
    intent: str = Field(description="search | aggregate | compare")
    understood: list[UnderstoodFilter] = Field(default_factory=list)
    answer: AnswerBlock
    aggregate: AggregateBlock | None = None
    results: list[ChatResultItem] = Field(default_factory=list)
    retrieval: RetrievalReport
    relaxation_hints: list[RelaxationHintOut] = Field(default_factory=list)
    forbidden_terms_warning: str | None = Field(
        default=None,
        description=(
            "Kullanıcının SORUSUNDA konvansiyonel terim geçtiyse uyarı "
            "(örn. 'faiz' yerine 'kâr payı'). Sorgu yine de çalıştırılır."
        ),
    )
