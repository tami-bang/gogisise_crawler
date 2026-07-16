import os
import asyncio
import json
from fastapi import FastAPI
from app.router import router
from app.logger import configure_logging
from app.service import CrawlerService
from app.redis_client import redis, STREAM_NAME
import structlog

configure_logging()
log = structlog.get_logger()

app = FastAPI(
    title="Geumcheon Crawler Service",
    description="FastAPI-wrapped Python crawler (peek + crawl)",
    version="1.0.0",
)

app.include_router(router)

async def redis_worker():
    """Redis Stream Consumer Worker"""
    group_name = "crawler-workers"
    consumer_name = "worker-1"
    try:
        await redis.xgroup_create(STREAM_NAME, group_name, mkstream=True, id='0')
    except Exception as e:
        if "BUSYGROUP" not in str(e):
            log.error("xgroup_create_failed", error=str(e))
    
    log.info("worker_started", stream=STREAM_NAME, group=group_name)
    service = CrawlerService()
    
    while True:
        try:
            messages = await redis.xreadgroup(group_name, consumer_name, {STREAM_NAME: ">"}, count=1, block=5000)
            if messages:
                for stream, msg_list in messages:
                    for msg_id, msg_data in msg_list:
                        payload_str = msg_data.get(b"payload", b"{}").decode("utf-8")
                        payload = json.loads(payload_str)
                        log.info("processing_task", msg_id=msg_id, payload=payload)
                        
                        try:
                            # 실제 크롤링 및 인제스트 수행
                            await service.run_full_crawl()
                            
                            # 성공 시 ACK
                            await redis.xack(STREAM_NAME, group_name, msg_id)
                            log.info("task_completed", msg_id=msg_id)
                        except Exception as inner_e:
                            log.error("task_failed", msg_id=msg_id, error=str(inner_e))
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("worker_error", error=str(e))
            await asyncio.sleep(5)

@app.on_event("startup")
async def on_startup():
    log.info("fastapi_startup", env=os.getenv("ENV", "dev"))
    asyncio.create_task(redis_worker())

@app.get("/health")
async def health():
    return {"status": "ok"}
