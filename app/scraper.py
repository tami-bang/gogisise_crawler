"""
scraper.py - 금천미트 API 기반 크롤러 (안정성 완전 구현)
==========================================================
CRAWLER_SPEC.md 5가지 안정성 규칙 구현:
  [Rule 1] API 장애  : 3회 재시도 + 지수 백오프 + ERROR 로그
  [Rule 2] 속도 제한 : 카테고리 간 0.5초, 페이지 간 0.3초 sleep
  [Rule 3] 데이터 결함: Pydantic 검증 실패 → skip + WARN 로그
  [Rule 4] 중복 처리 : 크롤러 미담당, BE DB에 완전 위임
  [Rule 5] 인코딩/타입: int() 강제, ISO 8601 고정, 빈 문자열 → None
"""

import json
import logging
import ssl
import time
import datetime
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# [로컬 환경] SSL 인증서 검증 우회 컨텍스트 (금천 API 서버 인증서 문제 대응)
# 🔑 비유: 신분증 확인을 잠시 건너뛰는 것 - 개발 환경에서만 사용!
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

from pydantic import ValidationError

from models import CrawlResult, RawRecord, ScrapeOutcome

# ────────────────────────────────────────────────────────────
# 로거 설정
# ────────────────────────────────────────────────────────────

logger = logging.getLogger("crawler.scraper")


# ────────────────────────────────────────────────────────────
# 상수 정의
# ────────────────────────────────────────────────────────────

BASE_URL = "https://gw.ekcm.co.kr"
SOURCE_NAME = "GEUMCHEON"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json",
    "Referer": "https://www.ekcm.co.kr/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# [Rule 1] 재시도 설정
MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 3.0]  # 최대 3회 시도 사이의 대기 (초)

# [Rule 2] 속도 제한 설정
SLEEP_BETWEEN_CATEGORIES = 0.5  # 카테고리 간 대기 (초)
SLEEP_BETWEEN_PAGES = 0.3       # 페이지 간 대기 (초)

# 축종 매핑 (API lsspeNm → INTERNAL_RAW_SPEC)
SPECIES_MAP = {
    "한우": "BEEF",
    "육우": "BEEF",
    "한돈": "PORK",
}

# 보관방법 코드 매핑 (API strgMthdGbCd → INTERNAL_RAW_SPEC)
STORAGE_MAP = {
    "1": "CHILLED",
    "2": "FROZEN",
}

# 등급명 정규화 (API lsprdGrdNm → 표준)
GRADE_NORMALIZE = {
    "1++": "1++",
    "1+":  "1+",
    "1":   "1",
    "2":   "2",
    "3":   "3",
    "등외": "등외",
    "A":   "1++",
    "B":   "1+",
    "C":   "1",
    "D":   "2",
    "E":   "3",
}


# ────────────────────────────────────────────────────────────
# [Rule 1] API 호출 유틸 - 재시도 + 지수 백오프
# ────────────────────────────────────────────────────────────

def _is_retryable_http_error(error: urllib.error.HTTPError) -> bool:
    """Retry throttling and server failures, never permanent client errors."""
    return error.code == 429 or 500 <= error.code < 600


def _http_get(url: str, timeout: int = 15) -> Any:
    """
    GET 요청. 실패 시 MAX_RETRIES회 재시도.
    모든 시도 실패 시 RuntimeError 발생.
    """
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers=HEADERS, method="GET")
            # SSL 우회 컨텍스트 적용
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as res:
                return json.loads(res.read().decode("utf-8"))

        except urllib.error.HTTPError as e:
            if not _is_retryable_http_error(e):
                raise RuntimeError(f"GET 요청 거부: {url} (HTTP {e.code})") from e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "[Rule1] GET transient failure (%d/%d) URL=%s error=%s; retry in %gs",
                    attempt + 1, MAX_RETRIES, url, e, delay,
                )
                time.sleep(delay)
            else:
                raise RuntimeError(f"GET 요청 실패: {url} ({e})") from e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "[Rule1] GET 요청 실패 (시도 %d/%d) URL=%s 오류=%s → %g초 후 재시도",
                    attempt + 1, MAX_RETRIES, url, e, delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "[Rule1] GET 요청 최종 실패 (3회 모두 실패) URL=%s 오류=%s",
                    url, e,
                )
                raise RuntimeError(f"GET 요청 실패: {url} ({e})") from e


