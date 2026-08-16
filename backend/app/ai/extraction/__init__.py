"""Çıkarım katmanları.

Katman 1  `table_source`  yapısal oran tabloları      güven 1.00
Katman 2  `rule_based`    regex + normalizasyon       güven 0.90
Katman 3  `llm_extractor` yalnızca çözülemeyen alanlar güven 0.70
"""

from app.ai.extraction.llm_extractor import LLMExtractionResult, extract_llm
from app.ai.extraction.rule_based import ExtractedField, extract_rule_based, solved_fields

__all__ = [
    "ExtractedField",
    "LLMExtractionResult",
    "extract_llm",
    "extract_rule_based",
    "solved_fields",
]
