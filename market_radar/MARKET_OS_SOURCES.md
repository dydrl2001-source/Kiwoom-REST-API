# Market OS Source Matrix

## 원칙

소스가 많아질수록 좋은 것이 아니라 **역할이 겹치지 않게 배치**한다.

1. **원천(Source of Truth)** — 가격·거래·공시의 사실 확인
2. **발견(Discovery)** — 어떤 종목/테마를 더 볼지 후보를 넓힘
3. **해석(Context)** — 실적·컨센서스·거시환경을 설명
4. **검증(Verification)** — 뉴스 제목이 아니라 원문·공시·가격 반응으로 확인

자동 수집은 공식 API/허용된 피드부터 연결한다. 유료 서비스의 화면을 무단 크롤링하는 방식은 기본 설계에 넣지 않는다.

## 권장 역할

| 소스 | 역할 | Market OS 사용처 | 자동화 상태 |
|---|---|---|---|
| Kiwoom REST/WebSocket | 국내 실시간 가격·체결·조회/거래대금·테마 | Radar, Theme, Setup | **핵심 / 현재 사용** |
| KRX Data Marketplace | 거래소 사후 검증·투자자/프로그램/공매도 등 | 장마감 검증, 백테스트 | Phase 2 |
| OpenDART | 공식 기업공시 | Catalyst 근거 | **현재 사용** |
| KIND | 거래소 공시 교차확인 | Catalyst 근거 | Phase 2 |
| Telegram | 조기 재료 탐지 | Discovery only | **현재 사용** |
| NAVER 공식 검색 (API HUB / 기존 키) | 보조 Discovery / Context / 사람 Verification | 구현·기본 OFF; 뉴스/웹문서/블로그, 결과 AI 입력 금지 |
| NAVER 증권 웹 | 사람의 시세/기업 교차확인 | 링크만, 자동 크롤링 없음 |
| 공개 뉴스/RSS | 사건 탐지 | Catalyst 후보 | 부분 사용 |
| TradingView | 글로벌 차트·스크리너·Heatmap | 사람의 교차검증 | Human-in-the-loop |
| Quantus | 팩터/기술조건 스크리닝·백테스트 대조군 | Rule 검증 | Human-in-the-loop |
| FnGuide CompanyGuide | 실적·컨센서스·밴드·수급 | Fundamental context | 라이선스 확인 후 |
| WiseReport | 증권사 리포트 탐색 | Catalyst/Estimate context | Human-in-the-loop |
| DeepSearch | 뉴스·공시·기업/시장 데이터 통합 후보 | Event/Fundamental API 후보 | 비용·라이선스 검토 |
| Reuters | 글로벌 overnight 뉴스 | Market context | Human/API 계약 시 |
| FINVIZ | 미국장 Heatmap/Screener | Overnight discovery | Human-in-the-loop |
| FRED | 미국 거시 시계열 | Market Regime macro | Phase 2 API |
| 경제 캘린더 | 발표 일정·실제/예상/이전 | Event risk calendar | Phase 2 |
| Koyfin / MacroMicro | 거시·자산 관계 시각화 | 사람의 레짐 점검 | Human-in-the-loop |

## 데이터 우선순위

같은 사건이 여러 곳에서 들어오면 다음 순서로 보존한다.

```text
공식 공시(DART/KIND)
    > 거래소/기업 IR 원문
    > 주요 통신·언론 원문
    > 증권사 리포트
    > Telegram/커뮤니티 언급
```

낮은 단계의 자료가 빠르다는 이유만으로 높은 단계의 검증을 대체하지 않는다.

## 실시간 파이프라인

```text
[Kiwoom SOR / WebSocket]
  ├─ 조회순위
  ├─ 거래대금
  ├─ 체결/분봉
  └─ 테마그룹
       ↓
  Radar / Theme / Setup

[Telegram / RSS / DART]
       ↓
 Event Deduper
       ↓
 Catalyst Evidence

[FRED / Overnight / FX / Oil / Rates]
       ↓
 Market Regime

세 축을 합산하지 않고
       ↓
 Market OS Watch Tier
 FOCUS / PREP / DISCOVER / BLOCKED
```

