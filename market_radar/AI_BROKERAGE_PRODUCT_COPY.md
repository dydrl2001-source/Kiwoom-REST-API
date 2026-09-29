# AI Brokerage Product Narrative & Copy Spec

> Reference analysis: public Wadiz project 417974, reviewed 2026-09-29.
> This document does **not** reproduce the source copy. It reverse-engineers the information architecture and rewrites it for Market Radar / AI Brokerage based on functions we can actually substantiate.

## 1. What the reference page does well

The reference page follows a clear persuasion sequence:

1. **Transformation scene** — an ordinary office worker becomes an operator of an automated investment workflow.
2. **Structural problem** — individual investors have limited time and fragmented tools while institutional teams divide work.
3. **Rule over intuition** — emotions and ad-hoc decisions are contrasted with predefined entry/exit/risk rules.
4. **Department metaphor** — investment work is split into screening, technical, fundamental/market, risk and operations.
5. **Meeting metaphor** — multiple perspectives disagree, then reach a constrained conclusion.
6. **Strategy library** — the system is presented as useful only when concrete strategies are loaded into it.
7. **Automation loop** — analysis → execution → review → rule improvement.
8. **Daily routine** — morning briefing, intraday execution/risk management, evening review.
9. **Build roadmap** — a two-week curriculum makes the result feel buildable.
10. **No-code reassurance** — lowers the implementation barrier.
11. **Package / tier comparison** — turns architecture into a concrete deliverable list.
12. **FAQ and safety caveats** — simulated trading first, small size, no profit guarantee.
13. **Action close** — “build a structure rather than rely on impulse.”

The strongest concept is not “AI stock picking.” It is **role separation + repeatable process + feedback loop**.

---

## 2. Our positioning

### Primary headline

**감으로 고르는 종목이 아니라  
근거가 통과한 전략만 다음 단계로**

### Supporting copy

Market Radar는 시장을 맞히는 AI를 전제로 하지 않는다.  
시장·재료·수급·차트·전략·리스크를 서로 다른 Desk로 분리하고, 각 Desk의 근거와 반론을 남긴다. 전략 조건과 Risk Gate를 모두 통과한 경우에만 PAPER 실행 후보가 된다.

### Short version

**Observe → Cross-check → Match → Veto → Paper → Review**

---

## 3. Narrative order for the product UI

### Scene 01 — Why

**혼자 더 오래 보는 것이 답이 아니었다.**

문제는 정보의 양보다 역할이 섞여 있다는 데 있다.  
뉴스를 읽으면서 차트를 보고, 차트를 보면서 손익을 걱정하면 판단 기준은 쉽게 이동한다.

AI Brokerage는 한 명의 천재 AI를 만드는 대신 **책임이 다른 Desk를 분리**한다.

---

### Scene 02 — Operating model

**한 종목을 여섯 번 본다. 같은 질문을 여섯 번 하는 것이 아니다.**

- Market Desk — 지금 어떤 장인가?
- Catalyst Desk — 이 재료는 실제 이 종목의 것인가?
- Flow Desk — 관심이 아니라 실제 돈이 들어오는가?
- Technical Desk — 가격 구조가 아직 살아 있는가?
- Strategy Desk — 어떤 전략의 조건이 실제로 충족됐는가?
- Risk Desk — 맞아 보여도 지금 실행하면 안 되는 이유가 있는가?

Risk Desk는 점수가 아니라 **거부권**을 가진다.

---

### Scene 03 — Strategy Factory

**전략 50개를 보유하는 것보다 중요한 것은  
50개를 똑같이 믿지 않는 것이다.**

Lifecycle:

DESIGN → PAPER → ACTIVE → DISABLED

- DESIGN: 논리와 조건만 정의됨
- PAPER: 전향적 가상실행으로 검증 중
- ACTIVE: 승격 기준을 통과한 운영 가능 전략
- DISABLED: 성과 저하·환경 부적합·검증 실패로 중지

The UI must always show **slot count and validated count separately**.

---

### Scene 04 — Decision states

- IGNORE — 현재 근거가 약함
- WATCH — 관찰 유지
- READY — 전략 조건은 맞지만 실행 문턱 전
- PAPER_ENTRY — 가상 forward-test 후보
- BLOCKED — 전략 점수와 무관하게 Risk/quality gate가 차단

