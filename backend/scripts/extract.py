"""Çıkarım çalıştırma komutu.

AĞA ÇIKMAZ. Kayıtlı `clean_text` üzerinde çalışır; bankalara istek gitmez.

⚠️ SPRINT 3A'da LLM katmanı `MockProvider` ile çalışır (`LLM_PROVIDER=mock`).
Gerçek model SPRINT 3B'de takılacak; bu komut değişmeyecek.

Çalıştırma:
    python dev.py cikarim --sadece-kural          # tablo + kural
    python dev.py cikarim --tumu                  # tablo + kural + LLM (hybrid)
    python dev.py cikarim --sadece-llm            # yalnızca LLM (ablasyon)
    python dev.py cikarim --tumu --yeniden          # önbelleği yok say
    python dev.py cikarim --tumu --banka ziraat_katilim --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.ai.pipeline import run_extraction
from app.ai.validation import Conflict
from app.ai.providers import get_provider
from app.config import get_settings
from app.db.session import SessionLocal
from app.logging_config import configure_logging

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Kip → raporda gösterilecek CLI bayrağı.
_BAYRAK: dict[str, str] = {
    "rule_only": "--sadece-kural",
    "hybrid": "--tumu",
    "llm_only": "--sadece-llm",
}

# CLI bayrağı → çalıştırma kipi.
KIPLER: dict[str, str] = {
    "sadece_kural": "rule_only",
    "tumu": "hybrid",
    "sadece_llm": "llm_only",
}


def _kip_sec(argumanlar: argparse.Namespace) -> str | None:
    """Seçilen kipi döndürür; hiçbiri ya da birden fazlası verildiyse None."""
    secilenler = [kip for bayrak, kip in KIPLER.items() if getattr(argumanlar, bayrak)]
    return secilenler[0] if len(secilenler) == 1 else None


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(description="Kampanya bilgi çıkarımı")
    ayristirici.add_argument(
        "--sadece-kural", action="store_true", help="Tablo + kural katmanı (LLM'e çağrı yok)"
    )
    ayristirici.add_argument(
        "--tumu", action="store_true", help="Tablo + kural + LLM (hybrid) — üretim kipi"
    )
    ayristirici.add_argument(
        "--sadece-llm", action="store_true", help="Yalnızca LLM (ablasyon karşılaştırması)"
    )
    ayristirici.add_argument("--banka", help="Yalnızca bu bankayı işle")
    ayristirici.add_argument("--limit", type=int, help="En fazla bu kadar kampanya")
    ayristirici.add_argument(
        "--yeniden", action="store_true", help="LLM önbelleğini yok say (yanıtları tazele)"
    )
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    # ⚠️ Varsayılan kip YOK. Hangi kipin çalıştığı ablasyon tablosunda bir
    # kolondur; sessiz bir varsayılan, iki kipin sonucunu aynı kolonda
    # toplayabilirdi.
    kip = _kip_sec(argumanlar)
    if kip is None:
        print("Tam olarak bir kip seçilmeli:")
        print("    python dev.py cikarim --sadece-kural")
        print("    python dev.py cikarim --tumu")
        print("    python dev.py cikarim --sadece-llm")
        return 1

    ayarlar = get_settings()
    saglayici = get_provider(ayarlar) if kip != "rule_only" else None
    if saglayici is not None:
        print(f"Sağlayıcı: {saglayici.model_info.name}  (LLM_PROVIDER={ayarlar.llm_provider})")

    with SessionLocal() as session:
        ozet = asyncio.run(
            run_extraction(
                session,
                saglayici,
                mode=kip,
                bank_code=argumanlar.banka,
                limit=argumanlar.limit,
                use_cache=not argumanlar.yeniden,
            )
        )

    if ozet.campaigns_processed == 0:
        print("İşlenecek kampanya bulunamadı. Önce 'python dev.py scrape' çalıştırın.")
        return 1

    print(f"\nÇalıştırma       : #{ozet.run_id}  ({ozet.mode} · {ozet.status})")
    print(f"İşlenen kampanya : {ozet.campaigns_processed}")
    print(f"Çıkarılan alan   : {ozet.fields_extracted}")
    print(f"Hata             : {ozet.errors_count}")
    print(f"Süre             : {ozet.duration_seconds} sn")

    if kip != "rule_only":
        print(f"LLM çağrısı      : {ozet.llm_calls}")
        print(f"Önbellek isabeti : {ozet.cache_hits}")
        print(f"LLM atlanan      : {ozet.llm_skipped} kampanya")

    # ── KAPI A7 — guard raporu ────────────────────────────
    print(f"\nHalüsinasyon guard'ı")
    print(f"  Reddedilen alan  : {ozet.fields_rejected}")
    print(f"  Mantık ihlali    : {ozet.logic_violations}")
    for katman, sayi in sorted((ozet.rejected_by_layer or {}).items(), key=lambda p: -p[1]):
        print(f"    {katman:24} {sayi}")

    if ozet.conflicts:
        yol = _cakismalari_yaz(ozet.conflicts, ozet.mode)
        print(f"  Çakışma          : {len(ozet.conflicts)} → {yol}")

    # ── KAPI A8 — sınıflandırma + özetleme ────────────────
    if kip != "rule_only":
        print("\nSınıflandırma + özetleme")
        print(f"  Sorulan eksen    : {ozet.axes_requested}")
        print(f"  Eklenen etiket   : {ozet.labels_added}")
        print(f"  Sözlük dışı red  : {ozet.labels_rejected}")
        print(f"  Yazılan özet     : {ozet.summaries_written}")
        print(f"  Reddedilen özet  : {ozet.summaries_rejected}")
        for gerekce, sayi in sorted((ozet.summary_rejections or {}).items(), key=lambda p: -p[1]):
            print(f"    {gerekce:30} {sayi}")

    if ozet.by_field:
        print("\nAlan bazında:")
        for alan, sayi in ozet.by_field.items():
            print(f"  {alan:24} {sayi}")

    print(f"\nSonraki adım: python dev.py degerlendir --mod {kip}")
    return 0


def _cakismalari_yaz(catismalar: list[Conflict], kip: str) -> Path:
    """Çakışmaları `docs/conflicts.md` dosyasına yazar.

    ⚠️ Çakışma sessiz geçilmez: kural ile modelin ayrıştığı her alan,
    prompt ince ayarında (SPRINT 3B) bakılacak ilk yerdir.
    """
    yol = REPO_ROOT / "docs" / "conflicts.md"
    yol.parent.mkdir(parents=True, exist_ok=True)

    satirlar = [
        "# Çıkarım çakışmaları",
        "",
        f"> `python dev.py cikarim {_BAYRAK.get(kip, kip)}` çıktısı. Otomatik üretilir.",
        "",
        "Aynı alan için birden fazla katman FARKLI değer üretti. Kazanan",
        "önceliğe göre seçildi (tablo > kural > LLM) ve güveni 0.15 düşürüldü;",
        "kaybeden kayıt SİLİNMEDİ, kendi satırında duruyor.",
        "",
        f"Toplam: **{len(catismalar)}** çakışma",
        "",
        "| Kampanya | Alan | Kazanan | Kaybeden |",
        "|---|---|---|---|",
    ]
    satirlar += [c.as_row() for c in catismalar]
    yol.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    return yol


if __name__ == "__main__":
    sys.exit(main())
