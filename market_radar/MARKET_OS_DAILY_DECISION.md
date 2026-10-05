# Daily Decision + NAVER Verification + Execution Risk Gate

구현 기준: 2026-10-05, PR #3 `feature/market-os-live-v2`의 `b987a2b`.

## 데이터 흐름과 권한

```
Kiwoom 가격/체결 → 기존 Market OS 다축 rule shortlist
DART 공시 목록  → 출처가 표시된 catalyst evidence
                       ↓
             최대 5개 / compact JSON ≤ 24KB
                       ↓ 14:30 ≤ KST < 14:40
             날짜당 immutable Daily Decision Packet
                       ↓ 선택적 OpenAI 1 HTTP attempt/day
               참고 의견 / 불확실성 / 후보별 메모

NAVER 공식 검색 → 별도 사람 검증 화면 (뉴스 / 웹문서 / 블로그)
                검색결과 본문·제목·파생물은 AI/판단 DB로 전달하지 않음

기존 Execution Firewall → 추가 Execution Risk Gate → shadow/manual review
                                                    실제 주문 경로 없음
```

기존 Radar/Theme/Setup/Catalyst/Trigger/Risk 계산과 CONTROL 선택을 바꾸지 않는다.
AI 결과는 별도 `advice`에 저장하며 원래 후보/점수/위험 규칙에 다시 주입하지 않는다.
규칙 엔진, 후보 추적, 학습 worker는 AI/NAVER 서비스 장애와 독립적으로 동작한다.

## 추가 파일과 연결 지점

- `market_os_budget.py`: PostgreSQL 기반 전역 일일 예약·감사, 유일한 OpenAI HTTP 송신 경로.
- `market_os_naver.py`: 공식 API HUB/legacy 검색 어댑터, 사람 링크 생성, 결과 비저장.
- `market_os_packet.py`: 실제 `flow_store.desk_payload()` shortlist에서 최소 공개 필드만 채택.
- `market_os_risk.py`: 필수 데이터 누락도 차단하는 LONG 진입 검토 규칙.
- `market_os_daily.py`: 30초 간격 독립 worker. 지정 시간대 내 첫 유효 패킷만 생성.
- `market_os_routes.py`, `market_os_decision.html/js`: 기존 dashboard token 인증을 사용하는 조회·사람 검증 화면.
- `web_research_engine.call_model`: 기존 web/flow research도 동일 OpenAI budget을 사용.
- `market_os_learning.refresh_execution_intents`: 기존 firewall 통과 후에도 새 위험 규칙을 만족해야 intent 생성.
- `local/shadow_rule_admin.sh intent-review ... approve`: 현재 데이터로 재검사. 저장된 AI 의견으로 승인 우회 불가.

화면: 기존 Market OS 상단 **일일 판단 · 검증**, 직접 경로 `/market-os/decision`.

## OpenAI 비용 한도와 장애 처리

- 한도는 프로젝트 운영 정책이며 OpenAI 서비스의 상품별 한도가 아니다.
- KST 달력일당 `OPENAI` 예약 1건. 모델/기능/키 변경, 여러 컨테이너, 수동/자동 요청이 한도를 분리하지 않는다.
- DB의 `clock_timestamp()`가 날짜 기준이다. 요청자가 날짜를 지정할 수 없다.
- DB transaction/advisory lock으로 예약을 직렬화하고, 네트워크 송신 **전에 commit**한다.
- 429/401/timeout/잘못된 JSON/프로세스 종료도 예약을 반환하지 않는다. HTTP retry/redirect를 사용하지 않는다.
- 완료 기록 실패나 프로세스 종료 시 `RESERVED`가 남을 수 있다. 이는 사용 가능이 아니라 결과 불확실·한도 소진이다.
- 예약 DB 장애 시 외부 호출을 차단한다. 규칙 기반 패킷과 기존 엔진은 독립적이다.
- 감사 항목: KST 날짜, 시도/완료 시각, 호출 이유, 요청 모델, 응답 모델, request hash, 상태,
  input/output/total tokens, 응답 일부 요약(최대 1,200자), 고정 오류 코드.
