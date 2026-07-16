# Gogisise Crawler (FastAPI)

이 리포지토리는 금천미트 통합 데이터 크롤링 및 분석 시스템을 위해 기존 NestJS(Backend) 종속 아키텍처에서 독립된 FastAPI 마이크로서비스입니다.

## 아키텍처 특징

- **FastAPI 분리**: 메인 백엔드의 배포와 런타임 종속성을 끊어내어 확장성 및 장애 격리(Fault Isolation) 달성.
- **Service Layer 분리**: 라우터와 비즈니스 로직(스크래퍼)을 완전히 분리하여 유지보수성을 극대화.
- **조기 필터링 및 통계**: 월령 제한(40개월 미만), 등급 제한(1등급 이상) 등 불필요한 데이터를 백엔드 인제스트 이전에 미리 걷어내어 네트워크 트래픽과 DB 용량 낭비를 방지.
- **비동기 처리 (Redis Stream)**: 백엔드의 작업 요청(Peek, Crawl)을 Redis Stream에 적재 후 Worker에서 비동기 수신.
- **Push 방식의 Ingest 연동**: 크롤링된 결과물을 직접 NestJS 엔드포인트(`POST /crawler/ingest`)로 밀어넣어 완전한 데이터 파이프라인 형성.

## 실행 방법

로컬 실행 및 의존성 설치:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

도커(Docker Compose) 환경 실행은 인프라 저장소의 설정을 따릅니다.
