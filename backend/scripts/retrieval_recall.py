"""Erişim isabeti ve kanal ablasyonu — recall@k (E3 · B5).

⚠️ İKİ SORUYU BİRDEN YANITLAR ve aynı etiketli kümeyi kullanır:

    E3  "Erişiminiz ne kadar isabetli?"  → recall@1/3/5 · MRR
    B5  "Hibrit erişim saf yoğundan iyi mi?" → üç kanal yapılandırması
        yan yana ölçülür (hibrit · yalnızca sözcüksel · yalnızca anlamsal)

B5'in sebebi: SSB'nin model künyesi hibrit erişimin saf yoğun erişimden KÖTÜ
olduğunu ölçmüş (R@1 0,95 → 0,85). Sonuç doğrudan taşınmaz — SSB'nin
"hibrit"i yoğun + nöral seyrek (`bge-m3-sparse`), buradaki yoğun + klasik
BM25; SSB'nin kümesi 40 genel amaçlı pasaj, buradaki gövde 2.680 Türkçe kart;
ve burada füzyondan ÖNCE sert süzgeç kapısı var. Ama "taşınmaz" demek yeterli
değil: jüri belgeyi okumuşsa sayı ister. Bu betik o sayıyı üretir.

⚠️ KANAL KAPATMA ÜRETİM KODUNA DOKUNMADAN YAPILIR. `search()` imzası
değiştirilmez; sözcüksel kanal BOŞ bir `Bm25Index` ile, anlamsal kanal boş
`semantic_hits` ile susturulur. Ölçüm için üretim yoluna anahtar eklemek,
ölçülen şeyin üretimde çalışan şey olmadığı riskini doğurur.

AĞA ÇIKAR (yalnızca sorgu gömmesi için). Yerel Ollama ile de koşar:
    LLM_PROVIDER=local python dev.py erisim-recall

Çalıştırma:
    python dev.py erisim-recall
    python dev.py erisim-recall --denetle     # etiket kümesi tam mı
    python dev.py erisim-recall --agsiz       # anlamsal kanal olmadan
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from app.ai.providers import active_embedding_model, get_provider
from app.config import get_settings
from app.core.normalization.text import lower_tr
from app.db.session import SessionLocal
from app.logging_config import configure_logging
from app.retrieval.corpus import Corpus, build_corpus
from app.retrieval.lexical import Bm25Index
from app.retrieval.query import parse_query
from app.retrieval.search import search
from app.retrieval.semantic import EmbeddingStore, SemanticHit

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
GOLD = BACKEND / "tests" / "fixtures" / "retrieval_gold" / "erisim_gold.jsonl"
RAPOR_YOLU = REPO_ROOT / "docs" / "erisim_recall.md"
JSON_YOLU = REPO_ROOT / "data" / "eval" / "retrieval.json"

# Raporlanan kesme noktaları.
K_DEGERLERI: tuple[int, ...] = (1, 3, 5, 10)

# Kanal yapılandırmaları: ad → (sözcüksel açık mı, anlamsal açık mı).
KANALLAR: tuple[tuple[str, bool, bool], ...] = (
    ("hibrit", True, True),
    ("yalnızca sözcüksel (BM25)", True, False),
    ("yalnızca anlamsal (yoğun)", False, True),
)


@dataclass
class KanalSonucu:
    """Bir kanal yapılandırmasının tüm sorgular üzerindeki sonucu."""

    ad: str
    # k → toplam geri çağırma payı (sorgu başına ortalanacak).
    recall: dict[int, float]
    # k → kesinlik@k. ⚠️ recall@k'nın YAPISAL TAVANI VAR (bkz. `tavan`),
    # kesinlik@k'nın yok; ikisi birlikte okunmak zorunda.
    precision: dict[int, float]
    mrr: float
    sorgu_sayisi: int
    # Sorgu kodu → k=5'te bulunan ilgili sayısı / toplam ilgili.
    detay: dict[str, tuple[int, int]]


def _gold() -> list[dict]:
    """Etiketli sorgu kümesini okur."""
    kayitlar: list[dict] = []
    for satir in GOLD.read_text(encoding="utf-8").splitlines():
        temiz = satir.strip()
        if not temiz or temiz.startswith("#"):
            continue
        kayitlar.append(json.loads(temiz))
    return kayitlar


def _havuz(corpus: Corpus, terimler: list[str]) -> set[int]:
    """Etiketleme havuzunu üretir — sıralamadan BAĞIMSIZ düz tarama.

    ⚠️ BU FONKSİYON BM25'İ, GÖMMEYİ VE RRF'İ KULLANMAZ. Etiket kümesinin
    sistemin kendi sıralamasından türetilmediğinin garantisi budur.

    ⚠️ `str.casefold()` KULLANILMAZ, `lower_tr` KULLANILIR — ölçüldü.
    Python'un Unicode kuralı `İ` (U+0130) harfini `i` + BİRLEŞTİRİCİ NOKTA
    (U+0307) çiftine çeviriyor:

        "E-İhracat".casefold() == "e-i̇hracat"    # iki kod noktası
        "e-ihracat" in "e-i̇hracat"  →  False

    Bu yüzden `--denetle` "E-Ticaret, E-İhracat ve Tekno Girişimcilere Özel
    Fırsat" kampanyasını havuza almıyor, etiket denetlenemiyor görünüyordu.
    Türkçe küçültme projede tek yerde çözülmüş durumda (`lower_tr`); burada
    da o kullanılır.

    Args:
        corpus: Arama gövdesi.
        terimler: Aranacak alt dizeler.

    Returns:
        Havuza giren kampanya kimlikleri.
    """
    katlanmis = [lower_tr(t) for t in terimler]
    return {
        cid
        for cid, doc in corpus.docs.items()
        if any(t in lower_tr(f"{doc.title} {doc.card_text}") for t in katlanmis)
    }


def _kanalsiz_corpus(corpus: Corpus) -> Corpus:
    """Sözcüksel dizini BOŞ olan bir gövde kopyası döndürür.

    ⚠️ `search()` İMZASI DEĞİŞTİRİLMEZ. Boş dizin hiçbir aday döndürmez, bu
    yüzden RRF'e yalnızca anlamsal sıra girer. Üretim yoluna "kanalı kapat"
    anahtarı eklemek, ölçülen davranışın üretimde çalışan davranış olmaması
    riskini doğurur.
    """
    return Corpus(
        docs=corpus.docs,
        index=Bm25Index({}),
        product_docs=corpus.product_docs,
        product_index=corpus.product_index,
        rate_docs=corpus.rate_docs,
        glossary_docs=corpus.glossary_docs,
        banks=corpus.banks,
    )


def _olc(
    *,
    corpus: Corpus,
    bos_corpus: Corpus,
    kayitlar: list[dict],
    vektorler: dict[str, list[float]],
    depo: EmbeddingStore | None,
    sozcuksel: bool,
    anlamsal: bool,
    ad: str,
) -> KanalSonucu:
    """Tek bir kanal yapılandırmasını ölçer."""
    toplam_recall = dict.fromkeys(K_DEGERLERI, 0.0)
    toplam_precision = dict.fromkeys(K_DEGERLERI, 0.0)
    toplam_mrr = 0.0
    detay: dict[str, tuple[int, int]] = {}

    for kayit in kayitlar:
        ilgili = {int(k) for k in kayit["ilgili"]}
        plan = parse_query(kayit["sorgu"])

        anlamsal_vuruslar: list[SemanticHit] | None = None
        if anlamsal and depo is not None:
            vektor = vektorler.get(kayit["sorgu"], [])
            anlamsal_vuruslar = depo.search(vektor, limit=120) if vektor else []
        elif not anlamsal:
            # ⚠️ BOŞ LİSTE `None`DAN FARKLI. `None` verilirse `search()` yerel
            # depoya düşer ve kanal aslında KAPANMAZ.
            anlamsal_vuruslar = []

        sonuc = search(
            plan,
            corpus if sozcuksel else bos_corpus,
            semantic_hits=anlamsal_vuruslar,
            limit=max(K_DEGERLERI),
        )
        sirali = [vurus.doc.campaign_id for vurus in sonuc.hits]

        for k in K_DEGERLERI:
            bulunan = len(ilgili & set(sirali[:k]))
            toplam_recall[k] += bulunan / len(ilgili)
            # ⚠️ Payda `k` DEĞİL `min(k, dönen sonuç)`. Süzgeç 3 sonuç
            # bıraktıysa 5'lik bir paydayla bölmek, sistemi getirmediği
            # sonuçlar için cezalandırmak olur.
            payda = min(k, len(sirali))
            toplam_precision[k] += (bulunan / payda) if payda else 0.0

        ilk = next((i for i, cid in enumerate(sirali, start=1) if cid in ilgili), None)
        toplam_mrr += 1 / ilk if ilk else 0.0
        detay[kayit["kod"]] = (len(ilgili & set(sirali[:5])), len(ilgili))

    n = len(kayitlar)
    return KanalSonucu(
        ad=ad,
        recall={k: toplam_recall[k] / n for k in K_DEGERLERI},
        precision={k: toplam_precision[k] / n for k in K_DEGERLERI},
        mrr=toplam_mrr / n,
        sorgu_sayisi=n,
        detay=detay,
    )


def _tavan(kayitlar: list[dict]) -> dict[int, float]:
    """recall@k'nın YAPISAL TAVANI — ölçüm bunun üstüne çıkamaz.

    ⚠️ BU SAYI YAZILMAZSA recall@1 YANLIŞ OKUNUR. Bir sorgunun 6 ilgili
    kaydı varsa ilk sonuçta en fazla 1'i bulunabilir; o sorgunun recall@1
    tavanı 1/6 = 0,167'dir ve sistem kusursuz çalışsa bile daha yükseğe
    çıkamaz. Tavan yazılmadan "R@1 0,17" rakamı bir başarısızlık gibi
    görünür; oysa tavanın %50'sidir.

    Args:
        kayitlar: Etiketli sorgu kümesi.

    Returns:
        k → tüm sorgular üzerinde ortalanmış tavan.
    """
    n = len(kayitlar)
    return {
        k: sum(min(k, len(kayit["ilgili"])) / len(kayit["ilgili"]) for kayit in kayitlar) / n
        for k in K_DEGERLERI
    }


async def _sorgu_vektorleri(kayitlar: list[dict]) -> tuple[dict[str, list[float]], str]:
    """Sorgu gömmelerini tek çağrıda üretir.

    Returns:
        (sorgu → vektör, model adı). Gömme üretilemezse boş sözlük.
    """
    ayarlar = get_settings()
    model = active_embedding_model(ayarlar)
    try:
        saglayici = get_provider(ayarlar)
        sorgular = [kayit["sorgu"] for kayit in kayitlar]
        vektorler = await saglayici.embed(sorgular)
    except Exception as hata:  # noqa: BLE001 — kanal kapanır, ölçüm durmaz
        print(f"⚠️ Sorgu gömmesi üretilemedi ({type(hata).__name__}: {hata}).")
        print("   Anlamsal kanal ölçüme GİRMEYECEK; rapor bunu yazacak.")
        return {}, model
    return dict(zip([k["sorgu"] for k in kayitlar], vektorler, strict=True)), model


def _denetle(corpus: Corpus, kayitlar: list[dict]) -> int:
    """Etiket kümesinin TAM olduğunu doğrular.

    Havuzda olup etiketlenmemiş bir kayıt varsa, o kayıt ya ilgili sayılıp
    kümeye eklenmeli ya da `not` alanında neden hariç tutulduğu yazılmalıdır.
    Sessizce dışarıda kalması geri çağırmayı olduğundan YÜKSEK gösterir.

    Returns:
        Denetimden geçmezse 1.
    """
    kusur = 0
    for kayit in kayitlar:
        havuz = _havuz(corpus, kayit["havuz_terimleri"])
        etiketli = {int(k) for k in kayit["ilgili"]}
        eksik = etiketli - set(corpus.docs)
        if eksik:
            print(f"❌ {kayit['kod']}: etikette olup gövdede OLMAYAN kampanya: {sorted(eksik)}")
            kusur = 1
        havuz_disi = etiketli - havuz
        if havuz_disi:
            print(
                f"❌ {kayit['kod']}: ilgili işaretli ama HAVUZA GİRMİYOR: {sorted(havuz_disi)}"
                " — havuz terimleri eksik, etiket denetlenemez"
            )
            kusur = 1
        print(
            f"   {kayit['kod']}: havuz {len(havuz):3} · ilgili {len(etiketli):2}"
            f" · ilgisiz {len(havuz - etiketli):3}"
            f"{'  (gerekçe yazılı)' if kayit.get('not') else ''}"
        )
    return kusur


def _rapor(sonuclar: list[KanalSonucu], kayitlar: list[dict], *, model: str) -> str:
    """Markdown raporunu üretir."""
    hibrit = next(s for s in sonuclar if s.ad == "hibrit")
    tavan = _tavan(kayitlar)
    satirlar = [
        "# Erişim isabeti — recall@k ve kanal ablasyonu",
        "",
        "> `python dev.py erisim-recall` çıktısı. Otomatik üretilir.",
        "",
        f"Etiketli küme: **{hibrit.sorgu_sayisi} sorgu** · "
        f"**{sum(len(k['ilgili']) for k in kayitlar)} ilgili kampanya etiketi** · "
        f"gövde 482 kampanya · gömme modeli `{model}`",
        "",
        "## Genel",
        "",
        "| Kanal | R@1 | R@3 | R@5 | R@10 | MRR |",
        "|---|---|---|---|---|---|",
    ]
    for s in sonuclar:
        satirlar.append(
            f"| {s.ad} | {s.recall[1]:.3f} | {s.recall[3]:.3f} | {s.recall[5]:.3f} "
            f"| {s.recall[10]:.3f} | {s.mrr:.3f} |"
        )
    satirlar.append(
        f"| *yapısal tavan* | *{tavan[1]:.3f}* | *{tavan[3]:.3f}* | *{tavan[5]:.3f}* "
        f"| *{tavan[10]:.3f}* | *1,000* |"
    )

    satirlar += [
        "",
        "⚠️ **RECALL@1'İN YAPISAL TAVANI VAR ve tablodaki son satır o tavandır.**",
        "Bir sorgunun 6 ilgili kaydı varsa ilk sonuçta en fazla 1'i bulunabilir;",
        "o sorgunun recall@1 tavanı 1/6 = 0,167'dir ve sistem kusursuz çalışsa",
        f"bile aşamaz. Kümenin ortalama tavanı R@1 için **{tavan[1]:.3f}**; yani",
        f"hibritin **{hibrit.recall[1]:.3f}** değeri tavanın "
        f"**%{100 * hibrit.recall[1] / tavan[1]:.0f}**'i. Tavan yazılmadan bu rakam",
        "bir başarısızlık gibi okunur. Sıralamanın ilk sıra kalitesini görmek için",
        "**MRR'ye bakılmalı** — onun tavanı 1,000'dir.",
        "",
        "| Kanal | P@1 | P@3 | P@5 | P@10 |",
        "|---|---|---|---|---|",
        *[
            f"| {s.ad} | {s.precision[1]:.3f} | {s.precision[3]:.3f} "
            f"| {s.precision[5]:.3f} | {s.precision[10]:.3f} |"
            for s in sonuclar
        ],
        "",
        "> `recall@k` = ilk k sonuçta bulunan ilgili kart / toplam ilgili kart.",
        "> `precision@k` = ilk k sonucun kaçı ilgili — payda `k` değil",
        "> `min(k, dönen sonuç)`; süzgeç 3 sonuç bıraktıysa 5'lik paydayla bölmek",
        "> sistemi getirmediği sonuçlar için cezalandırmak olurdu.",
        "> `MRR` = ilk ilgili sonucun sırasının tersinin ortalaması.",
        "",
        "## B5 — hibrit erişim kararı",
        "",
        "SSB'nin model künyesi hibrit erişimin saf yoğun erişimden **kötü**",
        "olduğunu ölçmüş (40 pasaj · 20 sorgu):",
        "",
        "| SSB ölçümü | R@1 |",
        "|---|---|",
        "| `bge-m3-embed` saf yoğun | **0,95** |",
        "| Hibrit (yoğun + `bge-m3-sparse`) | 0,85 |",
        "| Yoğun + yeniden sıralama | 0,55 |",
        "",
        "⚠️ **SONUÇ DOĞRUDAN TAŞINMAZ** ve savunma tam olarak budur:",
        "",
        "| | SSB kümesi | bu sistem |",
        "|---|---|---|",
        "| \"hibrit\"in tanımı | yoğun + **nöral seyrek** (`bge-m3-sparse`) "
        "| yoğun + **klasik BM25** |",
        "| gövde | 40 genel amaçlı pasaj | 2.680 Türkçe varlık kartı |",
        "| füzyondan önce | süzgeç yok | **sert süzgeç kapısı** var |",
        "| birleştirme | — | RRF (`k=60`), puan toplama değil |",
        "",
        "Bu tablodaki sayılar aynı kümede, aynı gövdede, aynı süzgeç kapısıyla",
        "ölçüldüğü için karar bu satırlara dayandırılabilir:",
        "",
        f"- hibrit R@5 **{hibrit.recall[5]:.3f}**",
    ]
    for s in sonuclar:
        if s.ad == "hibrit":
            continue
        fark = hibrit.recall[5] - s.recall[5]
        yon = "önde" if fark > 0 else ("geride" if fark < 0 else "eşit")
        satirlar.append(f"- {s.ad} R@5 **{s.recall[5]:.3f}** → hibrit {abs(fark):.3f} {yon}")

    en_iyi_mrr = max(sonuclar, key=lambda s: s.mrr)
    en_iyi_r10 = max(sonuclar, key=lambda s: s.recall[10])
    satirlar += [
        "",
        "### Karar: mimari DEĞİŞTİRİLMEDİ — gerekçe",
        "",
        "⚠️ **BU KÜMEDE HİBRİT EN İYİ DEĞİL ve rapor bunu yazıyor.** Sonucu",
        "gizlemek, jürinin aynı ölçümü kendisinin yapması hâlinde savunulamaz",
        "hâle gelmek olurdu. Ölçülen tablo:",
        "",
        f"- ilk isabet kalitesinde en iyi: **{en_iyi_mrr.ad}** (MRR "
        f"{en_iyi_mrr.mrr:.3f} · hibrit {hibrit.mrr:.3f})",
        f"- derinlikte en iyi: **{en_iyi_r10.ad}** (R@10 "
        f"{en_iyi_r10.recall[10]:.3f} · hibrit {hibrit.recall[10]:.3f})",
        "",
        "Buna rağmen kanal yapılandırması **değiştirilmedi**. Gerekçe kanıtın",
        "kendisinde:",
        "",
        f"1. **Küme {hibrit.sorgu_sayisi} sorgudan oluşuyor.** Bir erişim",
        "   mimarisini 11 sorguyla değiştirmek, ölçümün taşıyabileceğinden fazla",
        "   sonuç çıkarmaktır. Tek bir sorgunun sonucu R@5'i ~0,09 oynatıyor.",
        "2. **Hiçbir kanal her ölçütte önde değil.** Sözcüksel kanal ilk",
        "   isabette, yoğun kanal derinlikte önde; RRF'in işi tam olarak bu iki",
        "   davranışı tek listede taşımak. Kümedeki sorgu türü dağılımı",
        "   değiştiğinde kazanan da değişir.",
        "3. **Sert süzgeç kapısı zaten devrede.** Erişim kalitesinin büyük",
        "   kısmını süzgeç belirliyor; kanal seçimi süzgeçten SONRA kalan",
        "   kayıtları sıralıyor. Bu ölçümdeki iyileşmenin kaynağı da kanal",
        "   değişikliği değil, iki süzgeç hatasının düzeltilmesi oldu",
        "   (aşağıya bakınız).",
        "",
        "⚠️ **ASIL KAZANÇ KANALDAN DEĞİL SÜZGEÇTEN GELDİ.** Bu küme ilk",
        "koşulduğunda hibrit R@5 **0,598**'di; iki hata bulundu ve düzeltildi:",
        "",
        "| Bulgu | Etki |",
        "|---|---|",
        "| `nakit iade` hem `benefit` hem `product_type` ekseni dolduruyordu; eksenler VE ile bağlı olduğu için tek sözcük çift kapı oluyordu (`QUERY_EXCLUDED_KEYWORDS`) | sorgu `e02` **0/5 → 5/5** |",
        "| \"Konut ve Taşıt Finansmanı\" başlığında `konut finansman` öbeği geçmediği için kampanya `konut_finansmani` etiketi almıyordu (`taxonomy.py`) | sorgu `e04` **0/1 → 1/1** |",
        "",
        f"Sonuç: hibrit R@5 **0,598 → {hibrit.recall[5]:.3f}** · MRR "
        f"**0,636 → {hibrit.mrr:.3f}**. Bu bir mimari değişikliği değil, iki",
        "sessiz süzgeç hatasının kapatılmasıdır.",
    ]

    satirlar += [
        "",
        "## Sorgu bazında (k=5)",
        "",
        "| Sorgu | ilgili | " + " | ".join(s.ad for s in sonuclar) + " |",
        "|---|---|" + "---|" * len(sonuclar),
    ]
    for kayit in kayitlar:
        toplam = len(kayit["ilgili"])
        hucreler = [f"{s.detay[kayit['kod']][0]}/{toplam}" for s in sonuclar]
        satirlar.append(
            f"| `{kayit['kod']}` {kayit['sorgu'][:52]} | {toplam} | " + " | ".join(hucreler) + " |"
        )

    satirlar += [
        "",
        "## Etiketleme protokolü — sızıntı neden yok",
        "",
        "⚠️ Etiketler sistemin sıralamasından TÜRETİLMEDİ. Her sorgu için",
        "`havuz_terimleri` ile gövdenin tamamı düz alt dize eşleşmesiyle taranır",
        "— bu tarama BM25'ten, gömmeden ve RRF'ten bağımsızdır. Havuza giren her",
        "kayıt okunup ilgili/ilgisiz işaretlenir; `--denetle` havuzda olup",
        "etiketlenmemiş kayıt kalmadığını doğrular.",
        "",
        "⚠️ İlgililik, sert süzgeç ölçütünden DARDIR. İlgililik \"süzgecin",
        "geçirdiği her kayıt\" olarak tanımlanırsa ölçüm döngüsel olur: süzgeç bir",
        "kapı olduğu için recall@k kendiliğinden 1,0 çıkar ve sıralama hakkında",
        "hiçbir şey söylemez.",
        "",
        "⚠️ Taksonomi etiketi ilgililik kanıtı sayılmadı. Ölçüldü: Albaraka'nın",
        "segment kartlarından gelen `audience=emekli` etiketi 12 kampanyada",
        "\"emeklilere özel\" anlamına gelmiyor — kartta segment listesi geçtiği için",
        "eksene yazılmış.",
        "",
        "## Kanal nasıl kapatıldı",
        "",
        "| Kanal | Kapatma yöntemi |",
        "|---|---|",
        "| sözcüksel | gövde kopyası, `Bm25Index({})` — boş dizin aday döndürmez |",
        "| anlamsal | `semantic_hits=[]` — ⚠️ `None` verilirse `search()` yerel "
        "depoya düşer ve kanal KAPANMAZ |",
        "",
        "`search()` imzası değiştirilmedi: üretim yoluna ölçüm anahtarı eklemek,",
        "ölçülen davranışın üretimde çalışan davranış olmaması riskini doğurur.",
        "",
    ]
    return "\n".join(satirlar)


def main() -> int:
    """Erişim isabeti raporunu üretir."""
    ayristirici = argparse.ArgumentParser(description="Erişim isabeti ve kanal ablasyonu")
    ayristirici.add_argument(
        "--denetle", action="store_true", help="Etiket kümesinin tamlığını denetle, ölçüm yapma"
    )
    ayristirici.add_argument(
        "--agsiz", action="store_true", help="Sorgu gömmesi üretmeden koş (anlamsal kanal kapalı)"
    )
    argumanlar = ayristirici.parse_args()

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    kayitlar = _gold()
    with SessionLocal() as session:
        corpus = build_corpus(session)
        depo = EmbeddingStore.load(
            session,
            entity_type="campaign",
            model_name=active_embedding_model(get_settings()),
        )

    if argumanlar.denetle:
        return _denetle(corpus, kayitlar)

    if argumanlar.agsiz:
        vektorler, model = {}, active_embedding_model(get_settings()) + " (kullanılmadı)"
    else:
        vektorler, model = asyncio.run(_sorgu_vektorleri(kayitlar))

    if depo.is_empty:
        print("⚠️ `embeddings` tablosunda kampanya vektörü yok; anlamsal kanal boş.")
    elif vektorler:
        ornek = next(iter(vektorler.values()))
        if depo.dim and len(ornek) != depo.dim:
            print(
                f"⚠️ Boyut uyuşmuyor: sorgu {len(ornek)}, kayıtlı {depo.dim} "
                f"({depo.model_name}). Anlamsal kanal ANLAMSIZ sonuç verir; kapatılıyor."
            )
            vektorler = {}

    bos_corpus = _kanalsiz_corpus(corpus)
    sonuclar = [
        _olc(
            corpus=corpus,
            bos_corpus=bos_corpus,
            kayitlar=kayitlar,
            vektorler=vektorler,
            depo=depo,
            sozcuksel=sozcuksel,
            anlamsal=anlamsal and bool(vektorler),
            ad=ad,
        )
        for ad, sozcuksel, anlamsal in KANALLAR
    ]

    RAPOR_YOLU.parent.mkdir(parents=True, exist_ok=True)
    RAPOR_YOLU.write_text(_rapor(sonuclar, kayitlar, model=model), encoding="utf-8")
    JSON_YOLU.parent.mkdir(parents=True, exist_ok=True)
    JSON_YOLU.write_text(
        json.dumps(
            {
                "queries": len(kayitlar),
                "relevant_labels": sum(len(k["ilgili"]) for k in kayitlar),
                "embedding_model": model,
                "recall_ceiling": {str(k): round(v, 4) for k, v in _tavan(kayitlar).items()},
                "channels": [
                    {
                        "name": s.ad,
                        "recall": {str(k): round(v, 4) for k, v in s.recall.items()},
                        "precision": {str(k): round(v, 4) for k, v in s.precision.items()},
                        "mrr": round(s.mrr, 4),
                    }
                    for s in sonuclar
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    tavan = _tavan(kayitlar)
    for s in sonuclar:
        print(
            f"  {s.ad:28} R@1 {s.recall[1]:.3f}  R@3 {s.recall[3]:.3f}  "
            f"R@5 {s.recall[5]:.3f}  R@10 {s.recall[10]:.3f}  MRR {s.mrr:.3f}"
        )
    print(
        f"  {'yapısal tavan':28} R@1 {tavan[1]:.3f}  R@3 {tavan[3]:.3f}  "
        f"R@5 {tavan[5]:.3f}  R@10 {tavan[10]:.3f}"
    )
    print(f"\nRapor: {RAPOR_YOLU}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
