"""Admin uçları — health özeti + whitelist scrape/TKBB/LLM işleri.

⚠️ Kimlik doğrulama yok. Yalnızca yerel demo / şartname ortamı için.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbSession
from app.api.v1.health import health
from app.schemas.admin import AdminJobCreateRequest, AdminJobOut
from app.schemas.common import HealthResponse
from app.services import admin_jobs

router = APIRouter(prefix="/admin", tags=["admin"])


def _job_out(job: admin_jobs.AdminJob) -> AdminJobOut:
    return AdminJobOut(
        id=job.id,
        kind=job.kind,
        bank_code=job.bank_code,
        status=job.status,
        command=job.command,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        exit_code=job.exit_code,
        log=job.log,
        error=job.error,
        summary=job.summary,
    )


@router.get("/health", response_model=HealthResponse, summary="Admin sağlık özeti")
def admin_health(session: DbSession) -> HealthResponse:
    """Mevcut /health ile aynı gövde — Admin sayfası için net yol."""
    return health(session)


@router.get("/jobs", response_model=list[AdminJobOut])
def list_admin_jobs(
    limit: int = Query(default=20, ge=1, le=50),
) -> list[AdminJobOut]:
    return [_job_out(j) for j in admin_jobs.list_jobs(limit=limit)]


@router.get("/jobs/{job_id}", response_model=AdminJobOut)
def get_admin_job(job_id: str) -> AdminJobOut:
    job = admin_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"İş bulunamadı: {job_id}")
    return _job_out(job)


@router.post("/jobs", response_model=AdminJobOut, status_code=201)
def create_admin_job(req: AdminJobCreateRequest) -> AdminJobOut:
    """Whitelist iş başlatır. Eşzamanlı tek job."""
    bank = req.bank_code.strip() if req.bank_code else None
    try:
        job = admin_jobs.start_job(req.kind, bank)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_out(job)