- 제공자가 usage를 보내지 않은 실패는 토큰을 `null`로 보존한다. 0으로 비용을 단정하지 않는다.
- 신규 Daily AI는 tools 없음, output 최대 1,600 tokens, `store=false`. 계좌·인증값·Telegram 메시지는 전송하지 않는다.
- 기존 웹 리서치가 먼저 하루 한도를 쓰면 Daily Packet은 `RULES_ONLY`다. 패킷에 한도를 우선 배정하려면
  `WEB_RESEARCH_ENABLED=0`, `WEB_RESEARCH_AUTO=0`를 유지한다. 환경변수로 hard cap을 올릴 수 없다.
- 해당 DB를 공유하는 이 저장소의 generation 경로를 보호한다. 다른 앱/수동 API 호출이나 구버전 worker까지 제어하지는 않는다.

## 패킷 시각과 필드

`market_stance`, `leading_themes`, `candidates`(최대 5), `radar/theme/setup/catalyst/trigger/risk`,
거래대금·실제 구간초·rate ratio, 외국인/기관, DART 근거, NAVER 검증 링크, 실행 차단 이유를 담는다.
`generated_at`, `market_data_as_of`, 종목별 `price_as_of`, `collected_at`, regime 시각을 구분한다.

기존 rule/control 정렬을 그대로 사용하며 BLOCKED/중복 코드/90초 초과 또는 미래 시세 후보는 제외한다.
거래대금 순위를 외국인/기관 순매수로 해석하지 않는다. 현재 flow payload에 투자자 수급 공급이 없으므로
`foreign/institution.net_buy_krw=null`, `status=NOT_CONNECTED`로 표시한다.
공시 목록은 `LIST_ONLY_NOT_CAUSAL_PROOF`이며 본문 검증이나 상승 원인 확정을 의미하지 않는다.

주말은 제외한다. 평일 휴장일에 대해 캘린더를 추정하지 않고 현재 Kiwoom 체결·rule candidate가 없으면
패킷/AI 호출을 만들지 않는다. 이전 거래일 자료를 새 수집시각으로 포장해 사용하지 않는다.
거래일/계좌 확인은 **실행 위험 단계에서 별도 필수 사실**이다. 신선한 체결만으로 주문 가능일을 확정하지 않는다.
14:40 이후 재시작으로 놓친 호출을 보충하지 않는다. 이미 저장된 날짜는 장애 후에도 자동 재시도하지 않는다.

AI response는 `summary`, `uncertainties`, `candidate_notes[{code,note}]`만 허용한다.
주문/수량 등 추가 필드, 대상 외 종목, 중복 종목, 파싱 오류는 `INVALID_ADVICE → RULES_ONLY`.
자연어 참고 의견 자체를 주문 명령으로 파싱하지 않는다.

## NAVER 선택과 정책 경계

| API | 역할 | 채택 |
|---|---|---|
| 뉴스 검색 | Verification: 원문 링크·기사 시각을 사람이 대조 | 구현, 기본 OFF |
| 웹문서 검색 | Context: 기업 IR/공식 기관 자료 탐색 | 구현, 기본 OFF |
| 블로그 검색 | Discovery: 테마 표현·아이디어 탐색, 사실 근거로 승격 금지 | 구현, 기본 OFF |
| 검색어 트렌드/DataLab | 대중 관심도의 상대 지수. 매수자금·주가·체결 아님 | 조사만, 이번 미채택 |
| 카페/지식iN | 추가적인 사용자 게시물, 근거 중복과 신뢰도 한계 | 미채택 |
| 쇼핑/지역/이미지/책/백과·오타·성인 판별 | 이 시스템 판단에 실질적 효용 낮음 | 미채택 |
| NAVER 증권 웹 | 사람이 가격·뉴스·기업 정보를 교차 확인 | 링크만, 자동 크롤링 없음 |

2026-09-07 개정 개발자센터 약관 검색 특약 2.3은 결과의 AI 입력/학습/개선/평가/노출 활용을 금지한다.
따라서 요청의 `naver search context`는 **시스템 생성 query·검색 URL·증권 URL·결과 제외 사유**로 구현했다.
검색 API 결과나 그 요약/파생물을 AI prompt/패킷/학습 DB에 포함하지 않는다. 이 동작을 해제하는 env는 없다.
API HUB 계약의 세부 조건은 등록 화면에서 별도로 확인해야 하며, 본 구현은 AI 입력 허용을 가정하지 않는다.

