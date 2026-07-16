"""
금천미트 API 응답 구조 확인용 스크립트 v2 (인코딩 수정)
실행: python test_api.py
"""
import json
import urllib.request

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json",
    "Referer": "https://www.ekcm.co.kr/",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

def get_categories():
    url = "https://gw.ekcm.co.kr/api/display/v1/displayCategory/getDispCtgList?shopInfwYn=Y"
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    with urllib.request.urlopen(req, timeout=10) as res:
        raw = res.read()
        data = json.loads(raw.decode("utf-8"))
    return data

def get_goods(ctg_no: str, page: int = 1, page_size: int = 2):
    url = "https://gw.ekcm.co.kr/api/goods/v1/goods/dispGoodsList"
    payload = {
        "dispCtgNoList": [ctg_no],
        "brandNoList": [], "lsprdGrdCdList": [], "homeCdList": [],
        "ppYmdList": [], "strgMthdGbCdList": [], "workMethTypCdList": [],
        "deliProcTypCdList": [], "recomBkindList": [], "qualityList": [],
        "insfatGrdList": [], "mffldList": [], "estNoList": [],
        "sortTpCd": "10", "pageNo": page, "pageSize": page_size,
        "aplyPsbMediaCd": "01", "curCtgNo": ctg_no,
        "noDispCtgRegYn": "N", "mbrNo": "",
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=10) as res:
        raw = res.read()
        data = json.loads(raw.decode("utf-8"))
    return data


if __name__ == "__main__":
    # ── STEP 1: 카테고리 목록 ──
    print("=" * 60)
    print("STEP 1: 카테고리 목록 (최상위만)")
    print("=" * 60)
    try:
        cats = get_categories()
        # 상위 구조 키만 먼저 출력
        print("최상위 키:", list(cats.keys()) if isinstance(cats, dict) else type(cats))
        if isinstance(cats, dict):
            for k, v in cats.items():
                if isinstance(v, list) and len(v) > 0:
                    print(f"\n[{k}] 리스트 첫 번째 항목:")
                    print(json.dumps(v[0], ensure_ascii=False, indent=2))
                    print(f"  → 총 {len(v)}개 항목")
                else:
                    print(f"[{k}]:", v)
    except Exception as e:
        print(f"[ERROR] {e}")

    print()

    # ── STEP 2: 카테고리 130101 상품 샘플 2건 ──
    print("=" * 60)
    print("STEP 2: 카테고리 130101 상품 샘플 2건")
    print("=" * 60)
    try:
        goods = get_goods("130101", page=1, page_size=2)
        print("최상위 키:", list(goods.keys()) if isinstance(goods, dict) else type(goods))
        if isinstance(goods, dict):
            for k, v in goods.items():
                if isinstance(v, list) and len(v) > 0:
                    print(f"\n[{k}] 리스트 첫 번째 항목 핵심 필드:")
                    item = v[0]
                    # 파싱에 필요한 핵심 필드만 출력
                    important_keys = [
                        "goodsNo", "goodsNm", "artcNm", "lsspeNm", "lsprdGrdNm",
                        "strgMthdGbCd", "strgMthdGbNm", "salePrc", "norPrc",
                        "mage", "lventSexGbNm", "plspartNm", "ppYmd",
                        "dispCtgNm", "leafCtgNo"
                    ]
                    for key in important_keys:
                        if key in item:
                            print(f"  {key}: {item[key]}")
                    print(f"\n  → 총 {len(v)}개 항목 수신")
                elif isinstance(v, (int, str, bool)):
                    print(f"[{k}]:", v)
    except Exception as e:
        print(f"[ERROR] {e}")
