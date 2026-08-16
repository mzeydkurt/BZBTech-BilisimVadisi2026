"""LLM sağlayıcı sağlık kontrolü.

Yapılandırılmış sağlayıcıya ulaşılıp ulaşılamadığını söyler.

⚠️ SPRINT 3A'da `local` için "servis yok" çıktısı BEKLENEN sonuçtur, hata
değildir: model SPRINT 3B'de kurulacak. Bu yüzden betik, servise ulaşılamaması
durumunda da sıfır kodla döner — sağlık kontrolü durumu ÖĞRENMEK içindir.

Çalıştırma:
    python dev.py llm-saglik
    python dev.py llm-saglik --saglayici local
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.ai.providers import PROVIDERS, get_provider
from app.config import get_settings
from app.logging_config import configure_logging


async def _kontrol(saglayici_adi: str | None) -> int:
    """Sağlayıcıyı kurar ve sağlık durumunu yazar."""
    settings = get_settings()
    if saglayici_adi:
        settings = settings.model_copy(update={"llm_provider": saglayici_adi})

    try:
        provider = get_provider(settings)
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1

    bilgi = provider.model_info
    print(f"Sağlayıcı   : {settings.llm_provider}")
    print(f"Model       : {bilgi.name}")
    print(f"Yerel mi    : {'evet' if bilgi.is_local else 'HAYIR ⚠️'}")
    print(f"Bağlam      : {bilgi.context_tokens} token")

    ayakta = await provider.health()
    if ayakta:
        print("Durum       : ✅ hazır")
    else:
        print("Durum       : ⚠️ servis yok (SPRINT 3A'da `local` için beklenen)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Betiğin giriş noktası."""
    ayristirici = argparse.ArgumentParser(description="LLM sağlayıcı sağlık kontrolü")
    ayristirici.add_argument(
        "--saglayici",
        choices=PROVIDERS,
        help="Ayardaki sağlayıcı yerine bunu dener",
    )
    argumanlar = ayristirici.parse_args(argv)

    configure_logging()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    return asyncio.run(_kontrol(argumanlar.saglayici))


if __name__ == "__main__":
    sys.exit(main())