검색 결과는 원래 순서와 원래 문자열을 별도 `네이버 검색결과` 영역에 제공하고 출처/원문 링크를 표시한다.
키는 서버 헤더에만 사용한다. 결과는 DB/로그/브라우저 저장소에 쓰지 않는다.
`Cache-Control: no-store`, 새 질의 또는 15분 후 화면 제거. 응답의 HTML은 실행하지 않고 텍스트로 표시한다.
검색은 사람 버튼의 POST 요청으로만 발생한다. 주기 polling·자동 기사 전문 수집·증권 페이지 크롤러는 없다.

### 인증·이관·쿼터

기본 `hub`: NCP 콘솔 → NAVER API HUB 신청 → Application에 필요한 검색 API 등록.
`X-NCP-APIGW-API-KEY-ID`, `X-NCP-APIGW-API-KEY`를 서버 환경변수에서 설정한다.
공식 HTTPS 주소: `https://naverapihub.apigw.ntruss.com/search/v1/{news|webkr|blog}`.
`format=json`, `display=5`, `start=1`, news/blog는 `sort=date`, webkr는 sort 미전송.

`legacy`: 2026-07-30 24:00까지 신청한 기존 개발자센터 이용자만 선택.
`X-Naver-Client-Id`, `X-Naver-Client-Secret`, `https://openapi.naver.com/v1/search/{kind}.json`.
신규 신청은 2026-07-31부터 API HUB로 이관. 기존 제공은 2027-06-30 24:00 종료,
코드도 2027-07-01 KST부터 legacy 호출을 차단한다. 임의 호스트/redirect는 허용하지 않는다.

공식 검색 레퍼런스는 25,000회/일, HUB Application 안내는 검색 775,000회/월 최대를 제시한다.
실제 계약·콘솔 한도가 우선이다. 무료·무제한으로 가정하지 않는다. 이용요금은 등록 화면에서 확인한다.
로컬 기본은 API 종류를 합쳐 **100회/KST일**, 최소 1초 간격, 실패도 계산, 자동 재시도 없음.
403은 권한/등록 확인, 429는 당일/당월·계약 한도 확인 후 기다린다. 호출수를 늘려 우회하지 않는다.
여러 앱이 같은 키를 공유하면 이 로컬 카운터 외 소비가 있으므로 콘솔 집계를 함께 확인한다.