def _http_post(url: str, payload: dict, timeout: int = 15) -> Any:
    """
    POST 요청. 실패 시 MAX_RETRIES회 재시도.
    모든 시도 실패 시 RuntimeError 발생.
    """
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, data=body, headers=HEADERS, method="POST")
            # SSL 우회 컨텍스트 적용
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as res:
                return json.loads(res.read().decode("utf-8"))

        except urllib.error.HTTPError as e:
            if not _is_retryable_http_error(e):
                raise RuntimeError(f"POST 요청 거부: {url} (HTTP {e.code})") from e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "[Rule1] POST transient failure (%d/%d) URL=%s error=%s; retry in %gs",
                    attempt + 1, MAX_RETRIES, url, e, delay,
                )
                time.sleep(delay)
            else:
                raise RuntimeError(f"POST 요청 실패: {url} ({e})") from e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "[Rule1] POST 요청 실패 (시도 %d/%d) URL=%s 오류=%s → %g초 후 재시도",
                    attempt + 1, MAX_RETRIES, url, e, delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "[Rule1] POST 요청 최종 실패 (3회 모두 실패) URL=%s 오류=%s",
                    url, e,
                )
                raise RuntimeError(f"POST 요청 실패: {url} ({e})") from e


# ────────────────────────────────────────────────────────────
# 금천미트 API 메서드
# ────────────────────────────────────────────────────────────

def fetch_category_tree() -> List[Dict[str, Any]]:
    """
    전체 카테고리 계층 구조를 트리 노드 리스트 형태로 반환
    GET /api/display/v1/displayCategory/getDispCtgList
    """
    url = f"{BASE_URL}/api/display/v1/displayCategory/getDispCtgList?shopInfwYn=Y"
    resp = _http_get(url)

    nodes = []

    # 현재 금천미트 API는 전체 노드를 평면 배열로 반환한다.
    if isinstance(resp, list):
        for item in resp:
            no = item.get("dispCtgNo") or item.get("leafCtgNo") or item.get("ctgNo")
            name = item.get("dispCtgNm") or item.get("ctgNm") or ""
            path_str = item.get("pathNm") or name
            if not no or not name:
                continue

            nodes.append({
                "ctgNo": str(no),
                "name": name,
                "parentNo": item.get("uprDispCtgNo") or item.get("uprTopDispCtgNo"),
                "depth": int(item.get("depth") or 1),
                "path": path_str,
                "leafYn": item.get("leafYn"),
            })
        return nodes

    def _traverse(node: Any, parent_no: Optional[str] = None, depth: int = 1, current_path: str = "") -> None:
        if isinstance(node, dict):
            no = node.get("dispCtgNo") or node.get("leafCtgNo") or node.get("ctgNo")
            name = node.get("dispCtgNm") or node.get("ctgNm") or ""
            
            if not no or not name:
                return

            ctg_no_str = str(no)
            path_str = f"{current_path} > {name}" if current_path else name

            # 14 (한우 암소), 31 (돈육), 13 (한우 거세)만 하위 트리 포함
            # 탑 레벨은 10 (국내산 한우), 30 (국내산 돈육)
            if depth == 1:
                if ctg_no_str not in ["10", "30"]:
                    return
            elif depth == 2:
                if ctg_no_str not in ["13", "14", "31"]:
                    return

            nodes.append({
                "ctgNo": ctg_no_str,
                "name": name,
                "parentNo": parent_no,
                "depth": depth,
                "path": path_str
            })

            children = node.get("childList") or node.get("children") or []
            if children:
                for child in children:
                    _traverse(child, ctg_no_str, depth + 1, path_str)
        elif isinstance(node, list):
            for item in node:
                _traverse(item, parent_no, depth, current_path)

    _traverse(resp)
    return nodes


