import httpx
import asyncio
import random
import os
from typing import List, Dict, Any
import statistics
import re
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
        """특정 카테고리의 모든 페이지 상품 리스트를 가져옵니다."""
        url = f"{self.BASE_URL}/api/goods/v1/goods/dispGoodsList"
        base_payload = {
            "dispCtgNoList": [ctg_no],
            "brandNoList": [], "lsprdGrdCdList": [], "homeCdList": [],
            "ppYmdList": [], "strgMthdGbCdList": [], "workMethTypCdList": [],
            "deliProcTypCdList": [], "recomBkindList": [], "qualityList": [],
            "insfatGrdList": [], "mffldList": [], "estNoList": [],
            "sortTpCd": "10",
            "pageSize": 100,
            "aplyPsbMediaCd": "01",
            "curCtgNo": ctg_no,
            "noDispCtgRegYn": "N",
            "mbrNo": "",
        }
        
        all_items: List[Dict] = []
        page_no = 1

        async with httpx.AsyncClient(headers=self.HEADERS, verify=False) as client:
            while True:
                page_items: List[Dict] = []
                total_count = 0

                for attempt in range(3):
                    try:
                        payload = {**base_payload, "pageNo": page_no}
                        response = await client.post(url, json=payload, timeout=15.0)
                        response.raise_for_status()

                        payload_data = response.json().get("payload", [])
                        if isinstance(payload_data, dict):
                            page_items = (
                                payload_data.get("list")
                                or payload_data.get("items")
                                or payload_data.get("goodsList")
                                or []
                            )
                            total_count = int(
                                payload_data.get("totCnt")
                                or payload_data.get("totalCount")
                                or 0
                            )
                        elif isinstance(payload_data, list):
                            page_items = payload_data

                        if page_items and not total_count:
                            total_count = int(page_items[0].get("totCnt") or 0)
                        break
                    except Exception as e:
                        log.error(
                            "api_call_failed",
                            attempt=attempt,
                            ctg_no=ctg_no,
                            page_no=page_no,
                            error=str(e),
                        )
                        await asyncio.sleep(random.uniform(1, 3))
                else:
                    break

                if not page_items:
                    break

                all_items.extend(page_items)
                if total_count and len(all_items) >= total_count:
                    break
                if not total_count and len(page_items) < base_payload["pageSize"]:
                    break

                page_no += 1

        return all_items

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
            age = item.get("mage") or item.get("monthOfAge") or item.get("age")
            mfg_ymd = item.get("ppYmd", "") or item.get("mfgYmd", "")
            expiry_ymd = item.get("useByYmd", "") or item.get("exprYmd", "") or item.get("expYmd", "")
            storage_type = {"1": "CHILLED", "2": "FROZEN"}.get(str(item.get("strgMthdGbCd") or ""))
            species_name = str(item.get("lsspeNm") or "")
            species = "PORK" if "돈" in species_name else "BEEF" if "한우" in species_name else None

            goods_no = str(goods_no).strip() if goods_no is not None else ""
            if not goods_no or not storage_type or not species:
                continue
            
            # 필터링 조건 로직
            # 한우 월령은 1~40개월, 한돈 월령은 NULL로 정규화한다.
            age_int = None
            if age:
                try:
                    age_int = int(age)
                except (TypeError, ValueError):
                    age_int = None

            if species == "BEEF" and (age_int is None or not 1 <= age_int <= 40):
                continue
            if species == "PORK":
                age_int = None
                
            # 2. 등급 조건 필터링 (1++, 1+, 1)
            # 조건이 명확히 명시된 경우 필터, 안된 경우 패스 
            # (만약 한우의 경우에만 등급이 필수라면, 한우인지 체크도 필요할 수 있음)
            grade_match = re.search(r"1\+\+|1\+|1", str(grd))
            normalized_grade = grade_match.group(0) if grade_match else None
            if species == "BEEF" and normalized_grade is None:
                continue

            # 1kg당 가격 계산 표준화
            try:
                sale_price = int(str(item.get("salePrc") or "").replace(",", ""))
            except (TypeError, ValueError):
                continue
            weight = item.get("useEnabWgt") or item.get("invtWgt")
            weight_kg = None
            if weight:
                try:
                    w_val = float(str(weight).replace(",", ""))
                    if w_val > 0:
                        weight_kg = w_val
                except (TypeError, ValueError):
                    weight_kg = None
            if sale_price <= 0 or weight_kg is None:
                continue

            price_per_kg = int(round(sale_price / weight_kg))
            if price_per_kg <= 0:
                continue

            filtered.append({
                "name": goods_nm,
                "price": price_per_kg,
                "brand": brand_nm,
                "detail_url": f"https://www.ekcm.co.kr/pd/productDetail?goodsNo={goods_no}&artcCd={artc_cd}",
                "goodsNo": goods_no,
                "metadata": {
                    "age": age_int,
                    "grade": normalized_grade,
                    "mfg_date": mfg_ymd,
                    "expiry_date": expiry_ymd,
                    "weight_kg": weight_kg,
                    "sale_price": sale_price or None,
                    "species": species,
                    "storage_type": storage_type,
                }
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
        
        # 1. 카테고리 트리 동적 조회 (Geumcheonmit API로부터 직접 트리 구조 fetch)
        try:
            from app.scraper import fetch_category_tree
            nodes = fetch_category_tree()
        except Exception as e:
            log.error("fetch_category_tree_failed", error=str(e))
            return []

        # 2. 백엔드에 카테고리 트리 동기화 요청
        await self.sync_category_tree_to_backend(nodes)

        # 한우 암소와 한돈의 모든 브랜드/부위 말단 카테고리를 수집한다.
        leaf_nodes = [
            n for n in nodes 
            if n.get("leafYn") == "Y"
            and (
                "국내산 한우 암소" in n.get("path", "")
                or "국내산 돈육" in n.get("path", "")
            )
        ]
        
        log.info("start_full_crawl_dynamic", total_leaf_categories=len(leaf_nodes))
        
        for idx, node in enumerate(leaf_nodes):
            ctg_no = node["ctgNo"]
            category_path = node["path"]
            
            log.info("start_crawling", index=idx+1, total=len(leaf_nodes), category=category_path, ctg_no=ctg_no)
            
            items = await self.fetch_goods_list(ctg_no)
            if items:
                analyzed_result = self.process_and_analyze(category_path, items)
                results.append(analyzed_result)
            
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
        # 4. 분석 완료된 상품 리스트를 백엔드로 개별 인입
        await self.ingest_to_backend(results)
        
        return results

    async def sync_category_tree_to_backend(self, nodes: List[Dict[str, Any]]):
        """카테고리 트리 데이터를 백엔드로 전송하여 동기화합니다."""
        url = f"{self.BACKEND_URL}/crawler/category-tree"
        log.info("sync_category_tree_to_backend", url=url, nodes_count=len(nodes))
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json={"categories": nodes}, timeout=30.0)
                response.raise_for_status()
                log.info("sync_category_tree_success", status=response.status_code)
            except Exception as e:
                log.error("sync_category_tree_failed", error=str(e))

    async def ingest_to_backend(self, results: List[Dict[str, Any]]):
        """분석 완료된 데이터를 NestJS BE로 잉제스트합니다. (카테고리별 개별 전송)"""
        url = f"{self.BACKEND_URL}/crawler/ingest"
        log.info("ingesting_to_backend", url=url, total_categories_crawled=len(results))
        
        success_count = 0
        fail_count = 0
        
        async with httpx.AsyncClient() as client:
            for result in results:
                try:
                    # 카테고리 1개씩 전송 (Vercel 30s timeout 회피)
                    response = await client.post(url, json={"data": [result]}, timeout=60.0)
                    response.raise_for_status()
                    success_count += 1
                    log.info("ingest_category_success", category=result.get("category_path"), status=response.status_code)
                    await asyncio.sleep(0.5)  # 서버 과부하 방지
                except Exception as e:
                    fail_count += 1
                    log.error("ingest_category_failed", category=result.get("category_path"), error=str(e))
        
        log.info("ingest_complete", success=success_count, failed=fail_count)

    async def peek_metadata(self) -> Dict[str, Any]:
        """peek_metadata: 임시 구현. 필요시 fetch_goods_list로 건수 반환"""
        # (기존 NestJS와의 호환성을 위해 유지. 현재 요구사항의 핵심은 아님)
        return {"140101": 50, "130101": 20}