공식 조사 근거(2026-10-05 열람):
- [NAVER 검색 약관](https://developers.naver.com/products/terms/)
- [이관 공지](https://developers.naver.com/notice/article/32973)
- [HUB 이관 가이드](https://guide.ncloud-docs.com/docs/apihub-migration)
- [HUB 인증/등록](https://api.ncloud-docs.com/docs/naver-api-hub-overview)
- [HUB Application 한도/사용량](https://guide.ncloud-docs.com/docs/apihub-application)
- [뉴스](https://api.ncloud-docs.com/docs/naver-api-hub-search-news)
- [웹문서](https://api.ncloud-docs.com/docs/naver-api-hub-search-webkr)
- [블로그](https://api.ncloud-docs.com/docs/naver-api-hub-search-blog)
- [기존 뉴스](https://developers.naver.com/docs/serviceapi/search/news/news.md)
- [DataLab 조사](https://developers.naver.com/docs/serviceapi/datalab/search/search.md)

## 실행 위험 규칙과 현재 한계

검토 대상은 LONG entry이며 기존 손실청산 경로의 설계가 아니다. 브로커 adapter가 없고 실제 주문을 전송하지 않는다.
모든 모드에서 `can_submit_order=false`; `live` 등 다른 모드 요청은 차단한다.
`shadow` 통과는 관찰용, `manual_confirm` 통과도 확인 필요 메타데이터일 뿐 주문 권한이 아니다.

기본 실험적 운영 기준(검증된 투자 공식 아님):
- price/account/session/duplicate/theme/turnover 각각 90초 이내, 미래 timestamp 불가.
- 확인된 거래일·장중 상태 및 09:05 ≤ KST < 15:20.
- 기준가 대비 추격 ≤ 1%, 현재가 대비 유효 손절폭 ≤ 3%.
- 일일 손실 < 2%(수수료·미실현을 포함하는 손실률 입력 계약; 순이익인 경우 0).
- 테마 유지 확인, 동일기간 기준 거래대금 속도 ratio ≥ 0.5.
- 중복주문 없음 명시 확인, data confidence 0.9–1, quality flags 없음.
- 기존 FOCUS/STRUCTURE_CONFIRMED, A/B catalyst, 허용 시장 stance, risk 없음.
- null/NaN/inf/bool 잘못된 숫자, 알 수 없는 상태는 통과시키지 않는다.

**현재 account/session/duplicate/stop/reference/theme 신뢰 사실 adapter는 연결되지 않았다.**
이를 AI나 가격만으로 추정하지 않으므로 현재 실제 후보의 실행 gate는 BLOCKED가 정상이다.
기존 Firewall intent 생성과 수동 승인에도 이 gate를 적용해 과거 승인 경로로 우회하지 않는다.
이 연결을 만들기 전까지 시스템은 관찰/검증용이다. AI가 성공해도 이 차단은 그대로다.

## 적용 및 검증 절차

이미 실행 중인 Mac 서비스, 실제 DB, 계좌, API 키는 이 작업에서 변경하지 않는다.
배포할 때는 새 이미지와 기존 유료 worker를 섞지 않는다:

1. `local/.env.example`의 새 설정을 기존 `.env`에 병합. 키를 Git에 커밋하지 않는다.
2. `docker compose stop web-research-worker flow-research-worker`로 기존 유료 worker 중지.
3. 전체 새 이미지를 build하고 업데이트한다. 초기 budget migration은 기존 `web_research_runs.attempted_at`의
   과거 예약도 일자별로 가져오므로 이미 사용한 날에 새 한도가 생기지 않는다.
4. `docker compose up -d radar-api market-os-learning market-os-daily`로 관찰 서비스 실행.
5. `/market-os/decision`에서 기존 dashboard token으로 현재 규칙 preview 확인(유료 호출 없음).
6. 필요 시 실제 등록한 NAVER 자격증명을 설정하고 `NAVER_SEARCH_ENABLED=1`로 사람 검색 확인.
7. 검증 후 `MARKET_OS_DAILY_AI_ENABLED=1`, 모델/키 설정. 설정 전환 자체가 즉시 AI를 부르지는 않지만,
   다음 유효 시간대에 1회의 유료 시도가 발생한다. 이 작업에서는 실제 API 검증을 수행하지 않는다.

새 worker는 별도 Compose service이고 재시작해도 원래 규칙 엔진에 영향을 주지 않는다.
`MARKET_OS_DAILY_ENABLED=0`은 새 패킷 중지, `MARKET_OS_DAILY_AI_ENABLED=0`은 유료 호출 중지.
이 둘은 기존 web research 활성화를 제어하지 않으므로 해당 기능도 별도 OFF로 둔다.
롤백 시 audit DB를 삭제하지 않는다. DB 복구/교체는 한도 상태 복구까지 포함해야 한다.

검증 명령 (`market_radar/`에서):
```sh
python -m unittest discover -s tests -v
# 아래 DSN은 반드시 폐기 가능한 별도 market_os_test DB만 사용
MARKET_OS_TEST_DATABASE_URL=postgresql://postgres:TEST_PASSWORD@localhost:5432/market_os_test \
  python -m unittest tests.test_market_os_daily_decision -v
```
PostgreSQL 테스트는 명시한 test DB만 청소하며 production DATABASE_URL만으로는 실행되지 않는다.
CI에는 별도 Postgres service가 있어 경쟁 예약/장애/일일 중복 저장 테스트를 실제 DB로 실행한다.

함께 수정한 기존 오류: `test_flow.py`에 섞인 들여쓰기, Compose 서비스 구획/중복 key,
작은 거래량에서 고정 500만원 오차 여유가 단위 불일치를 통과시키던 거래대금 신뢰도 검사.
원래 unit 테스트의 실패 조건을 유지하면서 오차 여유를 거래규모의 10% 이내로 제한했다.
