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

from datetime import datetime
from decimal import Decimal
from typing import Any

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
    session_id: str | None = Field(
        default=None,
        description="Sohbet oturum anahtarı (UUID). Yoksa yeni oturum açılır.",
    )
    model_id: str | None = Field(
        default=None,
        description=(
            "`GET /chat/models` listesinden `provider:model` anahtarı. "
            "⚠️ Seçim YALNIZCA bu isteği etkiler; `.env` yazılmaz. Tanınmayan "
            "değer sessizce yok sayılır ve yapılandırılmış sağlayıcı kullanılır."
        ),
    )


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


class ChatProductItem(BaseModel):
    """Tekil ürün / oran kanıtı (results[] bozulmadan eklenir)."""

    product_id: int
    product_name: str
    bank_code: str
    bank_name: str
    product_type: str | None = None
    rate_type: str | None = None
    rate_id: int | None = None
    card_text: str
    profit_rate_pct: Decimal | None = None
    investor_share_pct: Decimal | None = None
    term_months: int | None = None
    source_url: str | None = None


class ChatGlossaryItem(BaseModel):
    """Tanım niyeti sonucu."""

    term_id: int
    term: str
    definition: str
    conventional_equivalent: str | None = None


class ChatComparisonBlock(BaseModel):
    """Ürün karşılaştırması — rank_products çıktısının taşıyıcısı."""

    rate_type: str
    criterion: str
    winner_product_id: int | None = None
    winner_bank_code: str | None = None
    winner_reason: str | None = None
    ranked: list[ChatProductItem] = Field(default_factory=list)
    without_data: list[ChatProductItem] = Field(default_factory=list)
    note: str | None = None


class ChatTopMatch(BaseModel):
    """Sohbet yanıtındaki en iyi eşleşmelerden biri (en fazla 3)."""

    entity_type: str = Field(description="campaign | product | product_rate | glossary")
    id: int
    title: str
    bank_name: str | None = None
    score: Decimal = Field(description="0-100 arası göreli puan")
    source_url: str | None = None
    reason: str | None = Field(default=None, description="Neden seçildiği (kısa)")
    detail_path: str | None = Field(
        default=None,
        description="Arayüz içi yol: /campaigns, /products/{id}, /katilim-hesabi",
    )


class ChatResponse(BaseModel):
    """Kanıtlı arama yanıtı.

    ⚠️ SÖZLEŞME DONDURULDU — yalnızca ekleme. Alan adı/tipi değiştirmek yasak.
    """

    query: str
    intent: str = Field(
        description=("search | aggregate | compare | tanim | tekil_sorgu | kapsam_disi | sohbet")
    )
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
    # ── Sprint 5 eklemeleri (geriye dönük uyumlu) ─────────
    clarification_needed: bool = False
    clarification_question: str | None = None
    direction_note: str | None = None
    products: list[ChatProductItem] = Field(default_factory=list)
    glossary: list[ChatGlossaryItem] = Field(default_factory=list)
    comparison: ChatComparisonBlock | None = None
    # ── Katibim eklemeleri ────────────────────────────────
    source_domain: str | None = Field(
        default=None,
        description="kampanya | finansman | katilma | tanim | kapsam_disi | sohbet",
    )
    top_matches: list[ChatTopMatch] = Field(default_factory=list)
    # ── Oturum (eklemeli) ─────────────────────────────────
    session_id: str | None = Field(default=None, description="Sohbet oturum anahtarı (UUID)")
    turn_index: int | None = Field(default=None, description="Bu turdaki sıra numarası (0 tabanlı)")


class ChatSessionCreateResponse(BaseModel):
    """Yeni sohbet oturumu."""

    session_id: str
    title: str | None = None
    created_at: str | None = None


class ChatSessionMessageOut(BaseModel):
    """Oturum geçmişindeki tek mesaj."""

    turn_index: int
    role: str
    content: str
    response_json: dict[str, Any] | ChatResponse | None = None
    intent: str | None = None
    source_domain: str | None = None
    answer_source: str | None = None
    created_at: str | None = None


class ChatSessionDetail(BaseModel):
    """Oturum + mesaj geçmişi."""

    session_id: str | None = None
    session_key: str | None = None
    title: str | None = None
    ended_at: str | None = None
    created_at: str | None = None
    last_activity_at: str | None = None
    messages: list[ChatSessionMessageOut] = Field(default_factory=list)


class ChatSessionSummary(BaseModel):
    """Sohbet geçmişi listesindeki tek satır.

    ⚠️ MESAJ İÇERİĞİ TAŞIMAZ. Liste yüzlerce oturum döndürebilir; her birinin
    tüm mesajlarını taşımak yanıtı megabaytlara çıkarır. Tıklanan oturum
    `GET /chat/sessions/{key}` ile ayrıca çekilir.
    """

    session_key: str
    title: str | None = Field(default=None, description="İlk kullanıcı sorusundan türetilen başlık")
    created_at: datetime
    last_activity_at: datetime
    ended_at: datetime | None = None
    turn_count: int = Field(default=0, description="Kullanıcı–asistan turu sayısı")
    first_query: str | None = Field(
        default=None, description="Oturumun ilk kullanıcı sorusu (önizleme)"
    )


class ChatSessionList(BaseModel):
    """Sohbet geçmişi listesi."""

    items: list[ChatSessionSummary] = Field(default_factory=list)
    total: int = 0


class ChatModelOption(BaseModel):
    """Sohbette seçilebilecek bir model."""

    id: str = Field(description="`provider:model` biçiminde kararlı anahtar")
    provider: str = Field(description="evren | local | mock")
    model: str
    label: str
    is_local: bool = Field(description="Kapalı ağda çalışır mı?")
    is_active: bool = Field(description="Şu an yapılandırılmış olan bu mu?")
    available: bool = Field(description="Sağlık yoklaması geçti mi?")
    note: str | None = None


class ChatModelsResponse(BaseModel):
    """Seçilebilir modeller ve etkin olan.

    ⚠️ `available=false` OLAN MODEL LİSTEDEN GİZLENMEZ. Kullanıcı neden
    seçemediğini görmeli; gizlemek "böyle bir seçenek yok" izlenimi verir.
    """

    active_id: str
    items: list[ChatModelOption] = Field(default_factory=list)
