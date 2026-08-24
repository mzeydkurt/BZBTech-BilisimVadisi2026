"""Erişim katmanı — BM25, süzgeç kapısı, toplama ve cevap denetimi.

⚠️ AĞA ÇIKMAZ. Gövde elle kurulan `CampaignDoc` nesnelerinden üretilir; model
çağrıları sahte sağlayıcıyla yapılır.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.ai.providers.base import LLMProvider, LLMResponse, LLMUnavailableError, ModelInfo
from app.retrieval import aggregate
from app.retrieval.answer import generate_answer
from app.retrieval.corpus import CampaignDoc, Corpus
from app.retrieval.lexical import Bm25Index, tokenize
from app.retrieval.query import AggregateSpec, parse_query
from app.retrieval.search import filter_all, search
from app.retrieval.semantic import EmbeddingStore, cosine, pack_vector, unpack_vector


def _doc(
    campaign_id: int,
    *,
    bank_code: str = "kuveyt_turk",
    bank_name: str = "Kuveyt Türk",
    title: str = "Kampanya",
    card_text: str = "kampanya metni",
    status: str = "active",
    axis: dict[str, frozenset[str]] | None = None,
    metrics: dict[str, Decimal] | None = None,
) -> CampaignDoc:
    return CampaignDoc(
        campaign_id=campaign_id,
        bank_code=bank_code,
        bank_name=bank_name,
        title=title,
        card_text=card_text,
        status=status,
        source_url=f"https://example.test/{campaign_id}",
        date_precision="exact",
        axis_values=axis or {},
        metrics=metrics or {},
        summary=None,
    )


def _corpus(docs: list[CampaignDoc]) -> Corpus:
    govde = {doc.campaign_id: f"{doc.title}\n{doc.bank_name}\n{doc.card_text}" for doc in docs}
    return Corpus(docs={doc.campaign_id: doc for doc in docs}, index=Bm25Index(govde))


class _SahteSaglayici(LLMProvider):
    """Sabit metin döndüren sağlayıcı."""

    def __init__(self, text: str, *, hata: Exception | None = None) -> None:
        self._text = text
        self._hata = hata

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(name="sahte", version="v1", license="Apache-2.0", is_local=True)

    async def health(self) -> bool:
        return True

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    async def generate(self, prompt: str, **kwargs: Any) -> LLMResponse:
        if self._hata is not None:
            raise self._hata
        return LLMResponse(text=self._text, model_name="sahte", latency_ms=1)


class TestBm25:
    def test_terimler_ve_ile_baglanmaz(self) -> None:
        """⚠️ Terimleri kesişimle bağlamak SIFIR sonuç üretiyordu.

        Bugünkü `chat_service` "Kuveyt Türk'te market kampanyası" sorgusunda üç
        terimi birden içeren kayıt bulamayıp boş dönüyordu.
        """
        dizin = Bm25Index({1: "kuveyt türk market kampanyası", 2: "market indirimi"})
        bulunan = {vurus.doc_id for vurus in dizin.search(tokenize("kuveyt türk market"))}
        assert bulunan == {1, 2}

    def test_turkce_ek_alan_kelime_eslesir(self) -> None:
        """ "market" sorgusu "markette" kelimesini bulmalı."""
        dizin = Bm25Index({1: "marketlerde geçerli kampanya"})
        assert dizin.search(["market"])

    def test_kisa_terim_on_ek_eslesmesi_yapmaz(self) -> None:
        """⚠️ Kısa terimde ön ek eşleşmesi gürültü üretir ("ay" → "ayakkabı")."""
        dizin = Bm25Index({1: "ayakkabı kampanyası"})
        assert dizin.search(["ay"]) == []

    def test_her_kartta_gecen_terim_puani_dusurmez(self) -> None:
        """⚠️ Klasik idf biçimi negatif değer üretip sıralamayı tersine çeviriyordu."""
        dizin = Bm25Index({1: "kampanya market", 2: "kampanya akaryakıt", 3: "kampanya giyim"})
        for vurus in dizin.search(["kampanya"]):
            assert vurus.score > 0


class TestSuzgecKapisi:
    def test_sayisal_esik_metin_benzerligini_ezer(self) -> None:
        """⚠️ Süzgeç bir KAPIDIR, puan değil."""
        docs = [
            _doc(1, card_text="kâr payı oranı %4,20", metrics={"profit_rate_pct": Decimal("4.20")}),
            _doc(2, card_text="kâr payı oranı %1,50", metrics={"profit_rate_pct": Decimal("1.50")}),
        ]
        plan = parse_query("kâr payı oranı %2'nin altında olan kampanyalar")
        kalan, _rapor = filter_all(_corpus(docs), plan)
        assert [doc.campaign_id for doc in kalan] == [2]

    def test_degeri_olmayan_kayit_ayri_sayilir(self) -> None:
        """⚠️ "eşiği geçmedi" ile "veri yok" AYRI raporlanır."""
        docs = [
            _doc(1, metrics={"profit_rate_pct": Decimal("4.20")}),
            _doc(2, metrics={}),
        ]
        plan = parse_query("kâr payı oranı %2'nin altında olan kampanyalar")
        _kalan, rapor = filter_all(_corpus(docs), plan)
        assert "profit_rate_pct:esik" in rapor.rejected
        assert "profit_rate_pct:veri_yok" in rapor.rejected

    def test_ayri_eksenler_ve_ile_baglanir(self) -> None:
        docs = [
            _doc(1, axis={"sector": frozenset({"market_gida"}), "audience": frozenset({"emekli"})}),
            _doc(2, axis={"sector": frozenset({"market_gida"})}),
        ]
        plan = parse_query("emeklilere market kampanyası")
        kalan, _rapor = filter_all(_corpus(docs), plan)
        assert [doc.campaign_id for doc in kalan] == [1]

    def test_suzgec_govdenin_tamamina_uygulanir(self) -> None:
        """⚠️ Süzgeci aday havuzuna uygulamak listeyi BOŞALTIYORDU.

        Arama terimleriyle hiç eşleşmeyen ama süzgeci sağlayan kayıt da
        dönmelidir; aksi hâlde "banka bu kampanyayı yapmıyor" izlenimi doğar.
        """
        docs = [
            _doc(i, card_text="alakasız metin", axis={"sector": frozenset({"market_gida"})})
            for i in range(1, 6)
        ]
        plan = parse_query("market kampanyaları")
        sonuc = search(plan, _corpus(docs), limit=10)
        assert len(sonuc.hits) == 5

    def test_bos_sonucta_gevsetme_onerisi_uretilir(self) -> None:
        """⚠️ Süzgeç SESSİZCE gevşetilmez; öneri olarak bildirilir."""
        docs = [_doc(1, axis={"sector": frozenset({"akaryakit"})})]
        plan = parse_query("akaryakıt indirimi olan kampanyalar")
        sonuc = search(plan, _corpus(docs), limit=5)
        assert sonuc.hits == ()
        assert any(oneri.kind == "benefit" for oneri in sonuc.relaxation_hints)
        assert all(oneri.hit_count > 0 for oneri in sonuc.relaxation_hints)


class TestToplama:
    def test_uc_deger_tum_kayitlar_uzerinden_hesaplanir(self) -> None:
        """⚠️ Getirilen 8 kartın asgarisi, tüm kayıtların asgarisi DEĞİLDİR."""
        docs = [_doc(i, metrics={"profit_rate_pct": Decimal(str(i))}) for i in range(1, 21)]
        cevap = aggregate.compute(
            docs, AggregateSpec(kind="extremum", field="profit_rate_pct", direction="min")
        )
        assert cevap.value == Decimal("1")
        assert cevap.with_value == 20

    def test_degeri_olmayan_kayit_sifir_sayilmaz(self) -> None:
        """⚠️ `NULL` "sıfır" değildir; en düşük değer olarak seçilemez."""
        docs = [
            _doc(1, metrics={"profit_rate_pct": Decimal("2.5")}),
            _doc(2, metrics={}),
        ]
        cevap = aggregate.compute(
            docs, AggregateSpec(kind="extremum", field="profit_rate_pct", direction="min")
        )
        assert cevap.value == Decimal("2.5")
        assert cevap.without_value == 1
        assert "1 kampanyada alan çıkarılamadığı için" in aggregate.describe(cevap)

    def test_beraberlik_gizlenmez(self) -> None:
        docs = [_doc(i, metrics={"profit_rate_pct": Decimal("0")}) for i in range(1, 4)]
        cevap = aggregate.compute(
            docs, AggregateSpec(kind="extremum", field="profit_rate_pct", direction="min")
        )
        assert len(cevap.ties) == 2
        assert "2 kampanya daha" in aggregate.describe(cevap)

    def test_alan_hic_dolu_degilse_uydurma_yapilmaz(self) -> None:
        docs = [_doc(1), _doc(2)]
        cevap = aggregate.compute(
            docs, AggregateSpec(kind="extremum", field="profit_rate_pct", direction="min")
        )
        assert cevap.winner is None
        assert "karşılaştırma yapılamıyor" in aggregate.describe(cevap)

    def test_sayma_banka_bazinda_dokum_verir(self) -> None:
        docs = [
            _doc(1, bank_name="Kuveyt Türk"),
            _doc(2, bank_name="Kuveyt Türk"),
            _doc(3, bank_name="Albaraka Türk"),
        ]
        cevap = aggregate.compute(docs, AggregateSpec(kind="count"))
        assert cevap.total == 3
        assert cevap.by_bank == {"Kuveyt Türk": 2, "Albaraka Türk": 1}

    def test_bicimlendirme_bilimsel_gosterime_kacmaz(self) -> None:
        """⚠️ `Decimal.normalize()` büyük tam sayıyı `1E+4` yapıyor."""
        docs = [_doc(1, metrics={"reward_amount_try": Decimal("10000.00")})]
        cevap = aggregate.compute(
            docs, AggregateSpec(kind="extremum", field="reward_amount_try", direction="max")
        )
        metin = aggregate.describe(cevap)
        assert "10.000 TL" in metin
        assert "E+" not in metin


class TestSemantik:
    def test_vektor_paketleme_tersine_cevrilebilir(self) -> None:
        vektor = [0.5, -0.25, 0.125]
        assert unpack_vector(pack_vector(vektor)) == pytest.approx(vektor)

    def test_sifir_vektor_bolme_hatasi_firlatmaz(self) -> None:
        assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_bos_depo_arama_yapmaz(self) -> None:
        depo = EmbeddingStore({}, "nomic-embed-text")
        assert depo.is_empty
        assert depo.search([1.0, 0.0]) == []

    def test_varligin_puani_parcalarin_en_yuksegi(self) -> None:
        """⚠️ Ortalama alınsa, tek isabetli bölüm gürültüyle seyreltilirdi."""
        depo = EmbeddingStore({(7, 0): [1.0, 0.0], (7, 1): [0.0, 1.0]}, "nomic-embed-text")
        vurus = depo.search([1.0, 0.0])
        assert len(vurus) == 1
        assert vurus[0].score == pytest.approx(1.0)


class TestCevapDenetimi:
    @pytest.mark.asyncio
    async def test_kart_yoksa_model_cagrilmaz(self) -> None:
        """⚠️ Boş bağlamla yanıt istemek, modeli uydurmaya davet etmektir."""
        saglayici = _SahteSaglayici("bu metin asla dönmemeli")
        cevap = await generate_answer(
            parse_query("market kampanyası"), (), provider=saglayici, forbidden_terms={}
        )
        assert cevap.source == "refusal"
        assert "yanıt verilemiyor" in cevap.text

    @pytest.mark.asyncio
    async def test_kaynakta_olmayan_sayi_isaretlenir(self) -> None:
        """⚠️ Modelin ürettiği hiçbir sayı denetimsiz geçmez."""
        docs = [
            _doc(
                11,
                card_text="250 TL hediye çeki verilir",
                axis={"benefit": frozenset({"hediye_ceki"})},
            )
        ]
        sonuc = search(parse_query("hediye çeki"), _corpus(docs), limit=5)
        saglayici = _SahteSaglayici("Kampanya 999 TL ödül veriyor. [11]")
        cevap = await generate_answer(
            parse_query("hediye çeki"), sonuc.hits, provider=saglayici, forbidden_terms={}
        )
        assert [uydurma.value for uydurma in cevap.unverified_numbers] == ["999"]
        assert cevap.is_grounded is False

    @pytest.mark.asyncio
    async def test_kaynakta_gecen_sayi_isaretlenmez(self) -> None:
        docs = [
            _doc(
                11,
                card_text="250 TL hediye çeki verilir",
                axis={"benefit": frozenset({"hediye_ceki"})},
            )
        ]
        sonuc = search(parse_query("hediye çeki"), _corpus(docs), limit=5)
        saglayici = _SahteSaglayici("Kampanya 250 TL ödül veriyor. [11]")
        cevap = await generate_answer(
            parse_query("hediye çeki"), sonuc.hits, provider=saglayici, forbidden_terms={}
        )
        assert cevap.unverified_numbers == ()
        assert cevap.citations == (11,)

    @pytest.mark.asyncio
    async def test_atif_numarasi_uydurma_sayilmaz(self) -> None:
        """⚠️ `[11]` içindeki 11 veri değeri değil kaynak göstergesidir."""
        docs = [_doc(11, card_text="kampanya metni")]
        sonuc = search(parse_query("kampanya"), _corpus(docs), limit=5)
        saglayici = _SahteSaglayici("Bir kampanya bulundu. [11]")
        cevap = await generate_answer(
            parse_query("kampanya"), sonuc.hits, provider=saglayici, forbidden_terms={}
        )
        assert cevap.unverified_numbers == ()

    @pytest.mark.asyncio
    async def test_baglamda_olmayan_atif_sayilmaz(self) -> None:
        docs = [_doc(11, card_text="kampanya metni")]
        sonuc = search(parse_query("kampanya"), _corpus(docs), limit=5)
        saglayici = _SahteSaglayici("Yanıt. [999]")
        cevap = await generate_answer(
            parse_query("kampanya"), sonuc.hits, provider=saglayici, forbidden_terms={}
        )
        assert cevap.citations == ()

    @pytest.mark.asyncio
    async def test_yasakli_terim_uyari_uretir(self) -> None:
        docs = [_doc(11, card_text="kâr payı oranı %2")]
        sonuc = search(parse_query("kâr payı"), _corpus(docs), limit=5)
        saglayici = _SahteSaglayici("Bu kampanyanın faiz oranı düşüktür. [11]")
        cevap = await generate_answer(
            parse_query("kâr payı"),
            sonuc.hits,
            provider=saglayici,
            forbidden_terms={"faiz": "kâr payı"},
        )
        assert [uyari.term for uyari in cevap.terminology_warnings] == ["faiz"]
        assert cevap.is_grounded is False

    @pytest.mark.asyncio
    async def test_model_erisilemezse_sistem_cokmez(self) -> None:
        """⚠️ Model kapalıyken sıralı sonuçlar hâlâ gösterilebilir."""
        docs = [_doc(11, card_text="kampanya metni")]
        sonuc = search(parse_query("kampanya"), _corpus(docs), limit=5)
        saglayici = _SahteSaglayici("", hata=LLMUnavailableError("servis yok"))
        cevap = await generate_answer(
            parse_query("kampanya"), sonuc.hits, provider=saglayici, forbidden_terms={}
        )
        assert cevap.source == "template"
        assert cevap.model_error == "servis yok"
        assert "kampanya" in cevap.text.lower()

    @pytest.mark.asyncio
    async def test_saglayici_yoksa_sablon_yanit(self) -> None:
        docs = [_doc(11, card_text="kampanya metni")]
        sonuc = search(parse_query("kampanya"), _corpus(docs), limit=5)
        cevap = await generate_answer(
            parse_query("kampanya"), sonuc.hits, provider=None, forbidden_terms={}
        )
        assert cevap.source == "template"
        assert cevap.model_error is None
