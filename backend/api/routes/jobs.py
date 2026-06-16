import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, field_validator

from db import get_db
from models.job import Job, FileResult
from worker.tasks import run_agent_task

router = APIRouter(prefix="/api/jobs")


class JobCreate(BaseModel):
    repo_url: str

    @field_validator("repo_url")
    @classmethod
    def validate_github_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("https://github.com/"):
            raise ValueError("repo_url must be a github.com HTTPS URL")
        if v.count("/") < 4:
            raise ValueError("repo_url must point to a specific repo, e.g. https://github.com/owner/repo")
        return v.rstrip("/")


class JobOut(BaseModel):
    id: str
    repo_url: str
    status: str
    summary: str | None
    pr_url: str | None


class FileResultOut(BaseModel):
    path: str
    debt_score: int | None
    line_count: int | None
    diff: str | None


class JobDetailOut(JobOut):
    files: list[FileResultOut]


@router.post("", response_model=dict)
async def create_job(body: JobCreate, db: AsyncSession = Depends(get_db)):
    job_id = str(uuid.uuid4())

    job = Job(id=job_id, repo_url=body.repo_url, status="queued")
    db.add(job)
    await db.commit()

    # hand off to Celery — returns immediately, doesn't wait for the agent
    run_agent_task.delay(body.repo_url, job_id)

    return {"job_id": job_id}


@router.get("/{job_id}", response_model=JobDetailOut)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    files_result = await db.execute(
        select(FileResult).where(FileResult.job_id == job_id)
    )
    files = files_result.scalars().all()

    return JobDetailOut(
        id=job.id,
        repo_url=job.repo_url,
        status=job.status,
        summary=job.summary,
        pr_url=job.pr_url,
        files=[
            FileResultOut(
                path=f.file_path,
                debt_score=f.debt_score,
                line_count=f.line_count,
                diff=f.diff,
            )
            for f in files
        ],
    )


@router.get("", response_model=list[JobOut])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).order_by(Job.created_at.desc()).limit(50))
    jobs = result.scalars().all()
    return [
        JobOut(
            id=j.id,
            repo_url=j.repo_url,
            status=j.status,
            summary=j.summary,
            pr_url=j.pr_url,
        )
        for j in jobs
    ]