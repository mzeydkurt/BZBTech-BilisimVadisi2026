"""Dışa aktarmayı doğrular ve manifeste damga basar (ağa çıkmaz).

⚠️ `reset_campaign_data.py` bu damga olmadan çalışmayı REDDEDER. Doğrulanmamış
bir yedeğe güvenip veri silmek, 880 satırlık elle etiketleme işini geri
getirilemez biçimde kaybetmek demektir.

Denetimler:
    1. Satır sayıları manifest ile eşleşiyor mu
    2. Dosya sha256'ları manifest ile eşleşiyor mu
    3. `campaign_key` benzersiz mi
    4. Gold'daki HER `campaign_key` kampanyalarda var mı  (%100 zorunlu)
    5. Ham HTML dosyaları diskte ve özetleri tutuyor mu

Çıkış kodu: 0 temiz · 1 bulgu var (silme engellenir) · 2 kullanım hatası.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.logging_config import configure_logging, get_logger

logger = get_logger(__name__)

# Ham arşiv denetiminde örneklenecek belge oranı. Gold'a bağlı kampanyalarda
# örnekleme yapılmaz; oradaki kayıp doğrudan ölçümü bozar.
ORNEK_ORANI = 0.10
ORNEK_SEED = 42


def cozumle_dizin(yol: str | Path) -> Path:
    """Dışa aktarma yolunu çözümler; `backend/` önekini tolere eder.

    Betikler `backend/` dizininde çalışıyor, ama kullanıcı komutu depo
    kökünden yazıyor ve doğal olarak `backend/data/exports/...` diye veriyor.
    İkisi de kabul edilir.

    Args:
        yol: Kullanıcının verdiği yol.

    Returns:
        Var olan dizin; hiçbiri bulunamazsa verilen yol olduğu gibi.
    """
    aday = Path(yol)
    if aday.is_dir():
        return aday
    # `backend/data/...` -> `data/...`
    parcalar = aday.parts
    if parcalar and parcalar[0] == "backend":
        kirpik = Path(*parcalar[1:])
        if kirpik.is_dir():
            return kirpik
    # `data/...` -> `backend/data/...`
    onekli = Path("backend") / aday
    if onekli.is_dir():
        return onekli
    return aday


def _oku_jsonl(yol: Path) -> list[dict[str, Any]]:
    """JSONL dosyasını okur."""
    if not yol.exists():
        return []
    return [json.loads(satir) for satir in yol.read_text(encoding="utf-8").splitlines() if satir]


def _sha256(yol: Path) -> str:
    """Dosyanın içerik özetini döndürür."""
    return hashlib.sha256(yol.read_bytes()).hexdigest()


def dogrula(dizin: Path) -> list[str]:
    """Dışa aktarmayı denetler.

    Args:
        dizin: Dışa aktarma dizini.

    Returns:
        Bulgu listesi. BOŞ liste = temiz.
    """
    bulgular: list[str] = []

    manifest_yolu = dizin / "manifest.json"
    if not manifest_yolu.exists():
        return [f"manifest.json bulunamadı: {manifest_yolu}"]

    manifest = json.loads(manifest_yolu.read_text(encoding="utf-8"))
    sayilar: dict[str, int] = manifest.get("satir_sayilari", {})
    ozetler: dict[str, str] = manifest.get("dosya_ozetleri", {})

    # 1 + 2: satır sayısı ve dosya özeti
    for ad, beklenen in sayilar.items():
        yol = dizin / f"{ad}.jsonl"
        if not yol.exists():
            bulgular.append(f"{ad}.jsonl eksik")
            continue
        gercek = len(_oku_jsonl(yol))
        if gercek != beklenen:
            bulgular.append(f"{ad}.jsonl satır sayısı tutmuyor: {gercek} != {beklenen}")

    for ad, beklenen_ozet in ozetler.items():
        yol = dizin / ad
        if not yol.exists():
            bulgular.append(f"{ad} eksik")
            continue
        if _sha256(yol) != beklenen_ozet:
            bulgular.append(f"{ad} içerik özeti tutmuyor (dosya değişmiş)")

    kampanyalar = _oku_jsonl(dizin / "campaigns.jsonl")
    gold = _oku_jsonl(dizin / "gold_annotations.jsonl")
    belgeler = _oku_jsonl(dizin / "source_documents.jsonl")

    # 3: campaign_key benzersizliği
    anahtarlar = [k.get("campaign_key") for k in kampanyalar]
    if len(anahtarlar) != len(set(anahtarlar)):
        tekrar = {a for a in anahtarlar if anahtarlar.count(a) > 1}
        bulgular.append(f"campaign_key tekrarlıyor: {sorted(tekrar)[:5]}")

    # 4: gold → kampanya bağı %100 olmalı
    kampanya_anahtarlari = set(anahtarlar)
    eksik_gold = {
        g["campaign_key"] for g in gold if g.get("campaign_key") not in kampanya_anahtarlari
    }
    if eksik_gold:
        bulgular.append(
            f"gold'da karşılığı olmayan {len(eksik_gold)} campaign_key: {sorted(eksik_gold)[:5]}"
        )

    # 5: ham arşiv
    bulgular.extend(
        _ham_arsivi_dogrula(
            belgeler, gold_anahtarlari=set(g["campaign_key"] for g in gold), kampanyalar=kampanyalar
        )
    )

    return bulgular


def _ham_arsivi_dogrula(
    belgeler: list[dict[str, Any]],
    *,
    gold_anahtarlari: set[str],
    kampanyalar: list[dict[str, Any]],
) -> list[str]:
    """Ham HTML dosyalarının varlığını ve özetlerini denetler.

    Gold'a bağlı kampanyaların belgelerinde ÖRNEKLEME YAPILMAZ: oradaki kayıp
    doğrudan ölçümü bozar. Geri kalanda `%10` örneklenir.
    """
    arsiv = get_settings().raw_html_path
    bulgular: list[str] = []

    gold_urls = {k["source_url"] for k in kampanyalar if k.get("campaign_key") in gold_anahtarlari}

    tam_denetim = [b for b in belgeler if b.get("url") in gold_urls]
    digerleri = [b for b in belgeler if b.get("url") not in gold_urls]
    rastgele = random.Random(ORNEK_SEED)
    ornek = (
        rastgele.sample(digerleri, k=max(1, int(len(digerleri) * ORNEK_ORANI))) if digerleri else []
    )

    for belge in [*tam_denetim, *ornek]:
        yol_metni = belge.get("raw_html_path")
        if not yol_metni:
            continue
        yol = arsiv / yol_metni
        if not yol.exists():
            bulgular.append(f"ham HTML diskte yok: {yol_metni}")
            continue
        beklenen = belge.get("raw_html_sha256")
        if beklenen and _sha256(yol) != beklenen:
            bulgular.append(f"ham HTML özeti tutmuyor: {yol_metni}")

    return bulgular


def damga_bas(dizin: Path) -> None:
    """Manifeste `verified_at` damgası basar."""
    from datetime import datetime

    yol = dizin / "manifest.json"
    manifest = json.loads(yol.read_text(encoding="utf-8"))
    manifest["verified_at"] = datetime.now().astimezone().isoformat()
    yol.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def dogrulanmis_mi(dizin: Path) -> bool:
    """Dizin doğrulama damgası taşıyor mu?"""
    yol = dizin / "manifest.json"
    if not yol.exists():
        return False
    return bool(json.loads(yol.read_text(encoding="utf-8")).get("verified_at"))


def main(argv: list[str] | None = None) -> int:
    """Doğrulamayı çalıştırır."""
    parser = argparse.ArgumentParser(
        prog="verify_export", description="Dışa aktarmayı doğrular ve damga basar."
    )
    parser.add_argument("--dizin", required=True, help="Dışa aktarma dizini")
    args = parser.parse_args(argv)
    configure_logging()

    dizin = cozumle_dizin(args.dizin)
    if not dizin.is_dir():
        print(f"Dizin bulunamadı: {dizin}")  # noqa: T201
        return 2

    bulgular = dogrula(dizin)
    if bulgular:
        print(f"\nHATA: {len(bulgular)} bulgu  SİLME ADIMI ÇALIŞTIRILMAMALI:\n")  # noqa: T201
        for bulgu in bulgular[:30]:
            print(f"  · {bulgu}")  # noqa: T201
        return 1

    damga_bas(dizin)
    print(f"\nOK: Doğrulandı ve damgalandı: {dizin}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
