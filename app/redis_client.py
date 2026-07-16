import os
import uuid
import json
from redis.asyncio import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

redis = Redis.from_url(REDIS_URL)

STREAM_NAME = "crawler:tasks"

async def publish_task(payload: dict) -> str:
    """Publish a crawl task to a Redis Stream. Returns the generated stream ID."""
    if "requestId" not in payload:
        payload["requestId"] = str(uuid.uuid4())
    entry_id = await redis.xadd(STREAM_NAME, {"payload": json.dumps(payload)})
    return entry_id
