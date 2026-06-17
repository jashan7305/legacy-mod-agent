import asyncio
import json

import redis.asyncio as aioredis
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from config import REDIS_URL

router = APIRouter(prefix="/api/jobs")


@router.get("/{job_id}/stream")
async def stream_logs(job_id: str):
    async def event_generator():
        r = aioredis.from_url(
            REDIS_URL,
            socket_timeout=None,
            socket_connect_timeout=20,
            socket_keepalive=True,
        )
        pubsub = r.pubsub()
        await pubsub.subscribe(f"job:{job_id}:logs")

        try:
            # replay history first, so a client connecting mid-job
            # (or reconnecting after a refresh) doesn't miss earlier lines
            history = await r.lrange(f"job:{job_id}:log_history", 0, -1)
            for line in history:
                text = line.decode() if isinstance(line, bytes) else line
                yield f"data: {text}\n\n"

            # then stream new messages as they arrive
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()

                payload = json.loads(data)

                if payload.get("type") == "done":
                    yield "event: done\ndata: done\n\n"
                    break

                yield f"data: {payload['text']}\n\n"

        except asyncio.CancelledError:
            # client disconnected — clean exit, no error needed
            pass
        finally:
            await pubsub.unsubscribe(f"job:{job_id}:logs")
            await pubsub.aclose()
            await r.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # belt-and-suspenders alongside nginx config
            "Connection": "keep-alive",
        },
    )