def fetch_categories() -> List[str]:
    """
    전체 카테고리 번호(dispCtgNo) 목록 반환
    GET /api/display/v1/displayCategory/getDispCtgList
    """
    url = f"{BASE_URL}/api/display/v1/displayCategory/getDispCtgList?shopInfwYn=Y"
    resp = _http_get(url)

    ctg_nos = []

    def _extract(node: Any) -> None:
        if isinstance(node, dict):
            no = node.get("dispCtgNo") or node.get("leafCtgNo") or node.get("ctgNo")
            children = node.get("childList") or node.get("children") or []
            if children:
                for child in children:
                    _extract(child)
            elif no:
                # 자식이 없는 말단 카테고리만 수집
                ctg_nos.append(str(no))
        elif isinstance(node, list):
            for item in node:
                _extract(item)

    _extract(resp)

    if not ctg_nos:
        logger.warning("카테고리 목록이 비어있습니다. 알려진 카테고리로 폴백합니다.")
        # 알려진 카테고리 번호 폴백
        ctg_nos = ["140101", "140201", "310101", "310201"]

    # [USER REQUEST] "국내산 한우 암소" (14) 및 "국내산 돈육" (31) 카테고리만 수집하여 속도 최적화
    filtered_ctg_nos = [c for c in ctg_nos if c.startswith("14") or c.startswith("31")]
    if filtered_ctg_nos:
        ctg_nos = filtered_ctg_nos

    logger.info("카테고리 %d개 로드 완료: %s", len(ctg_nos), ctg_nos[:5])
    return list(dict.fromkeys(ctg_nos))


def fetch_goods_page(ctg_no: str, page: int = 1, page_size: int = 100) -> Tuple[List[Dict], bool]:
    """
    특정 카테고리 상품 목록 1페이지 반환
    → (items 리스트, 다음 페이지 존재 여부)
    POST /api/goods/v1/goods/dispGoodsList
    """
    url = f"{BASE_URL}/api/goods/v1/goods/dispGoodsList"
    payload = {
        "dispCtgNoList": [ctg_no],
        "brandNoList": [], "lsprdGrdCdList": [], "homeCdList": [],
        "ppYmdList": [], "strgMthdGbCdList": [], "workMethTypCdList": [],
        "deliProcTypCdList": [], "recomBkindList": [], "qualityList": [],
        "insfatGrdList": [], "mffldList": [], "estNoList": [],
        "sortTpCd": "10",
        "pageNo": page,
        "pageSize": page_size,
        "aplyPsbMediaCd": "01",
        "curCtgNo": ctg_no,
        "noDispCtgRegYn": "N",
        "mbrNo": "",
    }
    resp = _http_post(url, payload)
    if not isinstance(resp, dict):
        raise RuntimeError("상품 API 응답이 JSON object가 아닙니다.")
    payload_data = resp.get("payload", [])
    if isinstance(payload_data, dict):
        items = (
            payload_data.get("list")
            or payload_data.get("items")
            or payload_data.get("goodsList")
            or []
        )
    else:
        items = payload_data
    if not isinstance(items, list):
        raise RuntimeError("상품 API payload가 list가 아닙니다.")
    has_more = len(items) >= page_size
    return items, has_more


# ────────────────────────────────────────────────────────────
# [Rule 5] 타입 변환 헬퍼
# ────────────────────────────────────────────────────────────

def _to_str_or_none(val: Any) -> Optional[str]:
    """빈 문자열 → None 정규화"""
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _parse_species(lsspe_nm: Optional[str]) -> Optional[str]:
    """축종명 → BEEF / PORK. 매핑 실패 시 None"""
    if not lsspe_nm:
        return None
    for key, val in SPECIES_MAP.items():
        if key in lsspe_nm:
            return val
    return None


def _parse_storage(code: Optional[str]) -> Optional[str]:
    """보관방법 코드 → CHILLED / FROZEN. 매핑 실패 시 None"""
    if code is None:
        return None
    return STORAGE_MAP.get(str(code).strip())


def _parse_grade(nm: Optional[str]) -> Optional[str]:
    """등급명 정규화. 알 수 없는 값은 원문 반환, 빈 값은 None"""
    if not nm:
        return None
    stripped = nm.strip()
    return GRADE_NORMALIZE.get(stripped, stripped if stripped else None)


