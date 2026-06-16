import asyncio
import json

import redis
from celery import Celery

from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from config import REDIS_URL, DATABASE_URL
from models.job import Job, FileResult

app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)

_sync_url = DATABASE_URL.replace("+asyncpg", "+psycopg2")
_engine   = create_engine(_sync_url)

def emit_log(job_id: str, text: str):
    r = redis.from_url(REDIS_URL)
    payload = json.dumps({"text": text})
    r.publish(f"job:{job_id}:logs", payload)
    r.rpush(f"job:{job_id}:log_history", text)
    r.close()

def finish_stream(job_id: str):
    r = redis.from_url(REDIS_URL)
    r.publish(f"job:{job_id}:logs", json.dumps({"type": "done"}))
    r.close()

def _update_job_sync(job_id: str, **kwargs) -> None:
    with Session(_engine) as session:
        session.execute(
            update(Job).where(Job.id == job_id).values(**kwargs)
        )
        session.commit()


def _save_file_result_sync(
    job_id: str,
    file_path: str,
    debt_score: int | None,
    reasons: str | None,
    diff: str | None,
) -> None:
    with Session(_engine) as session:
        existing = session.query(FileResult).filter_by(
            job_id=job_id, file_path=file_path
        ).first()

        if existing:
            if debt_score is not None:
                existing.debt_score = debt_score
            if reasons is not None:
                existing.reasons = reasons
            if diff is not None:
                existing.diff = diff
        else:
            session.add(FileResult(
                job_id=job_id,
                file_path=file_path,
                debt_score=debt_score,
                reasons=reasons,
                diff=diff,
            ))

        session.commit()

async def _update_job(job_id: str, **kwargs) -> None:
    await asyncio.to_thread(_update_job_sync, job_id, **kwargs)


async def _save_file_result(
    job_id: str,
    file_path: str,
    debt_score: int | None,
    reasons: str | None,
    diff: str | None,
) -> None:
    await asyncio.to_thread(
        _save_file_result_sync, job_id, file_path, debt_score, reasons, diff
    )

@app.task(name="run_agent_task")
def run_agent_task(repo_url: str, job_id: str):
    from agent.loop import run_agent

    emit_log(job_id, f"[worker] job picked up: {repo_url}")

    try:
        asyncio.run(
            run_agent(
                repo_url=repo_url,
                job_id=job_id,
                emit_log=emit_log,
                update_job=_update_job,
                save_file_result=_save_file_result,
            )
        )
    except Exception as e:
        emit_log(job_id, f"[worker] unhandled exception: {e}")
        _update_job_sync(job_id, status="failed", summary=f"Unhandled error: {e}")
    finally:
        finish_stream(job_id)