## 외부 소스를 붙일 때의 규칙

- 기사 제목만 저장하지 말고 `published_at / source / canonical_url / symbols / event_type / fingerprint`를 함께 저장한다.
- 동일 기사의 재전송과 독립된 새 출처를 구분한다.
- Telegram 채널 수를 사실성 점수로 쓰지 않는다. 확산 속도 지표로만 쓴다.
- 미국장 상승을 한국 종목 상승의 원인으로 바로 연결하지 않는다. 한국장 거래대금·테마 동행이 확인돼야 한다.
- 컨센서스는 절대값뿐 아니라 1주/1개월 변화율을 저장한다.
- 거시지표는 발표 시각을 보존해 look-ahead bias를 막는다.

## Phase 2 우선순위

1. Kiwoom 0B 체결 WebSocket → 정확한 분당 거래대금/체결강도
2. Market OS 축별 snapshot 저장 → 5분·30분·종가·D+1 MFE/MAE 검증
3. FRED + 환율/금리/유가 overnight context
4. KRX 장마감 투자자/프로그램 데이터 검증
5. 컨센서스 revision 데이터는 라이선스 가능한 공급자를 정한 뒤 연결

## Daily Decision 연동 (2026-10-05)

Kiwoom=가격·체결, DART=공시, KRX=사후검증 원칙을 유지한다. NAVER 검색은 시세·수급 공급원이 아니다.
공식 검색 API의 결과가 사실 검증 완료를 뜻하지 않으며, 블로그를 공시 등급으로 승격하지 않는다.

[NAVER 검색 약관](https://developers.naver.com/products/terms/) 검색 특약 2.3의 AI 입력 금지에 따라
Daily Decision의 `naver_search_context`에는 자체 검색어/사람 링크/결과 제외 상태만 포함한다.
결과 문자열·요약·파생물은 AI·학습·영구 패킷에 저장하지 않는다.

신규 키는 NAVER API HUB에서 등록한다. legacy 신규 신청은 2026-07-31부터 중단됐으며,
기존 키 서비스도 2027-07-01부터 종료된다. 인증·쿼터·선택 API와 제외 이유·이관 근거는
[Daily Decision 운영 문서](MARKET_OS_DAILY_DECISION.md)에 정리했다.

## 실제 수급·계좌 읽기 전용 연동

- Kiwoom `ka10059`: 종목별 외국인/기관 순매수. 금액 모드의 백만원을 원으로 변환하고 원본 거래일을 보존한다. 조회 시각으로 거래일을 갱신하지 않는다. 장중 확정 수급 또는 매매 신호로 취급하지 않는다.
- `kt00018`: KRX 기준 계좌 평가/잔고 요약. 누적 평가손익은 당일 손익이 아니다.
- `ka10074`: 요청일과 일치하는 행의 실현손익만 채택한다. 전일 또는 누락 행은 미확인이다.
- `ka10075`: 통합 시장 전체 미체결. 모든 페이지가 완료되어야 중복주문 여부를 판정한다.
- `kt00017`: D+2 추정예수금. 즉시 주문 가능금액으로 해석하지 않는다.
- 공식 [키움 REST API 가이드](https://openapi.kiwoom.com/m/guide/apiguide?dummyVal=0), 저장소 `kiwoom/_data/kiwoom_api_spec.json`의 필드/단위 계약 사용.
- 읽기 전용 adapter에는 주문·정정·취소 API가 없다. 계좌 최소 관측값은 인증된 로컬 화면만 사용하며 AI와 공개 산출물에 포함하지 않는다.

설정·조회·누락 처리·현재 검증 범위: [MARKET_OS_READONLY.md](MARKET_OS_READONLY.md).