def _parse_age(mage: Any, species: Optional[str]) -> Optional[int]:
    """
    [Rule 5] 월령 파싱
    - BEEF만 int() 변환 시도
    - PORK는 None 고정
    - "0" 또는 변환 불가 → None (skip 아님, None 허용)
    """
    if species != "BEEF":
        return None
    if mage is None:
        return None
    try:
        val = int(mage)
        return val if val > 0 else None
    except (ValueError, TypeError):
        return None


def _build_collected_at() -> datetime.datetime:
    """[Rule 5] 크롤링 시각 KST ISO 8601"""
    kst = datetime.timezone(datetime.timedelta(hours=9))
    return datetime.datetime.now(tz=kst)


# ────────────────────────────────────────────────────────────
# [Rule 3] Pydantic 검증 통합 매핑 및 하드 룰 적용
# ────────────────────────────────────────────────────────────
import re

HONDON_CHILLED = ['더좋은삼겹', '더좋은미박삼겹', 'A원삼겹', '두판삼겹', '삼겹', '미박삼겹', '목심', '미박목심', '앞다리', '미박앞다리', '뒷다리', '미박뒷다리', '등심', '지방등심', '안심', '갈비', '등갈비', '항정', '등심덧살', '갈매기', '사태']
HANWOO_COW_CHILLED = ['안심', '등심', '윗등심', '채끝', '아래등심', '목심', '앞다리살(앞다리+꼬리)', '앞다리살', '꾸리살', '부채살', '우둔(홍두깨포함)', '우둔살', '홍두깨', '설도(삼각살 X)', '설도', '설깃', '양지머리,치마양지', '양지머리', '외삼각살', '차돌양지', '치마살', '차돌박이', '업진살', '앞치마살,업진안살', '앞치마살', '업진안살', '사태', '갈비', '갈비살', '안창살', '갈비본살+갈비살', '치토시살', '토시,제비추리', '늑간살', '제비추리']

HONDON_CHILLED.sort(key=len, reverse=True)
HANWOO_COW_CHILLED.sort(key=len, reverse=True)

def map_item_to_record(item: Dict, collected_at: datetime.datetime) -> Optional[RawRecord]:
    """
    API 응답 아이템 1건 → RawRecord 변환 + Pydantic 검증
    """
    raw_name = _to_str_or_none(item.get("artcNm") or item.get("goodsNm")) or ""
    species  = _parse_species(item.get("lsspeNm"))
    storage  = _parse_storage(item.get("strgMthdGbCd"))
    age      = _parse_age(item.get("mage"), species)

    # [Rule B] 월령 40개월 이상 스킵
    if age is not None and age >= 40:
        return None

    # [Rule A] kg당 단가 (realUcost 우선, 없으면 salePrc)
    price_raw = item.get("realUcost") or item.get("salePrc")
    try:
        normalized_price = str(price_raw).replace(",", "").strip()
        price_per_kg = int(normalized_price) if normalized_price else None
    except (ValueError, TypeError):
        price_per_kg = None
    if not price_per_kg:
        return None

    # [Rule C] 등급 분리 및 필터링
    grade_str = str(item.get("lsprdGrdNm") or "").strip()
    quality = None
    yield_g = None
    
    if species == "BEEF":
        q_match = re.search(r'(1\+\+|1\+|1)', grade_str)
        y_match = re.search(r'([A-C])', grade_str, re.IGNORECASE)
        if q_match:
            quality = q_match.group(1)
        if y_match:
            yield_g = y_match.group(1).upper()
            
        if not quality:
            return None  # 1++, 1+, 1 아니면 버림
        if yield_g == "C":
            return None  # C등급 버림
    else:
        q_match = re.search(r'(1\+\+|1\+|1)', grade_str)
        if q_match:
            quality = q_match.group(1)

    # 성별 (한우는 암소 고정, 아니면 None)
    gender = "암소" if species == "BEEF" else None

    # 카테고리 매핑 (가장 긴 단어부터 매칭)
    category = "기타"
    if species == "BEEF":
        for c in HANWOO_COW_CHILLED:
            if c in raw_name:
                category = c
                break
    elif species == "PORK":
        for c in HONDON_CHILLED:
            if c in raw_name:
                category = c
                break

    # 브랜드명 추출 ( [브랜드] 형태 또는 띄어쓰기/슬래시 이전의 첫 단어)
    brand = "기타브랜드"
    b_match = re.search(r'\[(.*?)\]', raw_name)
    if b_match:
        brand = b_match.group(1)
    else:
        parts = raw_name.split()
        if parts:
            brand = parts[0].split('/')[0]

    try:
        record = RawRecord(
            sourceName=SOURCE_NAME,
            collectedAt=collected_at,
            rawProductName=raw_name,
            species=species or "",
            gender=gender,
            storageType=storage or "",
            category=category,
            brand=brand,
            qualityGrade=quality,
            yieldGrade=yield_g if yield_g in ["A", "B"] else None,
            ageMonths=age,
            pricePerKg=price_per_kg,
        )
        return record

    except ValidationError as e:
        logger.warning("[Rule3] 레코드 skip - 상품명=%s 오류=%s", raw_name, e.errors()[0]["msg"])
        return None

