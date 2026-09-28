# AI Brokerage v1

Market Radar의 관찰 데이터를 **시장 → 재료 → 수급 → 기술 → 전략 → 리스크**의 6개 Desk로 분리해 판단하는 PAPER-first 의사결정 계층입니다.

## 원칙

1. 실거래를 보내지 않습니다. v1은 판단 패킷만 생성합니다.
2. 50개 전략 슬롯과 50개 검증 전략은 다릅니다. Registry는 50개를 보유하지만 DESIGN은 선택 대상이 아닙니다.
3. 전략은 DESIGN → PAPER → ACTIVE → DISABLED 생명주기를 가집니다.
4. 규칙이 주문 조건을 몰래 고치지 않습니다. 학습은 먼저 전략 가중치와 승격/강등에 사용합니다.
5. 하드 리스크 조건과 데이터 신선도 조건은 어떤 점수보다 우선합니다.
6. 모든 결정은 Desk별 근거와 blocker를 남깁니다.

## 6 Desks

- market: market_regime_snapshots 장세와 freshness
- catalyst: DART/뉴스/Telegram 재료 강도와 identity
- flow: 후보점수, 조회순위, 거래대금, 테마 강도
- technical: MIMOSA chart state와 TOP_WARNING
- strategy: Strategy Registry의 PAPER/ACTIVE 전략 매칭
- risk: open-position, daily-loss, quote freshness, PAPER gate

## Decision states

- IGNORE: 의미 있는 후보가 아님
- WATCH: 관찰 유지
- READY: 전략 gate는 맞지만 paper entry 기준 전
- PAPER_ENTRY: 기존 paper_trade_engine이 소비할 수 있는 모의 진입 후보
- BLOCKED: 데이터/차트/리스크/전략 gate에 하드 blocker 존재

v1에는 LIVE_ENTRY가 존재하지 않습니다.

## Strategy Registry

- REGIME_TREND 6
- BREAKOUT 10
- PULLBACK 8
- FLOW 8
- SECTOR_ROTATION 6
- EVENT 5
- OVERNIGHT 4
- PORTFOLIO 3

초기에는 일부만 PAPER입니다. 나머지는 전향적 paper episode를 축적한 뒤 승격합니다.

## 연결 순서

1. Radar row → normalized context adapter
2. 6-Desk DecisionEngine 평가
3. dashboard row에 ai_brokerage 판단 패킷 노출
4. PAPER_ENTRY를 기존 paper_trade_engine experiment queue에 연결
5. 전략별 5/15/30/60분 outcome 및 closed-trade 성과 집계
6. regime별 전략 가중치 calibration과 승격/강등

Self-check: python -m market_radar.ai_brokerage.selfcheck

## Context Matrix

전략 성과는 전체 평균 하나로 판단하지 않습니다.

`Strategy × Regime × Catalyst × Chart State` 셀별로 Paper 결과를 나누고 다음을 확인합니다.

- 완료 표본 수
- 양(+) 비율
- 평균/중앙 관찰수익
- Profit Factor
- MFE / MAE
- 특정 컨텍스트 집중도

셀 완료 표본 5건 미만은 견고성 판단에서 제외합니다.

## Lifecycle Review

Lifecycle 변경은 자동 적용하지 않습니다.

현재 기본 승격 검토 gate:

- 완료 표본 30건 이상
- 양(+) 비율 55% 이상
- 중앙 관찰수익 +0.20% 이상
- Profit Factor 1.20 이상
- 유효 컨텍스트 셀 2개 이상
- 견고한 컨텍스트 셀 2개 이상
- 단일 컨텍스트 집중도 70% 이하

가능한 판정:

- `PROMOTE_CANDIDATE` — PAPER → ACTIVE 검토
- `KEEP_PAPER` — PAPER 유지
- `REWORK_CANDIDATE` — 전략 수정·중지 검토
- `DEMOTE_CANDIDATE` — ACTIVE → PAPER 강등 검토
- `SAMPLE_BUILDING` — 표본 부족

