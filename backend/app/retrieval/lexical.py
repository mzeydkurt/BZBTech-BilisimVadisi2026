"""BM25 sözcüksel arama — saf Python.

SQLite FTS5 KULLANILMIYOR. FTS5 sanal tabloları SQLite'a özgüdür ve
`CLAUDE.md`'nin "PostgreSQL'e geçişte yalnızca `DATABASE_URL` değişir, kodda
değişiklik gerekmez" kuralını bozar. Arama gövdesi 1.253 kart (~600 KB);
bu boyutta saf Python BM25 milisaniyenin altında çalışıyor ve taşınabilir.

GÖMME SÖZCÜKSEL ARAMANIN YERİNİ ALMAZ. Marka adı ("A101", "Pazarama"),
tutar ("250 TL") ve banka adı gibi BİREBİR eşleşmelerde gömme zayıftır:
vektör uzayında "A101" ile "Migros" birbirine çok yakın durur ve kullanıcı
A101 sorduğunda Migros kampanyası dönebilir. İki kanal birbirinin yedeği
değil, tamamlayıcısıdır.

TÜRKÇE EK BUDAMA YAPILMAZ, ÖN EK EŞLEŞMESİ YAPILIR. Gerçek bir
biçimbirim çözümleyicisi (morphological analyzer) bağımlılık ister ve
şartnamenin lisans havuzunu genişletir. Yerine: sorgu terimi, belge
teriminin ÖN EKİ ise eşleşme sayılır ("market" → "markette", "marketlerde").
Bu, `categorizer._kelime_var` ile aynı ilkedir — sol sınır zorunlu, sağ
sınır serbest.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Final

from app.core.normalization.text import ascii_fold_tr, lower_tr, normalize_text

# Standart BM25 parametreleri.
K1: Final[float] = 1.5
B: Final[float] = 0.75

# Ön ek eşleşmesinin geçerli sayılması için gereken en az terim uzunluğu.
# ⚠️ Kısa terimlerde ön ek eşleşmesi gürültü üretir: "ay" terimi "aylık",
# "ayakkabı", "ayrıca" hepsine uyar.
MIN_PREFIX_LENGTH: Final[int] = 4

# Ön ek eşleşmesine uygulanan ceza. Birebir eşleşme her zaman önde olmalı;
# aksi hâlde "market" sorgusu "marketing" içeren bir kartı gerçek market
# kampanyasının önüne çıkarabilir.
PREFIX_PENALTY: Final[float] = 0.6

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")


def tokenize(text: str | None) -> list[str]:
    """Metni karşılaştırılabilir simgelere böler.

    Türkçe karakterler ASCII'ye katlanır ("kâr payı" → "kar payi"); kullanıcı
    şapkalı â yazmıyor, banka sayfası yazıyor.
    """
    return _TOKEN_RE.findall(ascii_fold_tr(lower_tr(normalize_text(text or ""))))


@dataclass(frozen=True)
class LexicalHit:
    """Tek bir belgenin sözcüksel arama sonucu."""

    doc_id: int
    score: float
    # Sorgunun hangi terimleri bu belgede bulundu — arayüzde neden döndüğünü
    # açıklamak için gerekli.
    matched_terms: tuple[str, ...]


class Bm25Index:
    """Bellek içi BM25 dizini.

    ⚠️ DİZİN HER ARAMADA YENİDEN KURULMAZ. Kart sayısı sabit; dizin bir kez
    kurulup önbellekte tutulur (`app/retrieval/corpus.py`). Her istekte
    yeniden kurmak 1.253 kartı yeniden simgelemek demektir.
    """

    def __init__(self, documents: dict[int, str]) -> None:
        """Dizini kurar.

        Args:
            documents: Belge kimliği → aranacak metin.
        """
        self._freqs: dict[int, Counter[str]] = {}
        self._lengths: dict[int, int] = {}
        # Terim → o terimi içeren belge kimlikleri. Ön ek eşleşmesi bu
        # sözlüğün anahtarları üzerinde tarama yapar.
        self._postings: dict[str, set[int]] = {}

        for doc_id, text in documents.items():
            simgeler = tokenize(text)
            sayim = Counter(simgeler)
            self._freqs[doc_id] = sayim
            self._lengths[doc_id] = len(simgeler)
            for terim in sayim:
                self._postings.setdefault(terim, set()).add(doc_id)

        self._doc_count = len(documents)
        self._avg_length = sum(self._lengths.values()) / self._doc_count if self._doc_count else 0.0

    @property
    def doc_count(self) -> int:
        """Dizindeki belge sayısı."""
        return self._doc_count

    def _idf(self, doc_freq: int) -> float:
        """Ters belge sıklığı (BM25'in olasılıksal biçimi).

        ⚠️ `+1` GEREKLİ. Bir terim belgelerin yarısından fazlasında geçtiğinde
        klasik biçim NEGATİF idf üretiyor; "kampanya" gibi her kartta bulunan
        bir terim o zaman puanı DÜŞÜRÜYOR ve sıralamayı tersine çeviriyor.
        """
        return math.log(1 + (self._doc_count - doc_freq + 0.5) / (doc_freq + 0.5))

    def _eslesen_terimler(self, terim: str) -> list[tuple[str, float]]:
        """Sorgu terimine karşılık gelen dizin terimlerini ağırlıklarıyla verir."""
        if terim in self._postings:
            return [(terim, 1.0)]
        if len(terim) < MIN_PREFIX_LENGTH:
            return []
        return [
            (dizin_terimi, PREFIX_PENALTY)
            for dizin_terimi in self._postings
            if dizin_terimi.startswith(terim)
        ]

    def search(self, terms: list[str], *, limit: int = 50) -> list[LexicalHit]:
        """Terim listesine göre belgeleri puanlar.

        ⚠️ VE DEĞİL VEYA. Terimler kesişimle bağlanırsa "Kuveyt Türk'te market
        kampanyası" sorgusu üç terimi birden içeren kayıt bulamayıp SIFIR sonuç
        döndürüyor — bugünkü `chat_service`'in tam olarak bu davranışı vardı.
        Terimlerin tamamını içeren belgeler puanla öne çıkar; hiçbiri elenmez.

        Args:
            terms: Aranacak simgeler (`tokenize` çıktısı ya da serbest terimler).
            limit: Döndürülecek en fazla sonuç.

        Returns:
            Puanı sıfırdan büyük belgeler, azalan puana göre.
        """
        if not terms or not self._doc_count:
            return []

        puanlar: dict[int, float] = {}
        eslesen: dict[int, set[str]] = {}

        for sorgu_terimi in terms:
            for dizin_terimi, agirlik in self._eslesen_terimler(sorgu_terimi):
                belgeler = self._postings.get(dizin_terimi, set())
                if not belgeler:
                    continue
                idf = self._idf(len(belgeler))
                for doc_id in belgeler:
                    tf = self._freqs[doc_id][dizin_terimi]
                    uzunluk = self._lengths[doc_id]
                    norm = K1 * (1 - B + B * (uzunluk / self._avg_length or 1.0))
                    puanlar[doc_id] = puanlar.get(doc_id, 0.0) + agirlik * idf * (
                        tf * (K1 + 1) / (tf + norm)
                    )
                    eslesen.setdefault(doc_id, set()).add(dizin_terimi)

        sirali = sorted(puanlar.items(), key=lambda ikili: (-ikili[1], ikili[0]))
        return [
            LexicalHit(
                doc_id=doc_id,
                score=puan,
                matched_terms=tuple(sorted(eslesen.get(doc_id, set()))),
            )
            for doc_id, puan in sirali[:limit]
            if puan > 0
        ]