# ────────────────────────────────────────────────────────────
# 메인 크롤러 클래스
# ────────────────────────────────────────────────────────────

class GeumcheonScraper:
    """
    금천미트 공식 API 기반 크롤러
    CRAWLER_SPEC.md 5가지 안정성 규칙 완전 구현
    """

    def __init__(self, page_size: int = 100):
        self.page_size = page_size

    def scrape_category(
        self, ctg_no: str, collected_at: datetime.datetime
    ) -> Tuple[List[RawRecord], int]:
        """
        단일 카테고리 전체 페이지 수집
        반환: (유효 레코드 리스트, skip된 수)
        """
        all_records: List[RawRecord] = []
        skipped = 0
        page = 1

        while True:
            try:
                items, has_more = fetch_goods_page(ctg_no, page=page, page_size=self.page_size)
            except RuntimeError as e:
                # [Rule 1] 3회 모두 실패 → 해당 카테고리 skip
                logger.error("[Rule1] 카테고리 %s 페이지 %d 수집 포기: %s", ctg_no, page, e)
                break

            for item in items:
                record = map_item_to_record(item, collected_at)
                if record:
                    all_records.append(record)
                else:
                    skipped += 1

            if not has_more:
                break

            page += 1
            # [Rule 2] 페이지 간 속도 제한
            time.sleep(SLEEP_BETWEEN_PAGES)

        logger.info(
            "카테고리 %s: 유효 %d건, skip %d건 (총 %d페이지)",
            ctg_no, len(all_records), skipped, page,
        )
        return all_records, skipped

    def scrape_all(self) -> ScrapeOutcome:
        """
        전체 카테고리 수집 → CrawlResult 반환
        [Rule 4] 중복 처리는 BE에 완전 위임 (크롤러는 신경 안 씀)
        """
        collected_at = _build_collected_at()
        total_fetched = 0
        total_skipped = 0
        all_records: List[RawRecord] = []
        errors: List[str] = []

        # 카테고리 목록 조회
        try:
            ctg_nos = fetch_categories()
        except RuntimeError as e:
            logger.critical("[Rule1] 카테고리 목록 조회 실패: %s", e)
            errors.append(str(e))
            ctg_nos = ["130101", "130201", "130301", "130401"]

        for idx, ctg_no in enumerate(ctg_nos):
            logger.info("[%d/%d] 카테고리 %s 수집 시작...", idx + 1, len(ctg_nos), ctg_no)

            try:
                records, skipped = self.scrape_category(ctg_no, collected_at)
                total_fetched += len(records) + skipped
                total_skipped += skipped
                all_records.extend(records)
            except Exception as e:
                msg = f"카테고리 {ctg_no} 예외: {e}"
                logger.error("[Rule1] %s", msg)
                errors.append(msg)

            # [Rule 2] 카테고리 간 속도 제한
            if idx < len(ctg_nos) - 1:
                time.sleep(SLEEP_BETWEEN_CATEGORIES)

        # 세션 내 중복 제거 (동일 카테고리 중복 등록 방지)
        seen: set = set()
        unique_records: List[RawRecord] = []
        for r in all_records:
            key = (r.rawProductName, r.pricePerKg, r.species)  # pricePerKg로 변경
            if key not in seen:
                seen.add(key)
                unique_records.append(r)

        dedup_removed = len(all_records) - len(unique_records)
        if dedup_removed:
            logger.info("세션 내 중복 제거: %d건 제거", dedup_removed)

        logger.info(
            "수집 완료 - 전체 %d건 / 유효 %d건 / skip %d건 / 오류 %d건",
            total_fetched, len(unique_records), total_skipped, len(errors),
        )

        return ScrapeOutcome(
            records=unique_records,
            result=CrawlResult(
                totalFetched=total_fetched,
                validRecords=len(unique_records),
                skippedRecords=total_skipped,
                errors=errors,
            ),
        )

    def scrape_single_category(self, ctg_no: str = "130101") -> Tuple[List[RawRecord], int]:
        """테스트용: 단일 카테고리 1페이지"""
        collected_at = _build_collected_at()
        try:
            items, _ = fetch_goods_page(ctg_no, page=1, page_size=10)
        except RuntimeError as e:
            logger.error("테스트 수집 실패: %s", e)
            return [], 0

        records, skipped = [], 0
        for item in items:
            rec = map_item_to_record(item, collected_at)
            if rec:
                records.append(rec)
            else:
                skipped += 1
    def peek_latest_metadata(self) -> Dict[str, int]:
        """
        [Rule 6] 하이브리드 트리거용 변경 탐지 (Change Detection)
        전체 카테고리의 총 상품 개수(totalCount)를 가져와 딕셔너리로 반환.
        예: {'130101': 150, '130201': 45, ...}
        """
        try:
            # 카테고리 목록부터 가져오기 (이미 fetch_categories 존재)
            ctg_nos = fetch_categories()
        except Exception as e:
            logger.error("카테고리 조회 실패: %s", e)
            return {}

        counts = {}
        for ctg_no in ctg_nos:
            try:
                # pageSize=1로 호출해서 첫 페이지만 빠르게 가져옴
                url = f"{BASE_URL}/api/goods/v1/goods/dispGoodsList"
                payload = {
                    "dispCtgNoList": [ctg_no],
                    "sortTpCd": "10",
                    "pageNo": 1,
                    "pageSize": 1,
                    "curCtgNo": ctg_no,
                    "noDispCtgRegYn": "N",
                    "mbrNo": "",
                }
                resp = _http_post(url, payload)
                if isinstance(resp, dict):
                    payload_data = resp.get("payload", {})
                    # API 구조상 payload 안에 totCnt가 있거나, 첫 아이템 안에 totCnt가 있을 수 있음
                    tot_cnt = payload_data.get("totCnt")
                    if tot_cnt is None:
                        # 아이템에서 찾아봄
                        items = (
                            payload_data.get("list")
                            or payload_data.get("items")
                            or payload_data.get("goodsList")
                            or []
                        )
                        if isinstance(items, list) and items:
                            tot_cnt = items[0].get("totCnt", 0)
                        else:
                            tot_cnt = 0
                    
                    counts[ctg_no] = int(tot_cnt) if tot_cnt is not None else 0
            except Exception as e:
                logger.warning("카테고리 %s 카운트 조회 실패: %s", ctg_no, e)
                counts[ctg_no] = 0

            # Rate Limit 적용 (안전하게 0.3초 대기)
            time.sleep(0.3)

        return counts


# ────────────────────────────────────────────────────────────
# 단독 실행 테스트
# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    scraper = GeumcheonScraper()
    print("\n--- 카테고리 130101 단일 테스트 ---")
    records, skipped = scraper.scrape_single_category("130101")
    print(f"수집: {len(records)}건, skip: {skipped}건\n")
    for r in records[:3]:
        print(json.dumps(r.model_dump(), ensure_ascii=False, indent=2))
