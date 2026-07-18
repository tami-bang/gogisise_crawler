import unittest
from unittest.mock import patch

import httpx

from app.service import CrawlerService


class FakeResponse:
    status_code = 400
    text = '{"message":"validation failed"}'

    def raise_for_status(self):
        request = httpx.Request("POST", "https://backend/crawler/category-tree")
        response = httpx.Response(self.status_code, request=request)
        raise httpx.HTTPStatusError("bad request", request=request, response=response)


class FakeAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return FakeResponse()


class FailFastPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_category_tree_sync_propagates_http_failure(self):
        service = CrawlerService()
        nodes = [{
            "ctgNo": "1",
            "name": "국내산 한우",
            "parentNo": None,
            "depth": 1,
            "path": "국내산 한우",
            "leafYn": "N",
        }]

        with patch("app.service.httpx.AsyncClient", return_value=FakeAsyncClient()):
            with self.assertRaisesRegex(RuntimeError, "카테고리 트리 동기화 실패"):
                await service.sync_category_tree_to_backend(nodes)


if __name__ == "__main__":
    unittest.main()
