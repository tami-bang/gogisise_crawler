# 금천미트 크롤링 안정성 명세

- 상태: 구현 계약(코드와 함께 변경)
- 최종 수정: 2026-07-15
- 코드 계약: `models.py`
- 원천 수집: `scraper.py`
- 실행·전송: `main.py`
- 수신 계약: `gogisise_BE/src/modules/internal/dto/create-raw-record.dto.ts`

“절대 장애가 나지 않음”이 아니라 **장애가 전파되지 않고, 손실·중복·원인을
관측할 수 있음**을 안정성의 정의로 삼는다. 원천 API 계약이 바뀌면 잘못된
데이터를 추측해 저장하지 않고 해당 레코드 또는 범위를 격리한다.

## 1. 파이프라인과 소유권

```text
금천미트 API
  -> 응답 구조 확인
  -> 필드 정규화
  -> Pydantic 계약 검증
  -> 실행 세션 내 중복 제거
  -> 100건 이하 배치
  -> NestJS DTO 재검증
  -> PostgreSQL 멱등 저장
```

| 경계 | 책임 | 실패 시 동작 |
|---|---|---|
| 원천 API | 카테고리·상품 원문 제공 | 일시 장애만 3회 재시도 |
| `scraper.py` | 타입 정규화와 레코드 격리 | 잘못된 상품 1건만 skip |
| `models.py` | 전송 가능한 값의 최종 계약 | 미정의·범위 밖 값 거부 |
| `main.py` | 단일 실행, 배치, BE 전송 | 0건이면 전송 금지 |
| NestJS DTO | 외부 입력 독립 재검증 | 요청 전체를 400으로 거부 |
| PostgreSQL | 동일 payload 재전송 멱등성 | 고유키 충돌은 skip |

## 2. 불변 조건

저장되는 모든 레코드는 다음 조건을 만족해야 한다.

1. `sourceName`은 정확히 `GEUMCHEON`이다.
2. `collectedAt`은 timezone이 포함된 ISO 8601이며 offset은 `+09:00`이다.
3. `rawProductName`은 공백 제거 후 1~500자이다.
4. `price`는 문자열이 아닌 1 이상의 정수이다.
5. `species`는 `BEEF | PORK`, `storageType`은 `CHILLED | FROZEN`이다.
6. `ageInMonths`는 null 또는 1~240의 정수이며 PORK일 때 반드시 null이다.
7. 선언되지 않은 필드는 허용하지 않는다.
8. 한 번의 BE 요청은 1~100건이다.

원천값 변환은 검증 전에만 허용한다. 가격의 쉼표 제거와 `int()` 변환,
공백 제거, 코드 매핑 외의 추론은 금지한다.

## 3. 실패 및 재시도 결정표

| 실패 | 재시도 | 최종 처리 |
|---|---:|---|
| timeout, DNS/연결 실패 | 최대 3회 시도 | 해당 카테고리 실패 기록 후 다음 범위 진행 |
| HTTP 429 | 최대 3회 시도 | 위와 동일 |
| HTTP 5xx | 최대 3회 시도 | 위와 동일 |
| HTTP 4xx(429 제외) | 없음 | 계약/인증 오류로 즉시 실패 |
| JSON 파싱 실패 | 최대 3회 시도 | 원문 구조 장애로 실패 기록 |
| 상품 필드 검증 실패 | 없음 | 상품 1건 skip + WARN |
| BE timeout/429/5xx | 최대 3회 시도 | 실행 상태 `FAILED`, 동일 payload 재실행 가능 |
| BE 4xx | 없음 | 계약 오류로 즉시 `FAILED` |
| 유효 레코드 0건 | 없음 | BE 전송 금지, 실행 `FAILED` |

재시도 대기 간격은 1초, 3초이며 원천 API 요청 사이에는 페이지 0.3초,
카테고리 0.5초의 간격을 둔다.

## 4. 중복과 멱등성

- 수집 세션 안에서는 `(rawProductName, price, species)`가 같은 응답을 한 건으로 만든다.
- 전달 중 응답 유실로 같은 payload를 다시 보내도 DB의
  `uk_raw_records_ingestion` 고유키가 중복 삽입을 막는다.
- 고유키 구성은 `(sourceName, collectedAt, rawProductName, price, species,
  storageType)`이다. 다른 수집 시각의 동일 상품은 시계열 원본이므로 새 행이다.
- 기존 DB에는 `gogisise_DB/migrations/20260715_raw_record_idempotency.sql`을
  한 번 적용해야 한다. 기존 중복이 있으면 마이그레이션은 일부 데이터를
  임의 삭제하지 않고 실패해야 한다.

## 5. 실행 상태 기계

```text
IDLE/SUCCESS/FAILED -> RUNNING -> SUCCESS
                           `----> FAILED
```

- `RUNNING` 중 새 실행 요청은 HTTP 409로 거부한다.
- 성공은 “수집 성공”이 아니라 모든 배치가 BE의 성공 응답을 받은 상태다.
- 실패 시 `last_error`, 마지막 수집 수, 마지막 삽입 수를 상태 API에 남긴다.
- 프로세스 재시작 시 메모리 상태는 사라진다. 다중 인스턴스 운영 전에는
  Redis/DB 분산 잠금과 영속 실행 이력 테이블이 추가되어야 한다.

## 6. 배포 차단 테스트

다음 항목이 통과하지 않으면 배포하지 않는다.

1. `python -m unittest discover -s tests -v`
2. `npm run build`
3. mock endpoint를 통한 Crawler -> NestJS -> DB E2E
4. 같은 mock payload를 두 번 보내 두 번째 `insertedCount`가 0인지 확인
5. timeout, 429, 500, 400, 잘못된 JSON에 대한 장애 주입 테스트
6. 실제 API 샘플의 필드 목록을 이전 실행과 비교하는 schema-drift 테스트

## 7. 운영 중단 기준

다음 중 하나면 자동 저장을 중단하고 조사한다.

- 전체 유효 레코드가 0건
- skip 비율이 20%를 초과
- 직전 정상 실행 대비 수집량이 50% 이상 급감
- 알 수 없는 축종/보관 코드가 등장
- BE가 4xx로 계약을 거부

현재 구현은 0건 중단을 강제한다. 나머지 비율 경보와 외부 알림 채널은 후속
운영 기능이며, 구현 전까지 로그와 `/api/v1/crawler/status`를 점검한다.
