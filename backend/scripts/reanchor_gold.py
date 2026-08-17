"""Gold etiketlerini yeniden kazınmış kampanyalara bağlar (ağa çıkmaz).

Veri sıfırlanıp yeniden kazındığında `campaign_id`'ler değişir. `campaign_key`
kalıcı olduğu için etiketler kaybolmaz, ama hızlı JOIN bağı yeniden kurulmalı.

EŞLEŞTİRME MERDİVENİ:
    1. `campaign_key` = "{bank_code}:{external_slug}"   → otomatik kabul
    2. `(bank_code, source_url)`                        → otomatik kabul
    3. `(bank_code, normalize_text(title))`             → `--baslik-esiği` gerekir

⚠️ 3. basamak varsayılan olarak KAPALIDIR. 22 başlık grubu aynı bankada 2-5 kez
tekrarlıyor (Ziraat'in aylık yinelenen kampanyaları); birden çok aday varsa
eşleşme reddedilir.

⚠️ Bağlanamayan satır SİLİNMEZ: `campaign_id IS NULL` ile durur ve
`docs/gold_reanchor.md`'de listelenir.

Çıkış kodu: 0 tam eşleşme · 1 öksüz satır var (değerlendirme çalıştırılmamalı).
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.normalization.text import normalize_text
from app.db.models import Bank, Campaign, GoldAnnotation
from app.db.session import SessionLocal
from app.logging_config import configure_logging, get_logger

logger = get_logger(__name__)

RAPOR_YOLU = Path("../docs/gold_reanchor.md")


@dataclass
class ReanchorOzeti:
    """Yeniden bağlama sonucu."""

    toplam: int = 0
    eslesen_slug: int = 0
    eslesen_url: int = 0
    eslesen_baslik: int = 0
    oksuz: int = 0
    oksuz_anahtarlar: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.oksuz_anahtarlar is None:
            self.oksuz_anahtarlar = []

    @property
    def oran(self) -> Decimal:
        """Eşleşme oranı."""
        if not self.toplam:
            return Decimal("1")
        eslesen = self.toplam - self.oksuz
        return (Decimal(eslesen) / Decimal(self.toplam)).quantize(Decimal("0.0001"))


def yeniden_bagla(
    session: Session,
    *,
    baslik_esigi: bool = False,
    kuru: bool = False,
) -> ReanchorOzeti:
    """Gold etiketlerini kampanyalara yeniden bağlar.

    Args:
        session: Veritabanı oturumu.
        baslik_esigi: True ise 3. basamak (başlık) da denenir.
        kuru: True ise yazma yapılmaz.

    Returns:
        Yeniden bağlama özeti.
    """
    kampanyalar = session.execute(
        select(
            Campaign.id, Bank.code, Campaign.external_slug, Campaign.source_url, Campaign.title
        ).join(Bank, Campaign.bank_id == Bank.id)
    ).all()

    slug_haritasi: dict[str, int] = {}
    url_haritasi: dict[tuple[str, str], int] = {}
    baslik_haritasi: dict[tuple[str, str], list[int]] = defaultdict(list)
    for cid, kod, slug, url, baslik in kampanyalar:
        slug_haritasi[f"{kod}:{slug}"] = cid
        url_haritasi[(kod, url)] = cid
        baslik_haritasi[(kod, normalize_text(baslik).casefold())].append(cid)

    ozeti = ReanchorOzeti()
    etiketler = list(session.scalars(select(GoldAnnotation)))
    ozeti.toplam = len(etiketler)

    for etiket in etiketler:
        anahtar = etiket.campaign_key
        banka_kodu = anahtar.split(":", 1)[0]

        cid = slug_haritasi.get(anahtar)
        yontem = "slug"

        if cid is None:
            # Slug şeması değişmişse (ör. `#blok` eki) adres üzerinden bakılır.
            eslesme = [v for (kod, _url), v in url_haritasi.items() if kod == banka_kodu]
            cid = next(
                (
                    v
                    for (kod, url), v in url_haritasi.items()
                    if kod == banka_kodu and url.rstrip("/").endswith(anahtar.split(":", 1)[1])
                ),
                None,
            )
            yontem = "url" if cid is not None else yontem
            del eslesme

        if cid is None and baslik_esigi:
            # ⚠️ Yalnızca TEK aday varsa kabul edilir.
            adaylar = [
                idler
                for (kod, _b), idler in baslik_haritasi.items()
                if kod == banka_kodu and len(idler) == 1
            ]
            if len(adaylar) == 1:
                cid = adaylar[0][0]
                yontem = "baslik"

        if cid is None:
            ozeti.oksuz += 1
            ozeti.oksuz_anahtarlar.append(anahtar)
            if not kuru:
                etiket.campaign_id = None
                etiket.reanchor_method = None
            continue

        if yontem == "slug":
            ozeti.eslesen_slug += 1
        elif yontem == "url":
            ozeti.eslesen_url += 1
        else:
            ozeti.eslesen_baslik += 1

        if not kuru:
            etiket.campaign_id = cid
            etiket.reanchor_method = yontem

    if not kuru:
        session.commit()

    return ozeti


def rapor_yaz(ozeti: ReanchorOzeti, *, yol: Path = RAPOR_YOLU) -> None:
    """Öksüz kalan etiketleri belgeye yazar."""
    yol.parent.mkdir(parents=True, exist_ok=True)
    satirlar = [
        "# Gold Set Yeniden Bağlama Raporu",
        "",
        f"- Toplam etiket: **{ozeti.toplam}**",
        f"- Slug ile eşleşen: {ozeti.eslesen_slug}",
        f"- Adres ile eşleşen: {ozeti.eslesen_url}",
        f"- Başlık ile eşleşen: {ozeti.eslesen_baslik}",
        f"- **Öksüz kalan: {ozeti.oksuz}**",
        f"- Eşleşme oranı: **{ozeti.oran}**",
        "",
    ]
    if ozeti.oksuz_anahtarlar:
        satirlar += [
            "## Bağlanamayan kampanya anahtarları",
            "",
            "⚠️ Bu etiketler SİLİNMEDİ; `campaign_id IS NULL` ile duruyor.",
            "Eşleşme oranı %100 olmadan `python dev.py degerlendir` çalıştırılmamalıdır:",
            "eksik gold ile ölçülen F1 sistemi olduğundan iyi gösterir.",
            "",
        ]
        for anahtar in sorted(set(ozeti.oksuz_anahtarlar)):
            satirlar.append(f"- `{anahtar}`")
        satirlar.append("")

    yol.write_text("\n".join(satirlar), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Yeniden bağlamayı çalıştırır."""
    parser = argparse.ArgumentParser(
        prog="reanchor_gold", description="Gold etiketlerini yeniden kazınmış kampanyalara bağlar."
    )
    parser.add_argument(
        "--baslik-esigi",
        action="store_true",
        help="Başlık üzerinden eşleştirmeyi de dene (RİSKLİ, tekrarlı başlıklar var)",
    )
    parser.add_argument("--kuru", action="store_true", help="Yazma yapma, yalnızca raporla")
    args = parser.parse_args(argv)
    configure_logging()

    with SessionLocal() as session:
        ozeti = yeniden_bagla(session, baslik_esigi=args.baslik_esigi, kuru=args.kuru)

    rapor_yaz(ozeti)

    print(f"\nGold yeniden bağlama{' (KURU)' if args.kuru else ''}:")  # noqa: T201
    print(f"  toplam            {ozeti.toplam}")  # noqa: T201
    print(f"  slug ile          {ozeti.eslesen_slug}")  # noqa: T201
    print(f"  adres ile         {ozeti.eslesen_url}")  # noqa: T201
    print(f"  başlık ile        {ozeti.eslesen_baslik}")  # noqa: T201
    print(f"  ÖKSÜZ             {ozeti.oksuz}")  # noqa: T201
    print(f"  eşleşme oranı     {ozeti.oran}")  # noqa: T201
    print(f"\nRapor: {RAPOR_YOLU}")  # noqa: T201

    if ozeti.oksuz:
        print("\nUYARI: Eşleşme %100 değil  'dev.py degerlendir' çalıştırılmamalı.")  # noqa: T201
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
