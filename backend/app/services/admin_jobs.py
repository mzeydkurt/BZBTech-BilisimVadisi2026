"""Admin iş kuyruğu — whitelist alt süreç + TKBB yerinde yenileme.

⚠️ Auth yok: yalnızca yerel / demo. Üretimde dışarı açılmamalı.

TKBB: alt süreç yerine aynı SessionLocal ile yazılır; böylece API'nin
okuduğu DB ile scrape hedefi kesin aynıdır ve logda ürün/oran özeti görünür.
"""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

BACKEND_ROOT: Final[Path] = Path(__file__).resolve().parents[1].parent

AdminJobKind = Literal[
    "campaign",
    "js_campaign",
    "product",
    "bank_pipeline",
    "campaign_all",
    "js_campaign_all",
    "product_all",
    "tkbb",
    "tkbb_seed",
    "llm_health",
]

JobStatus = Literal["queued", "running", "succeeded", "failed"]

_LOG_MAX: Final[int] = 120_000

# Banka gerektiren türler.
_BANKA_ZORUNLU: Final[frozenset[str]] = frozenset(
    {"campaign", "js_campaign", "product", "bank_pipeline"}
)


@dataclass
class AdminJob:
    id: str
    kind: AdminJobKind
    bank_code: str | None
    status: JobStatus
    command: list[str]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    log: str = ""
    error: str | None = None
    summary: str | None = None


_lock = threading.Lock()
_jobs: dict[str, AdminJob] = {}
_active_id: str | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _subprocess_env() -> dict[str, str]:
    """API ile aynı DB dosyasına yazılsın diye mutlak DATABASE_URL verir."""
    env = os.environ.copy()
    ayar = get_settings()
    env["DATABASE_URL"] = ayar.sqlalchemy_url
    # `-m scripts.*` için backend kökü path'te olsun.
    py_path = env.get("PYTHONPATH", "")
    kok = str(BACKEND_ROOT)
    env["PYTHONPATH"] = kok if not py_path else f"{kok}{os.pathsep}{py_path}"
    return env


def build_command_steps(kind: AdminJobKind, bank_code: str | None) -> list[list[str]]:
    """Whitelist adım listesi. Bilinmeyen kind / eksik banka → ValueError."""
    py = sys.executable
    if kind in _BANKA_ZORUNLU and not bank_code:
        raise ValueError(f"{kind} için banka kodu zorunlu.")

    if kind == "campaign":
        return [[py, "-m", "app.scrapers.run", "--banka", bank_code or ""]]
    if kind == "js_campaign":
        return [[py, "-m", "scripts.scrape_js_campaigns", "--banka", bank_code or ""]]
    if kind == "product":
        return [[py, "-m", "scripts.scrape_products", "--banka", bank_code or ""]]
    if kind == "bank_pipeline":
        assert bank_code
        return [
            [py, "-m", "app.scrapers.run", "--banka", bank_code],
            [py, "-m", "scripts.scrape_js_campaigns", "--banka", bank_code],
            [py, "-m", "scripts.scrape_products", "--banka", bank_code],
        ]
    if kind == "campaign_all":
        return [[py, "-m", "app.scrapers.run", "--tumu"]]
    if kind == "js_campaign_all":
        return [[py, "-m", "scripts.scrape_js_campaigns"]]
    if kind == "product_all":
        return [[py, "-m", "scripts.scrape_products", "--tumu"]]
    if kind == "llm_health":
        return [[py, "-m", "scripts.llm_health"]]
    if kind in {"tkbb", "tkbb_seed"}:
        # Yerinde çalışır; komut satırı yalnızca log için.
        return [[py, "-m", "scripts.scrape_tkbb" if kind == "tkbb" else "scripts.load_tkbb_seed"]]
    raise ValueError(f"Bilinmeyen iş türü: {kind}")


def build_command(kind: AdminJobKind, bank_code: str | None) -> list[str]:
    """Tek komut (geriye dönük testler). Çok adımlı işlerde ilk adım."""
    adimlar = build_command_steps(kind, bank_code)
    return adimlar[0] if adimlar else []


def list_jobs(*, limit: int = 20) -> list[AdminJob]:
    with _lock:
        sirali = sorted(_jobs.values(), key=lambda j: j.created_at, reverse=True)
        return sirali[:limit]


def get_job(job_id: str) -> AdminJob | None:
    with _lock:
        return _jobs.get(job_id)


def start_job(kind: AdminJobKind, bank_code: str | None = None) -> AdminJob:
    """Yeni job başlatır; zaten çalışan job varsa RuntimeError."""
    global _active_id
    adimlar = build_command_steps(kind, bank_code)
    with _lock:
        if _active_id is not None:
            aktif = _jobs.get(_active_id)
            if aktif is not None and aktif.status in {"queued", "running"}:
                raise RuntimeError(
                    f"Başka bir iş zaten çalışıyor (id={_active_id}). Bitmesini bekleyin."
                )
            _active_id = None

        job = AdminJob(
            id=str(uuid.uuid4()),
            kind=kind,
            bank_code=bank_code,
            status="queued",
            command=adimlar[0]
            if len(adimlar) == 1
            else ["pipeline", *itertools.chain.from_iterable(adimlar)],
            created_at=_now_iso(),
        )
        # Daha okunur command özeti.
        if len(adimlar) > 1:
            job.command = ["+"] + [f"adim{i + 1}:{' '.join(a[2:])}" for i, a in enumerate(adimlar)]
        _jobs[job.id] = job
        _active_id = job.id

    thread = threading.Thread(target=_run_job, args=(job.id, kind, bank_code), daemon=True)
    thread.start()
    return job


