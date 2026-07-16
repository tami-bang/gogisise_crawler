import httpx
import asyncio
import random
import os
from typing import List, Dict, Any
import statistics
import structlog
from app.models import CategoryMap

log = structlog.get_logger()

class CrawlerService:
    BASE_URL = "https://gw.ekcm.co.kr"
    BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.ekcm.co.kr/",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9",
    }

    async def fetch_goods_list(self, ctg_no: str) -> List[Dict]:
        """특정 카테고리의 상품 리스트를 가져옵니다."""
        url = f"{self.BASE_URL}/api/goods/v1/goods/dispGoodsList"
        payload = {
            "dispCtgNoList": [ctg_no],
            "brandNoList": [], "lsprdGrdCdList": [], "homeCdList": [],
            "ppYmdList": [], "strgMthdGbCdList": [], "workMethTypCdList": [],
            "deliProcTypCdList": [], "recomBkindList": [], "qualityList": [],
            "insfatGrdList": [], "mffldList": [], "estNoList": [],
            "sortTpCd": "10",
            "pageNo": 1,
            "pageSize": 100,
            "aplyPsbMediaCd": "01",
            "curCtgNo": ctg_no,
            "noDispCtgRegYn": "N",
            "mbrNo": "",
        }
        
        async with httpx.AsyncClient(headers=self.HEADERS, verify=False) as client:
            for attempt in range(3):
                try:
                    response = await client.post(url, json=payload, timeout=15.0)
                    response.raise_for_status()
                    
                    # API 응답 구조체 파싱 (기존 API 스키마 참고)
                    res_data = response.json()
                    payload_data = res_data.get("payload", [])
                    if isinstance(payload_data, dict):
                        items = (
                            payload_data.get("list")
                            or payload_data.get("items")
                            or payload_data.get("goodsList")
                            or []
                        )
                        return items
                    elif isinstance(payload_data, list):
                        return payload_data
                    return []
                except Exception as e:
                    log.error("api_call_failed", attempt=attempt, ctg_no=ctg_no, error=str(e))
                    await asyncio.sleep(random.uniform(1, 3))
        return []

    def process_and_analyze(self, category_path: str, items: List[Dict]) -> Dict[str, Any]:
        """가져온 상품 리스트를 필터링하고 통계를 산출합니다."""
        filtered = []
        for item in items:
            # 기본 데이터 추출
            goods_nm = item.get("goodsNm", "")
            sale_price = item.get("salePrc", 0)
            brand_nm = item.get("brandNm", "")
            goods_no = item.get("goodsNo", "")
            artc_cd = item.get("artcCd", "")
            grd = item.get("lsprdGrdNm", "") or item.get("grd", "")
            age = item.get("monthOfAge", None) or item.get("age", None)
            mfg_ymd = item.get("ppYmd", "") or item.get("mfgYmd", "")
            
            # 필터링 조건 로직
            # 1. 월령이 있을 경우 40개월 미만 (None인 경우 돼지고기이거나 데이터 누락)
            age_int = 0
            if age:
                try:
                    age_int = int(age)
                except:
                    pass
                    
            if age_int and age_int >= 40:
                continue
                
            # 2. 등급 조건 필터링 (1++, 1+, 1)
            # 조건이 명확히 명시된 경우 필터, 안된 경우 패스 
            # (만약 한우의 경우에만 등급이 필수라면, 한우인지 체크도 필요할 수 있음)
            valid_grades = ["1++", "1+", "1", "1등급", "1+등급", "1++등급", "A", "B", "C"]
            if grd and grd not in valid_grades:
                continue

            filtered.append({
                "name": goods_nm,
                "price": sale_price,
                "brand": brand_nm,
                "detail_url": f"https://www.ekcm.co.kr/pd/productDetail?goodsNo={goods_no}&artcCd={artc_cd}",
                "goodsNo": goods_no,
                "metadata": {"age": age_int if age_int else None, "mfg_date": mfg_ymd}
            })

        # 통계 계산
        prices = [i["price"] for i in filtered]
        return {
            "category_path": category_path,
            "statistics": {
                "avg_price": statistics.mean(prices) if prices else 0,
                "min_price": min(prices) if prices else 0,
                "max_price": max(prices) if prices else 0,
                "total_count": len(filtered)
            },
            "items": filtered
        }

    async def run_full_crawl(self) -> List[Dict[str, Any]]:
        """전체 카테고리에 대해 매핑을 기반으로 크롤링과 분석을 수행합니다."""
        results = []
        category_map = CategoryMap()
        
        # 국내산 돈육 크롤링
        for storage, categories in category_map.pork.items():
            for cat_name, ctg_no in categories.items():
                category_path = f"국내산 돈육 > {storage} > {cat_name}"
                log.info("start_crawling", category=category_path, ctg_no=ctg_no)
                
                items = await self.fetch_goods_list(ctg_no)
                analyzed_result = self.process_and_analyze(category_path, items)
                results.append(analyzed_result)
                
                await asyncio.sleep(random.uniform(1, 3))

        # 국내산 한우 크롤링
        for storage, categories in category_map.hanwoo.items():
            for cat_name, ctg_no in categories.items():
                category_path = f"국내산 한우 > {storage} > {cat_name}"
                log.info("start_crawling", category=category_path, ctg_no=ctg_no)
                
                items = await self.fetch_goods_list(ctg_no)
                analyzed_result = self.process_and_analyze(category_path, items)
                results.append(analyzed_result)
                
                await asyncio.sleep(random.uniform(1, 3))
                
        # 최종 결과를 NestJS 백엔드(POST /crawler/ingest)로 전송
        await self.ingest_to_backend(results)
        
        return results

    async def ingest_to_backend(self, results: List[Dict[str, Any]]):
        """분석 완료된 데이터를 NestJS BE로 잉제스트합니다."""
        url = f"{self.BACKEND_URL}/crawler/ingest"
        log.info("ingesting_to_backend", url=url, total_categories_crawled=len(results))
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json={"data": results}, timeout=30.0)
                response.raise_for_status()
                log.info("ingest_success", status=response.status_code)
            except Exception as e:
                log.error("ingest_failed", error=str(e))
                # 실패 시 어떻게 처리할지는 정책에 따라 결정 (DLQ 등)

    async def peek_metadata(self) -> Dict[str, Any]:
        """peek_metadata: 임시 구현. 필요시 fetch_goods_list로 건수 반환"""
        # (기존 NestJS와의 호환성을 위해 유지. 현재 요구사항의 핵심은 아님)
        return {"140101": 50, "130101": 20}
