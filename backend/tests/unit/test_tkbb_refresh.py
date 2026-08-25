"""TKBB otomatik yenileme — bayatlık ve kilit davranışı."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.services import tkbb_refresh


def test_bayat_dosya_yok(seeded_session: Session, tmp_path: Path) -> None:
    with (
        patch.object(tkbb_refresh, "_DURUM_DOSYASI", tmp_path / "yok.txt"),
        patch.object(tkbb_refresh, "_TKBB_ARSIV", tmp_path / "arsiv"),
    ):
        assert tkbb_refresh.tkbb_bayat_mi(seeded_session) is True


def test_taze_durum_dosyasi(seeded_session: Session, tmp_path: Path) -> None:
    durum = tmp_path / "tkbb_last_success.txt"
    durum.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    with patch.object(tkbb_refresh, "_DURUM_DOSYASI", durum):
        assert tkbb_refresh.tkbb_bayat_mi(seeded_session) is False


def test_eski_durum_bayat(seeded_session: Session, tmp_path: Path) -> None:
    durum = tmp_path / "tkbb_last_success.txt"
    eski = datetime.now(UTC) - timedelta(hours=25)
    durum.write_text(eski.isoformat(), encoding="utf-8")
    with patch.object(tkbb_refresh, "_DURUM_DOSYASI", durum):
        assert tkbb_refresh.tkbb_bayat_mi(seeded_session) is True


def test_ensure_taze_cekmez(seeded_session: Session, tmp_path: Path) -> None:
    durum = tmp_path / "tkbb_last_success.txt"
    durum.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    with (
        patch.object(tkbb_refresh, "_DURUM_DOSYASI", durum),
        patch("scripts.scrape_tkbb.cek_widgetlari") as mock_cek,
    ):
        assert tkbb_refresh.ensure_tkbb_fresh(seeded_session) is True
        mock_cek.assert_not_called()