def _append_log(job_id: str, chunk: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.log = (job.log + chunk)[-_LOG_MAX:]


def _set_summary(job_id: str, summary: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.summary = summary


def _run_tkbb_inplace(job_id: str, *, seed: bool) -> int:
    """Aynı süreçte TKBB yaz — API DB'si ile birebir."""
    from app.db.session import SessionLocal
    from app.services.tkbb_refresh import _basariyi_kaydet

    if seed:
        _append_log(job_id, "TKBB seed (load_tkbb_seed) yükleniyor…\n")
        from scripts.load_tkbb_seed import main as seed_main

        kod = int(seed_main())
        _append_log(job_id, f"Seed çıkış kodu: {kod}\n")
        if kod == 0:
            _basariyi_kaydet()
            _set_summary(job_id, "TKBB seed yüklendi")
        return kod

    from scripts.scrape_tkbb import WIDGET_ESLEMESI, cek_widgetlari, cekilen_veriyi_yukle

    _append_log(
        job_id,
        f"TKBB API çekiliyor ({len(WIDGET_ESLEMESI)} widget)…\n",
    )
    yakalanan = cek_widgetlari()
    eksik = set(WIDGET_ESLEMESI) - set(yakalanan)
    _append_log(job_id, f"Alınan: {len(yakalanan)}/{len(WIDGET_ESLEMESI)}\n")
    for wid in yakalanan:
        _append_log(job_id, f"  [OK] {WIDGET_ESLEMESI[wid].aciklama}\n")
    for wid in sorted(eksik):
        _append_log(job_id, f"  [EKSIK] {WIDGET_ESLEMESI[wid].aciklama}\n")

    if not yakalanan:
        _append_log(job_id, "Hiç veri alınamadı. tkbb_seed deneyin.\n")
        return 1

    with SessionLocal() as session:
        ozet = cekilen_veriyi_yukle(session, yakalanan)

    ozet_metin = (
        f"Yazıldı — ürün: {ozet.get('urun', 0)}, oran: {ozet.get('oran', 0)}, "
        f"bayat silinen: {ozet.get('silinen_bayat', 0)}, "
        f"not_offered: {ozet.get('not_offered', 0)}"
    )
    _append_log(job_id, ozet_metin + "\n")
    _set_summary(job_id, ozet_metin)
    _basariyi_kaydet()

    if eksik:
        _append_log(job_id, f"Eksik {len(eksik)} widget — kısmi başarı, çıkış 1.\n")
        return 1
    return 0


def _run_subprocess_steps(job_id: str, adimlar: list[list[str]]) -> int:
    env = _subprocess_env()
    son_kod = 0
    for i, komut in enumerate(adimlar, start=1):
        _append_log(job_id, f"\n── Adım {i}/{len(adimlar)}: {' '.join(komut)}\n")
        proc = subprocess.Popen(
            komut,
            cwd=str(BACKEND_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _append_log(job_id, line)
        kod = proc.wait()
        _append_log(job_id, f"── Adım {i} bitti (kod={kod})\n")
        if kod != 0:
            return kod
        son_kod = kod
    return son_kod


def _run_job(job_id: str, kind: AdminJobKind, bank_code: str | None) -> None:
    global _active_id
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.status = "running"
        job.started_at = _now_iso()

    logger.info("admin_job_basladi", job_id=job_id, kind=kind, bank_code=bank_code)
    try:
        if kind in {"tkbb", "tkbb_seed"}:
            kod = _run_tkbb_inplace(job_id, seed=(kind == "tkbb_seed"))
        else:
            adimlar = build_command_steps(kind, bank_code)
            kod = _run_subprocess_steps(job_id, adimlar)

        with _lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            job.exit_code = kod
            job.finished_at = _now_iso()
            job.status = "succeeded" if kod == 0 else "failed"
            if kod != 0:
                job.error = job.error or f"Çıkış kodu: {kod}"
            if _active_id == job_id:
                _active_id = None
        logger.info("admin_job_bitti", job_id=job_id, exit_code=kod)
    except Exception as exc:
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = _now_iso()
                _append_log(job_id, f"\n[hata] {exc}\n")
            if _active_id == job_id:
                _active_id = None
        logger.error("admin_job_hata", job_id=job_id, hata=str(exc))


def _reset_for_tests() -> None:
    global _active_id
    with _lock:
        _jobs.clear()
        _active_id = None


__all__ = [
    "AdminJob",
    "AdminJobKind",
    "build_command",
    "build_command_steps",
    "get_job",
    "list_jobs",
    "start_job",
]
