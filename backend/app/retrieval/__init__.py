"""Kanıta dayalı sorgulama katmanı.

Mimari: `docs/SPRINT3C_RAG_MIMARI.md`.

Katmanlar:
    `query`     Türkçe soruyu yapısal süzgeçlere çevirir (kural önce).
    `lexical`   BM25 sözcüksel arama.
    `semantic`  Gömme tabanlı anlamsal arama.
    `fusion`    İki sıralamayı birleştirir, sert süzgeci uygular.
    `aggregate` Toplama sorularını SQL ile yanıtlar.
    `answer`    Getirilen kanıttan Türkçe yanıt üretir ve denetler.

⚠️ BU KATMAN SAYI ÜRETMEZ. Kullanıcıya gösterilen her rakam
`campaign_metrics` / `campaign_extractions` satırından gelir; model yalnızca
cümle kurar. Gerekçe mimari dokümanının 2. bölümünde.
"""

from __future__ import annotations
