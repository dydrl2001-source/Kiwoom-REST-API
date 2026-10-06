# Market Review Bridge

## Goal

Railway 로그인/프로젝트 인증이 없어도 장마감 복기 데이터를 읽을 수 있도록
실시간 실행계층과 복기계층을 분리한다.

```
Railway runtime/Postgres
  ├─ existing collectors / Market OS / Telegram
  ├─ market-review-journal   (issued decisions only, append-only)
  └─ review-bridge           (SELECT only)
            │ HTTPS + dedicated token
            ▼
GitHub Action 15:50 KST
            │
            ▼
PRIVATE review archive repository
  sessions/YYYY/MM/YYYY-MM-DD/eod.json
            │
            ▼
ChatGPT/GitHub read
```

이 저장소 `dydrl2001-source/Kiwoom-REST-API`는 public이므로 review JSON을
이 저장소에 저장하지 않는다. Telegram 원문, 후보, 진입/손절 계획은 반드시 별도
**private repository**에 보관한다.

## Safety boundary

`review-bridge`:

- DB 연결은 `default_transaction_read_only=on`.
- GET endpoint만 제공한다.
- broker/order endpoint가 없다.
- 계좌 식별자를 export하지 않는다.
- EOD 분석 결과를 Postgres에 쓰지 않는다.
- `DASHBOARD_TOKEN`과 별도인 `REVIEW_BRIDGE_TOKEN`을 사용한다.
- original event-engine `[RADAR_SUMMARY]`가 저장돼 있지 않으면
  `UNAVAILABLE`이라고 반환한다.
- Telegram에서 다시 계산한 theme/ticker 집계는
  `RECONSTRUCTED_FROM_TELEGRAM_MESSAGES`로 명확히 구분한다.

## Endpoints

```
GET /health
GET /review/latest
GET /review/session/YYYY-MM-DD
```

인증:

```
X-Review-Token: <REVIEW_BRIDGE_TOKEN>
```

`/health`는 데이터나 secret을 반환하지 않는다.

## Immutable decision journal

`market_review_decisions`는 end-of-day 해석이 아니라 **당시 발행된 판단**만 저장한다.

현재 자동 캡처:

- 08:20 KST `PREMARKET_0820`: Market OS FOCUS snapshot
- 09:20 KST `CHECKPOINT_0920`: Market OS FOCUS snapshot

이 자동 캡처는 `grade=A`를 만들지 않는다.
`FOCUS`와 A-grade는 다른 의미이므로 `MARKET_OS_FOCUS_SNAPSHOT`으로 보존한다.

실제 A-grade engine 또는 TRADE CARD generator가 연결되면 같은 journal helper를
사용해 원본 계획을 append한다.

예시:

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from market_review_journal import append_decision

append_decision({
    "issued_at": datetime.now(ZoneInfo("Asia/Seoul")),
    "stage": "TRADE_CARD",
    "source_kind": "A_GRADE_ENGINE",
    "stock_code": "005930",
    "stock_name": "삼성전자",
    "grade": "A",
    "watch_tier": "FOCUS",
    "setup_type": "LEADER_PULLBACK",
    "side": "LONG",
    "trigger_spec": {"kind": "ABOVE", "price": 100000},
    "exit_spec": {"kind": "STOP_OR_CLOSE"},
    "theoretical_entry_krw": 100200,
    "invalidation_stop_krw": 98200,
    "market_stance": "SELECTIVE",
    "catalyst_grade": "A",
    "rule_version": "example",
    "evidence": {"note": "example only"}
})
```

Bridge의 MFE/MAE 계산은 explicit LONG trigger/entry/stop이 모두 있을 때만 수행한다.
실제 system R은 여기에 원래 `exit_spec`까지 있어야 계산한다.
지원되는 초기 exit rule은 `STOP_OR_CLOSE`와 `TARGET_STOP_CLOSE`이며,
같은 1분봉에서 entry/stop 또는 stop/target 순서가 불명확하면 R을 추정하지 않는다.
조건이 없으면 `TRIGGER_SPEC_NOT_AUDITABLE` 또는
`TRIGGER_FIRED_STOP_NOT_AUDITABLE`로 남기고 추정하지 않는다.

## Railway deployment

새 서비스 2개를 같은 코드/DB로 배포한다.

### market-review-journal

Start command:

```
python /app/market_review_journal.py
```

필수:

```
DATABASE_URL=<same radar postgres>
MARKET_REVIEW_JOURNAL_POLL_SECONDS=15
```

### review-bridge

Start command:

```
python -m uvicorn market_review_bridge_app:app --host 0.0.0.0 --port $PORT
```

필수:

```
DATABASE_URL=<same radar postgres>
REVIEW_BRIDGE_TOKEN=<separate long random token>
```

Railway public domain은 **review-bridge service에만** 붙인다.
Postgres나 journal worker를 public network에 노출하지 않는다.

## Private archive setup

별도 private GitHub repository를 만든 후 이 public code repository의 Actions secrets에 설정:

- `REVIEW_BRIDGE_URL`: Railway review-bridge HTTPS base URL
- `REVIEW_BRIDGE_TOKEN`: bridge 전용 token
- `REVIEW_ARCHIVE_REPO`: `owner/private-repo`
- `REVIEW_ARCHIVE_TOKEN`: private archive repo에 contents write 권한만 가진 fine-grained token

`.github/workflows/archive-market-review.yml`은 평일 **15:50 KST**에 실행된다.
동일 session의 `eod.json`이 이미 있으면 덮어쓰지 않는다.

## Source family

기본적으로 이름에 `급등일보`가 들어간 sibling channel은 하나의
`급등일보` family로 접는다.

추가 family는 env JSON으로 확장할 수 있다.

```
REVIEW_SOURCE_FAMILY_ALIASES_JSON={"family-a":["channel-a","channel-b"]}
```

## Known limitation

현재 저장소에서 event-engine의 `[RADAR_SUMMARY]` 로그를 DB로 persist하는 writer는
확인되지 않았다. 그래서 bridge는 다음 table 중 하나가 존재할 때만 이를 원본으로 읽는다.

- `event_engine_radar_summaries(summary_time,payload)`
- `radar_summary_snapshots(summary_time,payload)`
- `telegram_radar_summaries(summary_time,payload)`

없으면 원본 상태를 `UNAVAILABLE`로 표시하고 Telegram 원문 기반 재구성치를 별도 제공한다.
event-engine 쪽에 summary sink가 연결되면 bridge 코드는 그대로 원본을 우선 사용한다.
