import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from app.service import CrawlerService


def response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://backend/crawler/ingest")
    return httpx.Response(status_code, request=request, text="response")


def result_with_items(item_count: int):
    return {
        "category_path": "국내산 한우 암소,39.9,채끝",
        "statistics": {"total_count": item_count},
        "items": [{"goodsNo": str(index)} for index in range(item_count)],
    }


class FakeAsyncClient:
    def __init__(self, post):
        self.post = post

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class IngestResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_splits_items_into_fifty_item_chunks(self):
        post = AsyncMock(return_value=response(200))
        service = CrawlerService()

        with patch("app.service.httpx.AsyncClient", return_value=FakeAsyncClient(post)):
            with patch("app.service.asyncio.sleep", new=AsyncMock()):
                await service.ingest_to_backend([result_with_items(121)])

        self.assertEqual(post.await_count, 3)
        chunk_sizes = [len(call.kwargs["json"]["data"][0]["items"]) for call in post.await_args_list]
        self.assertEqual(chunk_sizes, [50, 50, 21])

    async def test_retries_read_timeout_three_times_then_succeeds(self):
        request = httpx.Request("POST", "https://backend/crawler/ingest")
        post = AsyncMock(side_effect=[
            httpx.ReadTimeout("slow", request=request),
            httpx.ReadTimeout("slow", request=request),
            httpx.ReadTimeout("slow", request=request),
            response(200),
        ])
        service = CrawlerService()

        with patch("app.service.httpx.AsyncClient", return_value=FakeAsyncClient(post)):
            with patch("app.service.asyncio.sleep", new=AsyncMock()) as sleep:
                await service.ingest_to_backend([result_with_items(1)])

        self.assertEqual(post.await_count, 4)
        self.assertEqual([call.args[0] for call in sleep.await_args_list[:3]], [1, 2, 4])

    async def test_does_not_retry_client_error(self):
        post = AsyncMock(return_value=response(400))
        service = CrawlerService()

        with patch("app.service.httpx.AsyncClient", return_value=FakeAsyncClient(post)):
            with patch("app.service.asyncio.sleep", new=AsyncMock()):
                with self.assertRaisesRegex(RuntimeError, "백엔드 상품 인입 실패"):
                    await service.ingest_to_backend([result_with_items(1)])

        self.assertEqual(post.await_count, 1)

    async def test_retries_only_502_and_504_server_errors(self):
        post = AsyncMock(side_effect=[response(502), response(504), response(200)])
        service = CrawlerService()

        with patch("app.service.httpx.AsyncClient", return_value=FakeAsyncClient(post)):
            with patch("app.service.asyncio.sleep", new=AsyncMock()):
                await service.ingest_to_backend([result_with_items(1)])

        self.assertEqual(post.await_count, 3)

    def test_checkpoint_round_trip_is_atomic(self):
        service = CrawlerService()
        with tempfile.TemporaryDirectory() as directory:
            service.CHECKPOINT_PATH = Path(directory) / "checkpoint.json"
            service._save_checkpoint({"200", "100"})

            self.assertEqual(service._load_checkpoint(), {"100", "200"})
            self.assertEqual(
                json.loads(service.CHECKPOINT_PATH.read_text(encoding="utf-8")),
                {"completedCategoryIds": ["100", "200"]},
            )
            self.assertFalse(Path(str(service.CHECKPOINT_PATH) + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
