"""Çıkarım motoru — sağlayıcı soyutlaması, önbellek, promptlar ve çıkarıcılar.

Katman sırası (bkz. SPRINT 3A §0):

    1. Tablo parser   — `product_rates`'ten yapısal veri        güven 1.00
    2. Kural tabanlı  — regex ve normalizasyon                  güven 0.90-1.00
    3. LLM            — YALNIZCA kuralın çözemediği alanlar     güven 0.50-0.90

⚠️ LLM SON ÇAREDİR, İLK DEĞİL. `%2,05` = `% 2.05` = `2.05 %` dönüşümü regex ile
%100 doğrulukla çözülür; bunu modele sormak yavaş, pahalı ve hatalıdır.
"""