There is no LIVE_ENTRY in v1.

---

### Scene 05 — Daily loop

#### Morning
**오늘 무엇을 사야 하는가보다 먼저, 오늘 어떤 장인가.**

Regime / leading sectors / overnight context / active strategy families.

#### Intraday
Candidate Tracker가 관심·돈·재료·차트의 변화를 추적한다.

#### Decision meeting
6 Desks produce independent verdicts and blockers.

#### Execution
Only PAPER_ENTRY is handed to the paper execution layer.

#### Evening
**오늘 수익이 났는가가 아니라, 어떤 판단이 맞았는가.**

Attribute outcome to:
- market regime
- strategy
- catalyst type
- sector
- chart state
- entry timing
- blocker quality

---

## 4. Product copy bank

### Hero alternatives

**A. Default**
> 시장을 예측하는 AI보다, 잘못된 판단을 막는 구조를 만든다.

**B. Quant**
> 하나의 추천 점수 대신 여섯 개의 독립 판단과 하나의 Risk Veto.

**C. Everyday**
> 하루 종일 차트를 볼 필요가 없도록, 판단 과정을 시스템 안에 넣는다.

### Section titles

- 오늘 장을 먼저 읽습니다
- 돈이 어디로 이동하는지 봅니다
- 재료가 진짜 그 종목의 것인지 확인합니다
- 차트가 아니라 가격 구조를 읽습니다
- 현재 장에 맞는 전략만 꺼냅니다
- 맞아 보여도 Risk Desk가 막을 수 있습니다
- 실행보다 먼저 PAPER에서 틀려봅니다
- 결과를 전략에 다시 돌려줍니다

### Safety copy

**PAPER FIRST**  
실전 주문보다 먼저 forward-test 표본을 쌓습니다.

**NO BLACK BOX**  
결론만 보여주지 않고 Desk별 이유와 blocker를 함께 저장합니다.

**NO SILENT SELF-MODIFICATION**  
AI가 실시간으로 매매 규칙을 몰래 고치지 않습니다. 성과는 먼저 Strategy Performance에 귀속하고, 승격·강등은 별도 기준으로 처리합니다.

---

## 5. What we should not copy from the reference

Do not reuse external claims that are not ours:

- funding/revenue/testimonial amounts
- “verified strategy” claims without our own evidence
- profit-like before/after charts
- “10 minutes a day” as a promise before measured usage data
- named-investor personas as if they are actual expert agents
- guaranteed automation / automatic improvement language
- tier valuations that assign arbitrary monetary value to templates

Our advantage should come from **observable system behavior**, not stronger marketing adjectives.

---

## 6. Evidence we can actually surface

Every marketing statement should be backed by one UI object.

| Claim | Evidence in product |
|---|---|
| Six independent desks | Desk verdict array with reasons/blockers |
| 50 strategy slots | StrategyRegistry lifecycle counts |
| Risk veto | BLOCKED state and Risk Desk blockers |
| Market-adaptive selection | regime × strategy match record |
| Explainable decision | DecisionPacket |
| Forward validation | paper trade episode and outcomes |
| Learning | strategy-level performance history and promotion/demotion log |
| Data freshness | market/quote freshness seconds |
| Material verification | identity quality + DART/news/Telegram evidence |

---

## 7. Next product pages

### AI Brokerage
Current six-desk meeting, Strategy Factory, lifecycle, candidate decisions.

### Strategy Performance
Each strategy:
- N
- win rate
- expectancy
- profit factor
- MFE / MAE
- max drawdown
- regime split
- recent 20 / 60
- promotion state

### Daily Review
- decisions made
- blocked decisions
- false positives
- missed opportunities
- desk attribution
- proposed calibration

### Morning Brief
- regime
- strongest sectors
- active strategy families
- watchlist
- risk budget
- what changed overnight

---

## 8. Product principle

> **자동화의 수준은 주문을 얼마나 빨리 내느냐가 아니라,  
> 어떤 판단을 왜 자동화했는지 설명할 수 있느냐로 평가한다.**

Market Radar AI Brokerage should become an operating system that can answer three questions for every trade candidate:

1. **왜 지금 이 종목인가?**
2. **왜 이 전략인가?**
3. **무엇이 틀리면 즉시 철회할 것인가?**

If those three answers are not present, the system has not earned the right to execute.