모든 판정에는 `auto_apply=false`가 붙습니다. 실제 lifecycle 변경은 별도 검토·버전 변경으로만 수행합니다.


## Shadow Execution

Paper Trade가 전략 신호 자체를 검증한다면, Shadow Execution은 **그 신호를 실제 주문으로 냈다고 가정했을 때의 실행 품질**을 검증합니다.

v1은 실제 주문을 보내지 않으며, 현재 저장 데이터에 실제 bid/ask depth가 없기 때문에 다음 관측치만 사용합니다.

- 이벤트 시점과 가까운 SOR 체결가
- 최근 관측구간 거래대금
- 최근 3분봉 단기 변동성
- 주문 참여율 상한
- 가정 계좌자산 / 거래당 위험예산 / 최대 포지션 비중
- 사용자가 명시한 수수료·매도세 비용

유동성 근거가 없으면 체결을 추정하지 않고 `NO_LIQUIDITY_EVIDENCE` 또는 `REJECTED`로 남깁니다.

부분체결은 전량체결로 간주하지 않습니다. 출구에서 잔여수량이 생기면 `CLOSED_PARTIAL_LIQUIDITY`로 분리하며, 완전청산 표본만 대표 수익 통계에 포함합니다.

Shadow 검증은 prospective 원칙을 유지합니다. worker 시작 이전의 과거 Paper Trade를 장기간 백필하지 않고, 재시작 장애 복구를 위한 짧은 replay window만 허용합니다.

### Shadow v1 position sizing

- risk budget = account equity × risk per trade
- stop distance = 최근 변동성 기반, 최소/최대 범위 제한
- target notional = risk budget / stop distance
- final notional = target notional과 max position cap 중 작은 값
- fillable notional = 최근 거래대금 × max participation

### Important limitation

현재 v1의 slippage는 **실제 호가 스프레드가 아니라 proxy**입니다. 실제 최우선 호가·잔량이 수집되면 execution model의 입력을 교체하고 v1 proxy 결과와 분리해 버전 관리해야 합니다.


## Execution v2 — Official 10-Level Order Book + TCA

Execution v2 separates **signal quality** from **execution quality**.

### Official Kiwoom order-book source

Read-only collector:

- API ID: `ka10004`
- Method: `POST`
- URL: `/api/dostk/mrkcond`
- request: `stk_cd`
- SOR request example: `005930_AL`

Important official response identifiers used by the collector:

- best ask: `sel_fpr_bid`
- best ask quantity: `sel_fpr_req`
- ask levels 2–10: `sel_{n}th_pre_bid`, `sel_{n}th_pre_req`
- best bid: `buy_fpr_bid`
- best bid quantity: `buy_fpr_req`
- bid levels 2–10: `buy_{n}th_pre_bid`, `buy_{n}th_pre_req`
- total ask quantity: `tot_sel_req`
- total bid quantity: `tot_buy_req`
- provider book-time field: `bid_req_base_tm`

The collector calls no order endpoint. It targets only recent AI Brokerage / Paper / Shadow names.

### BOOK_V2 fill model

When a fresh order book exists:

1. calculate best ask / best bid / midpoint / spread
2. haircut displayed quantity before using it
3. BUY walks asks from best price upward
4. SELL walks bids from best price downward
5. stop when requested shares are filled or 10 levels are exhausted
6. record VWAP, fill ratio, levels used, remaining shares
7. compute implementation shortfall against arrival midpoint

A crossed book is rejected. A spread above the configured maximum is rejected.

### PROXY_V1 fallback

If a fresh order book is absent and fallback is enabled, the previous turnover/volatility model is used.

BOOK_V2 and PROXY_V1 must never be pooled as if they had equal execution fidelity. Dashboard metrics expose BOOK_V2 coverage explicitly.

### Implementation Shortfall / TCA

For BOOK_V2:

