"""
Standalone entry point for running the agent loop as a subprocess.
Invoked by worker/tasks.py via `python -m agent.runner <repo_url> <job_id>`.

This file exists specifically to avoid Celery's stdio hijacking —
running here gives the MCP SDK's stdio_client real, unproxied file
descriptors to spawn its own subprocesses (the MCP servers).
"""
import asyncio
import json
import sys

import redis
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from config import REDIS_URL, DATABASE_URL
from models.job import Job, FileResult
from agent.loop import run_agent

_sync_url = DATABASE_URL.replace("+asyncpg", "+psycopg2")
_engine   = create_engine(_sync_url)


def emit_log(job_id: str, text: str) -> None:
    r = redis.from_url(REDIS_URL)
    r.publish(f"job:{job_id}:logs", json.dumps({"text": text}))
    r.rpush(f"job:{job_id}:log_history", text)
    r.close()


def _update_job_sync(job_id: str, **kwargs) -> None:
    with Session(_engine) as session:
        session.execute(update(Job).where(Job.id == job_id).values(**kwargs))
        session.commit()


def _save_file_result_sync(job_id, file_path, debt_score, reasons, diff) -> None:
    with Session(_engine) as session:
        existing = session.query(FileResult).filter_by(
            job_id=job_id, file_path=file_path
        ).first()
        if existing:
            if debt_score is not None: existing.debt_score = debt_score
            if reasons is not None: existing.reasons = reasons
            if diff is not None: existing.diff = diff
        else:
            session.add(FileResult(job_id=job_id, file_path=file_path,
                                   debt_score=debt_score, reasons=reasons, diff=diff))
        session.commit()


async def _update_job(job_id: str, **kwargs) -> None:
    await asyncio.to_thread(_update_job_sync, job_id, **kwargs)


async def _save_file_result(job_id, file_path, debt_score, reasons, diff) -> None:
    await asyncio.to_thread(_save_file_result_sync, job_id, file_path, debt_score, reasons, diff)


async def main():
    repo_url = sys.argv[1]
    job_id   = sys.argv[2]

    is_job_finished = False

    try:
        await run_agent(
            repo_url=repo_url,
            job_id=job_id,
            emit_log=emit_log,
            update_job=_update_job,
            save_file_result=_save_file_result,
        )
        is_job_finished = True
    except BaseException as e:
        if is_job_finished:
            emit_log(job_id, f"[runner] non-fatal cleanup error after completion: {type(e).__name__}: {e}")
            return
        import traceback
        emit_log(job_id, f"[runner] FATAL: {type(e).__name__}: {e}")
        emit_log(job_id, f"[runner] traceback:\n{traceback.format_exc()}")
        await _update_job(job_id, status="failed", summary=f"{type(e).__name__}: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())