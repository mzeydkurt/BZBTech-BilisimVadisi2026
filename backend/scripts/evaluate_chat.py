"""Sohbet uçtan uca değerlendirme — çıkarım F1 ile karıştırılmaz.

Gold: `tests/fixtures/chat_gold/chat_gold.jsonl`
Çıktı: `docs/sprint5_evaluation.md`

    python -m scripts.evaluate_chat
    python -m scripts.evaluate_chat --limit 10
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from app.ai.providers import active_embedding_model
from app.config import get_settings
from app.db.session import SessionLocal
from app.logging_config import configure_logging
from app.schemas.chat import ChatRequest
from app.services.chat_service import process_chat_query

BACKEND = Path(__file__).resolve().parents[1]
GOLD = BACKEND / "tests" / "fixtures" / "chat_gold" / "chat_gold.jsonl"
DOCS = BACKEND.parent / "docs" / "sprint5_evaluation.md"


def _load_gold(limit: int | None) -> list[dict]:
    satirlar: list[dict] = []
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        satirlar.append(json.loads(line))
        if limit and len(satirlar) >= limit:
            break
    return satirlar


async def _olc(limit: int | None) -> dict:
    gold = _load_gold(limit)
    settings = get_settings()
    dogru_niyet = 0
    dogru_susma = 0
    susma_hedef = 0
    halusinasyon = 0
    netlestirme_isabet = 0
    netlestirme_hedef = 0
    gecikmeler: list[int] = []
    niyet_dagilim: Counter[str] = Counter()
    semantic_kullanan = 0

    with SessionLocal() as session:
        for kayit in gold:
            bas = time.perf_counter()
            yanit = await process_chat_query(session, ChatRequest(query=kayit["query"]))
            gecikmeler.append(int((time.perf_counter() - bas) * 1000))
            niyet_dagilim[yanit.intent] += 1
            if yanit.retrieval.semantic_used:
                semantic_kullanan += 1

            if yanit.intent == kayit["expected_intent"]:
                dogru_niyet += 1

            if kayit.get("expect_silence"):
                susma_hedef += 1
                if yanit.answer.source in {"refusal", "computed"} and not yanit.results:
                    # computed + clarification da susma sayılır
                    if yanit.clarification_needed or yanit.answer.source == "refusal":
                        dogru_susma += 1
                    elif kayit["expected_intent"] == "tanim" and yanit.glossary:
                        dogru_susma += 1  # tanim susma değil ama ayrı
                elif yanit.clarification_needed:
                    dogru_susma += 1

            if kayit.get("expect_clarification"):
                netlestirme_hedef += 1
                if yanit.clarification_needed:
                    netlestirme_isabet += 1

            if yanit.answer.unverified_numbers:
                halusinasyon += 1

    n = max(len(gold), 1)
    return {
        "n": len(gold),
        "provider": settings.llm_provider,
        # ⚠️ `settings.embedding_model` DEĞİL. O alan yerel Ollama modelini
        # tutuyor; EVREN kullanılırken vektörler `bge-m3-embed`'den geliyor ve
        # rapor yanlış modeli beyan ediyordu. Vektörü gerçekten üreten modelin
        # adı tek kaynaktan okunur (bkz. `active_embedding_model` gerekçesi).
        "embedding_model": active_embedding_model(settings),
        "semantic_used_count": semantic_kullanan,
        "semantic_used_rate": semantic_kullanan / n,
        "intent_acc": dogru_niyet / n,
        "hallucination_rate": halusinasyon / n,
        "silence_rate": (dogru_susma / susma_hedef) if susma_hedef else None,
        "silence_n": susma_hedef,
        "clarification_acc": (
            (netlestirme_isabet / netlestirme_hedef) if netlestirme_hedef else None
        ),
        "clarification_n": netlestirme_hedef,
        "avg_latency_ms": sum(gecikmeler) / len(gecikmeler) if gecikmeler else 0,
        "intent_dist": dict(niyet_dagilim),
    }


def _rapor(ozet: dict) -> str:
    satirlar = [
        "# Sprint 5 — Sohbet Değerlendirme",
        "",
        "> Bu rapor **sohbet uçtan uca** metriğidir. "
        "`docs/evaluation.md` içindeki alan çıkarımı F1 (0.785) ile **karıştırılmamalıdır**.",
        "",
        f"- Sağlayıcı: `{ozet['provider']}`",
        f"- Gömme modeli ayarı: `{ozet['embedding_model']}`",
        f"- Anlamsal kanal (`semantic_used=true`): "
        f"**{ozet['semantic_used_count']}/{ozet['n']}** "
        f"({ozet['semantic_used_rate']:.3f})",
        "- Lexical kanal: BM25 her zaman açık",
        f"- Gold soru sayısı: **{ozet['n']}**",
        f"- Doğru niyet oranı: **{ozet['intent_acc']:.3f}**",
        f"- Halüsinasyon oranı (unverified_numbers dolu): **{ozet['hallucination_rate']:.3f}**",
        f"- Ortalama gecikme: **{ozet['avg_latency_ms']:.0f} ms**",
    ]
    if ozet["silence_rate"] is not None:
        satirlar.append(
            f"- Doğru susma oranı ({ozet['silence_n']} vaka): **{ozet['silence_rate']:.3f}**"
        )
    if ozet["clarification_acc"] is not None:
        satirlar.append(
            f"- Netleştirme isabeti ({ozet['clarification_n']} vaka): "
            f"**{ozet['clarification_acc']:.3f}**"
        )
    satirlar.extend(
        [
            "",
            "## Niyet dağılımı (sistem çıktısı)",
            "",
            "| Niyet | Adet |",
            "|---|---|",
        ]
    )
    for k, v in sorted(ozet["intent_dist"].items()):
        satirlar.append(f"| {k} | {v} |")
    satirlar.extend(
        [
            "",
            "## Notlar",
            "",
            "- MockProvider ile ölçülen sayı **boru hattının** doğruluğudur, modelin değil.",
            "- Anlamsal kanal boşsa `semantic_used=false`; lexical yeterlidir.",
            "- Tutturulamayan hedefler gizlenmez; gold etiketleri kör yazılmıştır.",
            "",
        ]
    )
    return "\n".join(satirlar)


def main(argv: list[str] | None = None) -> int:
    import asyncio

    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    if not GOLD.is_file():
        print(f"Gold set yok: {GOLD}")
        return 1
    ozet = asyncio.run(_olc(args.limit))
    metin = _rapor(ozet)
    DOCS.parent.mkdir(parents=True, exist_ok=True)
    DOCS.write_text(metin, encoding="utf-8")
    print(metin)
    print(f"\nYazıldı: {DOCS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