- entry IS = adverse distance from arrival mid to entry VWAP
- exit IS = adverse distance from arrival mid to exit VWAP
- round-trip IS = entry IS + exit IS
- return drag = Paper return − Shadow net return

The dashboard exposes:

- BOOK_V2 coverage
- median entry / exit / round-trip IS
- median Paper→Shadow return drag
- fill ratio
- complete vs partial exits
- execution / liquidity rejects

### Portfolio Risk Budget

Before a Shadow entry is simulated, the proposed risk is checked against:

- total portfolio risk cap
- theme risk cap
- strategy-family risk cap
- maximum simultaneous positions

The simulator may scale requested shares down when only part of the risk budget remains.

A hard-cap breach rejects the Shadow entry.

### Defaults

Defaults are research settings, not claims of optimality:

- account equity: KRW 100,000,000
- risk per trade: 0.50%
- max position: 10%
- max total portfolio risk: 2.0%
- max theme risk: 0.8%
- max strategy-family risk: 1.2%
- max open positions: 5
- displayed book liquidity haircut: 50%
- book max age: 30 seconds
- proxy fallback: enabled

Fees and sell tax default to zero until the actual account/broker cost assumptions are explicitly entered.

### Core rule

> A good strategy with poor execution is not a good trade.

Execution v2 therefore reports the strategy result and the execution cost separately.


## Capacity Model — Execution-adjusted Strategy Capacity

Capacity Model asks a different question from strategy win rate:

> **How much capital can this strategy absorb before execution erodes the observed edge?**

It deliberately separates two concepts.

### 1. Point-in-time Book Capacity

At each Shadow entry, the 10-level order book is walked using the configured displayed-liquidity haircut.

The engine stores the maximum immediately executable size whose estimated implementation shortfall remains below the configured threshold.

Default research threshold:

- max book-capacity IS: 30 bp

Stored fields include:

- entry book capacity shares
- entry book capacity KRW
- entry book capacity IS
- entry spread

This is an **instantaneous liquidity estimate**, not a long-run strategy capacity forecast.

### 2. Empirical Strategy Capacity

Completed BOOK_V2 Shadow trades are grouped by:

`Strategy × Regime × Liquidity × Spread × Order Size`

Current order-size research buckets:

- O1: ≤ KRW 2.5m
- O2: KRW 2.5m–5m
- O3: KRW 5m–10m
- O4: KRW 10m–20m
- O5: ≥ KRW 20m

A size bucket is supported only after minimum samples and execution-adjusted performance gates are met.

Current default research gates:

- minimum BOOK_V2 closed samples per strategy: 20
- minimum samples per order-size bucket: 5
- minimum positive ratio: 50%
- minimum median Shadow net return: +0.10%
- minimum Profit Factor: 1.10
- maximum median Paper→Shadow drag: 0.50%p
- maximum median round-trip IS: 40 bp
- minimum distinct regimes: 2

The reported Evidence Capacity is conservatively limited by both:

1. the highest empirically supported order-size bucket, and
2. the 25th percentile of observed point-in-time book capacity.

No capacity value is automatically applied to live sizing.

### Final Lifecycle Gate

Paper performance is no longer sufficient for a final promotion candidate.

A PAPER strategy can reach `PROMOTE_CANDIDATE_EXECUTION_ADJUSTED` only when:

1. Paper lifecycle review says promotion candidate,
2. Shadow sample is sufficient,
3. BOOK_V2 coverage is sufficient,
4. execution-adjusted median net return remains positive,
5. execution-adjusted Profit Factor remains above the gate,
6. implementation shortfall remains controlled,
7. Paper→Shadow drag remains controlled, and
8. strategy capacity has evidence support.

Otherwise it stays pending or is blocked.

Every lifecycle result continues to return `auto_apply=false`.

### Capacity caveat

The current Capacity Model measures capacity within the **observed 10-level book and sampled market regimes**.

It does not claim institutional AUM capacity, hidden-liquidity availability, queue priority, market impact beyond displayed depth, or multi-day liquidation capacity.

Those require additional data and models.
