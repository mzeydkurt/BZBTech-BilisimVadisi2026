"""Gold set etiketleme şemaları.

⚠️ EN KRİTİK AYRIM BU DOSYADADIR: "metinde YOK" ile "henüz etiketlenmedi"
farklı şeylerdir ve farklı taşınırlar.

    Gövdede alan VAR + value=null  → ∅  "bu bilgi metinde yok" (bilinçli karar)
    Gövdede alan YOK               → "bu alan henüz etiketlenmedi"

Ayrım kaybolursa sistemin halüsinasyonu ölçülemez: metinde oran yokken model
`%2,05` üretirse bu yanlış pozitiftir, ama o alan ∅ işaretlenmemişse
"etiketleyici atlamış" ile ayırt edilemez.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.core.vocab import ANNOTATION_METHODS


class AnnotatedField(BaseModel):
    """Tek bir alanın insan etiketi."""

    # ⚠️ None = "metinde YOK". Boş dize ya da 0 ile karıştırılmaz:
    # 0 "değer sıfır" demektir (ör. "vade farksız" → kâr payı oranı 0).
    value: str | None = Field(default=None, description="Değer; None ise metinde yok")
    evidence: str | None = Field(default=None, description="Kaynaktan birebir kopya")
    unit: str | None = Field(
        default=None, description="pct | TRY | month | count | bool | date | enum"
    )


class AnnotationIn(BaseModel):
    """Bir kampanyanın etiket gönderimi."""

    annotator: str = Field(min_length=1, description="Etiketleyen kişi")
    method: str = Field(description=f"Etiketleme yöntemi: {ANNOTATION_METHODS}")
    is_difficult: bool = Field(default=False, description="Zor vaka mı?")
    note: str | None = Field(default=None, description="Serbest not")
    # ⚠️ Yalnızca ETİKETLENEN alanlar gönderilir. Gönderilmeyen alan için
    # kayıt oluşturulmaz — "etiketlenmedi" durumu böyle temsil edilir.
    fields: dict[str, AnnotatedField] = Field(default_factory=dict)


class AnnotationOut(BaseModel):
    """Kaydedilmiş tek alan etiketi."""

    model_config = ConfigDict(from_attributes=True)

    field_name: str
    gold_value: str | None
    unit: str | None
    evidence_text: str | None
    annotator: str
    method: str
    is_difficult: bool
    note: str | None


class CampaignForAnnotation(BaseModel):
    """Etiketlenecek kampanyanın gösterime hazır hâli."""

    campaign_id: int
    order: int | None = None
    bank_code: str
    bank_name: str
    title: str
    source_url: str
    clean_text: str
    # Örneklemden gelen bağlam.
    method: str
    is_difficult: bool = False
    difficulty_reasons: list[str] = Field(default_factory=list)
    # Daha önce kaydedilmiş etiketler (düzeltme için).
    existing: list[AnnotationOut] = Field(default_factory=list)
    # ⚠️ `assisted` kipte kural tabanlı çıkarımın ön-doldurması. KAPI A4
    # tamamlanana kadar BOŞ gelir; kör etiketleme buna bağımlı değildir.
    prefill: dict[str, AnnotatedField] = Field(default_factory=dict)


class ProgressOut(BaseModel):
    """Etiketleme ilerlemesi."""

    sample_size: int
    # Örneklemde hâlâ DB'de çözülebilen kampanya sayısı (yetim slug'lar hariç).
    reachable_campaigns: int = 0
    # Yeniden kazımada düşmüş / slug'ı kaybolmuş örneklem satırları.
    orphan_campaigns: int = 0
    annotated_campaigns: int
    total_annotations: int
    blind_campaigns: int
    blind_target: int
    assisted_campaigns: int
    difficult_campaigns: int
    # "Metinde yok" diye işaretlenmiş alan sayısı — halüsinasyon ölçümünün
    # paydası. Sıfırsa etiketleme eksik yapılmış demektir.
    explicit_null_fields: int
