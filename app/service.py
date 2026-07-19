import httpx
import asyncio
import random
import os
import json
from pathlib import Path
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
    INGEST_CHUNK_SIZE = 50
    INGEST_MAX_RETRIES = 3
    CHECKPOINT_PATH = Path(os.getenv("CRAWLER_CHECKPOINT_PATH", "checkpoint.json"))

    def _load_checkpoint(self) -> Dict[str, List[str]]:
        if not self.CHECKPOINT_PATH.exists():
            return {}

        try:
            payload = json.loads(self.CHECKPOINT_PATH.read_text(encoding="utf-8"))
            completed = payload.get("completedCategories")
            if completed is None and "completedCategoryIds" in payload:
                log.warning("legacy_checkpoint_ignored", path=str(self.CHECKPOINT_PATH))
                return {}
            if not isinstance(completed, dict):
                raise ValueError("completedCategories must be an object")
            if not all(
                isinstance(category_id, str)
                and isinstance(goods_nos, list)
                and all(isinstance(goods_no, str) for goods_no in goods_nos)
                for category_id, goods_nos in completed.items()
            ):
                raise ValueError("completedCategories values must be string arrays")
            return completed
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"체크포인트 파일을 읽을 수 없습니다: {self.CHECKPOINT_PATH}") from exc

    def _save_checkpoint(self, completed_categories: Dict[str, List[str]]) -> None:
        self.CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.CHECKPOINT_PATH.with_suffix(self.CHECKPOINT_PATH.suffix + ".tmp")
        payload = {
            "completedCategories": {
                category_id: sorted(set(goods_nos))
                for category_id, goods_nos in sorted(completed_categories.items())
            }
        }
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, self.CHECKPOINT_PATH)

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
                        if attempt == 2:
                            raise RuntimeError(
                                f"금천미트 상품 API 최종 실패: category={ctg_no}, page={page_no}"
                            ) from e

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
            # 한우 월령은 값이 제공된 경우에만 1~40개월을 검증합니다.
            # 알꼬리·스지처럼 개체 월령/등급을 제공하지 않는 부산물도 상품번호,
            # 중량, 판매가가 유효하면 정상 판매 상품이므로 누락시키지 않습니다.
            age_int = None
            if age:
                try:
                    age_int = int(age)
                except (TypeError, ValueError):
                    age_int = None

            if species == "BEEF" and age_int is not None and not 1 <= age_int <= 40:
                continue
            if species == "PORK":
                age_int = None
                
            # 2. 등급이 존재하는 정육 상품은 1++, 1+, 1로 정규화합니다.
            # 원천 등급이 '해당없음'인 한우 부산물은 NULL을 유지합니다.
            grade_match = re.search(r"1\+\+|1\+|1", str(grd))
            normalized_grade = grade_match.group(0) if grade_match else None

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
        completed_categories = self._load_checkpoint()
        
        # 1. 카테고리 트리 동적 조회 (Geumcheonmit API로부터 직접 트리 구조 fetch)
        from app.scraper import fetch_category_tree
        nodes = fetch_category_tree()
        if not nodes:
            raise RuntimeError("금천미트 카테고리 트리가 비어 있습니다.")

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

            if ctg_no in completed_categories:
                log.info("skip_checkpointed_category", category=category_path, ctg_no=ctg_no)
                continue
            
            log.info("start_crawling", index=idx+1, total=len(leaf_nodes), category=category_path, ctg_no=ctg_no)
            
            items = await self.fetch_goods_list(ctg_no)
            analyzed_result = self.process_and_analyze(category_path, items)
            if analyzed_result["items"]:
                results.append(analyzed_result)
                await self.ingest_to_backend([analyzed_result])

            completed_categories[ctg_no] = [
                item["goodsNo"] for item in analyzed_result["items"]
            ]
            self._save_checkpoint(completed_categories)
            log.info("category_checkpoint_saved", category=category_path, ctg_no=ctg_no)
            
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
        leaf_category_ids = {node["ctgNo"] for node in leaf_nodes}
        if set(completed_categories) != leaf_category_ids:
            raise RuntimeError("전체 카테고리 완료 전에는 단종 동기화를 실행할 수 없습니다.")

        # 한국어 주석: 체크포인트에 카테고리별로 누적해 둔 상품번호를 하나의 전체
        # 스냅샷 목록으로 합칩니다. 중간 재시작 시에도 이미 완료된 카테고리의
        # goodsNo가 유실되지 않으므로 단순 메모리 리스트보다 안전합니다.
        collected_goods_nos = sorted({
            goods_no
            for goods_nos in completed_categories.values()
            for goods_no in goods_nos
        })
        # 한국어 주석: 594개 전체 카테고리 집합이 정확히 완료된 뒤에만 Vercel
        # 운영 백엔드의 단종 동기화 API를 호출합니다. 일부 수집 결과로 ACTIVE
        # 상품을 잘못 비활성화하는 상황을 위의 집합 일치 검사로 차단합니다.
        await self.finalize_crawl_to_backend(collected_goods_nos)
        return results

    async def finalize_crawl_to_backend(self, goods_nos: List[str]) -> None:
        """전체 수집 스냅샷을 Vercel 백엔드로 보내 누락 상품을 단종 처리합니다."""
        if not goods_nos:
            raise RuntimeError("수집 상품 목록이 비어 있어 단종 동기화를 중단했습니다.")

        url = f"{self.BACKEND_URL}/crawler/finalize"
        async with httpx.AsyncClient() as client:
            for retry_count in range(self.INGEST_MAX_RETRIES + 1):
                response = None
                try:
                    response = await client.post(
                        url,
                        json={"goodsNos": goods_nos},
                        timeout=60.0,
                    )
                    response.raise_for_status()
                    log.info("crawl_finalize_success", goods_count=len(goods_nos))
                    return
                except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                    retryable = True
                    error = exc
                except httpx.HTTPStatusError as exc:
                    retryable = exc.response.status_code in (502, 504)
                    error = exc
                except Exception as exc:
                    retryable = False
                    error = exc

                if not retryable or retry_count == self.INGEST_MAX_RETRIES:
                    response_text = response.text[:1000] if response is not None else None
                    log.critical(
                        "crawl_finalize_failed",
                        retry_count=retry_count,
                        error=str(error),
                        response=response_text,
                    )
                    raise RuntimeError("백엔드 단종 동기화 실패") from error

                await asyncio.sleep(2 ** retry_count)

    async def sync_category_tree_to_backend(self, nodes: List[Dict[str, Any]]):
        """카테고리 트리 데이터를 백엔드로 전송하여 동기화합니다."""
        url = f"{self.BACKEND_URL}/crawler/category-tree"
        log.info("sync_category_tree_to_backend", url=url, nodes_count=len(nodes))
        
        async with httpx.AsyncClient() as client:
            response = None
            try:
                response = await client.post(url, json={"categories": nodes}, timeout=30.0)
                response.raise_for_status()
            except Exception as e:
                response_text = response.text[:1000] if response is not None else None
                log.critical("sync_category_tree_failed", error=str(e), response=response_text)
                raise RuntimeError("카테고리 트리 동기화 실패") from e

        log.info("sync_category_tree_success", status=response.status_code)

    async def ingest_to_backend(self, results: List[Dict[str, Any]]):
        """상품을 50개씩 전송하며 일시적 장애만 제한적으로 재시도합니다."""
        url = f"{self.BACKEND_URL}/crawler/ingest"
        log.info("ingesting_to_backend", url=url, total_categories_crawled=len(results))
        
        success_count = 0
        
        async with httpx.AsyncClient() as client:
            for result in results:
                items = result.get("items", [])
                chunks = [
                    items[offset:offset + self.INGEST_CHUNK_SIZE]
                    for offset in range(0, len(items), self.INGEST_CHUNK_SIZE)
                ] or [[]]

                for chunk_index, chunk in enumerate(chunks, start=1):
                    chunk_result = {**result, "items": chunk}
                    for retry_count in range(self.INGEST_MAX_RETRIES + 1):
                        response = None
                        try:
                            response = await client.post(
                                url,
                                json={"data": [chunk_result]},
                                timeout=60.0,
                            )
                            response.raise_for_status()
                            log.info(
                                "ingest_chunk_success",
                                category=result.get("category_path"),
                                chunk=chunk_index,
                                total_chunks=len(chunks),
                                item_count=len(chunk),
                                status=response.status_code,
                            )
                            break
                        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
                            retryable = True
                            error = exc
                        except httpx.HTTPStatusError as exc:
                            retryable = exc.response.status_code in (502, 504)
                            error = exc
                        except Exception as exc:
                            retryable = False
                            error = exc

                        if not retryable or retry_count == self.INGEST_MAX_RETRIES:
                            response_text = response.text[:1000] if response is not None else None
                            log.critical(
                                "ingest_chunk_failed",
                                category=result.get("category_path"),
                                chunk=chunk_index,
                                retry_count=retry_count,
                                error=str(error),
                                response=response_text,
                            )
                            raise RuntimeError(
                                f"백엔드 상품 인입 실패: {result.get('category_path')} "
                                f"chunk={chunk_index}/{len(chunks)}"
                            ) from error

                        delay_seconds = 2 ** retry_count
                        log.warning(
                            "retry_ingest_chunk",
                            category=result.get("category_path"),
                            chunk=chunk_index,
                            retry=retry_count + 1,
                            delay_seconds=delay_seconds,
                            error=str(error),
                        )
                        await asyncio.sleep(delay_seconds)

                    await asyncio.sleep(0.5)

                success_count += 1
                log.info("ingest_category_success", category=result.get("category_path"))
        
        log.info("ingest_complete", success=success_count, failed=0)

    async def peek_metadata(self) -> Dict[str, Any]:
        """peek_metadata: 임시 구현. 필요시 fetch_goods_list로 건수 반환"""
        # (기존 NestJS와의 호환성을 위해 유지. 현재 요구사항의 핵심은 아님)
        return {"140101": 50, "130101": 20}
