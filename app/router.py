import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.service import CrawlerService
from app.redis_client import publish_task
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/crawler")

def get_crawler_service():
    return CrawlerService()

class CrawlRequest(BaseModel):
    requestId: str | None = None
    categories: list[str] | None = None

@router.get("/peek", response_model=dict)
async def peek(service: CrawlerService = Depends(get_crawler_service)):
    """
    메타데이터를 가져옵니다. (현재 DB 상태 관리는 BE에 있으므로 단순 데이터 반환)
    """
    try:
        current_counts = await service.peek_metadata()
        log.info("peek_result", counts=current_counts)
        return {"success": True, "data": current_counts}
    except Exception as e:
        log.error("peek_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/crawl", response_model=dict, status_code=status.HTTP_202_ACCEPTED)
async def crawl(req: CrawlRequest):
    """
    큐에 작업을 발행하고 taskId를 반환.
    """
    payload = {
        "requestId": req.requestId or str(uuid.uuid4()),
        "categories": req.categories or [],
    }
    task_id = await publish_task(payload)
    log.info("crawl_task_queued", requestId=payload["requestId"], taskId=task_id)
    return {"taskId": task_id, "requestId": payload["requestId"]}
