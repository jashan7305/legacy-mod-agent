import asyncio
import json
import subprocess
import sys

import redis
from celery import Celery
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from config import REDIS_URL, DATABASE_URL
from models.job import Job, FileResult

app = Celery("tasks", broker=REDIS_URL, backend=REDIS_URL)

_sync_url = DATABASE_URL.replace("+asyncpg", "+psycopg2")
_engine   = create_engine(_sync_url)


def emit_log(job_id: str, text: str) -> None:
    r = redis.from_url(REDIS_URL)
    r.publish(f"job:{job_id}:logs", json.dumps({"text": text}))
    r.rpush(f"job:{job_id}:log_history", text)
    r.close()


def finish_stream(job_id: str) -> None:
    r = redis.from_url(REDIS_URL)
    r.publish(f"job:{job_id}:logs", json.dumps({"type": "done"}))
    r.close()


def _update_job_sync(job_id: str, **kwargs) -> None:
    with Session(_engine) as session:
        session.execute(update(Job).where(Job.id == job_id).values(**kwargs))
        session.commit()


@app.task(name="run_agent_task")
def run_agent_task(repo_url: str, job_id: str) -> None:
    """
    Launches the agent loop as a genuinely separate subprocess.
    This avoids Celery's stdio hijacking (LoggingProxy) breaking
    the MCP SDK's stdio_client, which needs real file descriptors
    to spawn its own child processes.
    """
    emit_log(job_id, f"[worker] job picked up: {repo_url}")
    _update_job_sync(job_id, status="running")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "agent.runner", repo_url, job_id],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=1800,  # 30 min hard ceiling
        )
        if result.returncode != 0:
            emit_log(job_id, f"[worker] agent subprocess failed: {result.stderr[-1000:]}")
            _update_job_sync(job_id, status="failed",
                             summary=f"Agent process exited with code {result.returncode}")
    except subprocess.TimeoutExpired:
        emit_log(job_id, "[worker] agent subprocess timed out after 30 minutes")
        _update_job_sync(job_id, status="failed", summary="Agent timed out after 30 minutes")
    except Exception as e:
        emit_log(job_id, f"[worker] unhandled exception launching agent: {e}")
        _update_job_sync(job_id, status="failed", summary=f"Unhandled error: {e}")
    finally:
        finish_stream(job_id)