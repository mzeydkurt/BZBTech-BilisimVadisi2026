"""TKBB katılma oranlarının 24 saat bayatlık denetimi ve otomatik yenileme.

URL değişmez: `https://veri-petegi.tkbb.org.tr/api/v1/data/`
(`scripts.scrape_tkbb`). İstek yolunu bozmaz; timeout/hata durumunda eski
satırlar dönmeye devam eder.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.product import ProductRate
from app.logging_config import get_logger

logger = get_logger(__name__)

_BAYATLIK: Final[timedelta] = timedelta(hours=24)
_KILIT = threading.Lock()
_SON_DENEME: float = 0.0
_MIN_ARALIK_SN: Final[float] = 60.0  # aynı süreçte spam engeli
_BACKEND: Final[Path] = Path(__file__).resolve().parents[2]
_DURUM_DOSYASI: Final[Path] = _BACKEND / "data" / "tkbb_last_success.txt"
_TKBB_ARSIV: Final[Path] = _BACKEND / "data" / "raw_html" / "tkbb"


def _dosya_zamani(path: Path) -> datetime | None:
    if not path.is_file():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _son_tkbb_zamani(session: Session) -> datetime | None:
    """Son başarılı çekim: durum dosyası → arşiv mtime → satır varlığı."""
    if _DURUM_DOSYASI.is_file():
        try:
            return datetime.fromisoformat(_DURUM_DOSYASI.read_text(encoding="utf-8").strip())
        except ValueError:
            return _dosya_zamani(_DURUM_DOSYASI)

    if _TKBB_ARSIV.is_dir():
        zamanlar = [_dosya_zamani(p) for p in _TKBB_ARSIV.glob("*.json")]
        zamanlar_f = [t for t in zamanlar if t is not None]
        if zamanlar_f:
            return max(zamanlar_f)

    # Hiç satır yoksa bayat say.
    var = session.scalar(
        select(ProductRate.id).where(ProductRate.data_source == "tkbb_veripetegi").limit(1)
    )
    if var is None:
        return None
    # Satır var ama zaman bilinmiyor → yenilemeyi zorla (güvenli taraf).
    return None


def tkbb_bayat_mi(session: Session) -> bool:
    """TKBB verisi 24 saatten eskiyse (veya yoksa) True."""
    son = _son_tkbb_zamani(session)
    if son is None:
        return True
    return datetime.now(timezone.utc) - son > _BAYATLIK


def _basariyi_kaydet() -> None:
    _DURUM_DOSYASI.parent.mkdir(parents=True, exist_ok=True)
    _DURUM_DOSYASI.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def ensure_tkbb_fresh(session: Session, *, timeout_sn: float = 45.0) -> bool:
    """Bayatsa aynı `tkbb-cek` yolunu kilit ile çalıştırır.

    Returns:
        True yenileme denendi ve başarılı / gerekmedi · False hata/timeout
        (çağıran eski satırları döndürmeye devam eder).
    """
    global _SON_DENEME
    if not tkbb_bayat_mi(session):
        return True

    simdi = time.monotonic()
    if simdi - _SON_DENEME < _MIN_ARALIK_SN:
        return False

    if not _KILIT.acquire(blocking=False):
        logger.info("tkbb_yenileme_kilitli")
        return False

    try:
        _SON_DENEME = time.monotonic()
        logger.info("tkbb_otomatik_yenileme_basladi")
        from scripts.scrape_tkbb import cek_widgetlari, cekilen_veriyi_yukle

        baslangic = time.monotonic()
        yakalanan = cek_widgetlari()
        if not yakalanan:
            logger.warning("tkbb_otomatik_bos")
            return False
        if time.monotonic() - baslangic > timeout_sn:
            logger.warning("tkbb_otomatik_timeout")
            return False
        cekilen_veriyi_yukle(session, yakalanan)
        _basariyi_kaydet()
        logger.info("tkbb_otomatik_yenileme_tamam", widget=len(yakalanan))
        return True
    except Exception as exc:
        logger.warning("tkbb_otomatik_hata", hata=str(exc))
        return False
    finally:
        _KILIT.release()


__all__ = ["ensure_tkbb_fresh", "tkbb_bayat_mi"]
