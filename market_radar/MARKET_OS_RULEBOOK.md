# Market OS Rulebook v1

## 목적

기존 Market Radar의 장점은 유지한다. **Kiwoom 조회순위·거래대금·30초 흐름, Telegram/뉴스/DART, 미모사 차트 상태, Market Regime**을 하나의 총점으로 섞지 않고 서로 다른 판단축으로 분리한다.

핵심 순서는 교재에서 반복되는 문법을 따른다.

```text
시장 레짐
  ↓
주도 테마 / 돈의 집중
  ↓
종목 압축
  ↓
재료 검증
  ↓
차트 Setup
  ↓
Trigger 확인
  ↓
관찰·실행 후 복기
```

## 왜 총점을 없애는가

기존 `attention_score`는 화면에서 먼저 볼 종목을 줄이는 데는 유용하지만, 관심·수급·차트·재료를 한 숫자에 섞으면 "왜 이 종목이 위에 있는가"가 흐려진다.

v1에서는 다음을 독립적으로 표시한다.

| 축 | 질문 | 출력 |
|---|---|---|
| Radar | 지금 사람들이 보고 실제 거래가 붙는가? | 0–100 관찰 강도 |
| Theme | 같은 테마로 돈이 확산·지속되는가? | 0–100 테마 구조 |
| Setup | 교재의 돌파·수렴·눌림 구조와 맞는가? | 0–100 차트 구조 |
| Catalyst | 재료가 얼마나 검증되었는가? | A/B/C/U 근거등급 |
| Trigger | 현재 실행 구조가 어느 단계인가? | 상태값 |
| Risk | 들어가면 안 되는 이유가 무엇인가? | 플래그 |

**Radar/Theme/Setup 점수는 수익확률이 아니다.** 서로 독립적으로 비교하기 위한 운영 휴리스틱이다.

## 강의·교재에서 시스템으로 옮긴 핵심

### 1. 천리안 — 시장이 먼저다

- 시장 → 주도 섹터 → 종목 압축 → 타점.
- 좋은 뉴스 자체보다 좋은 뉴스에 시장이 어떻게 반응하는지를 본다.
- 특정 섹터와 대장주에 돈이 지속되는 장과, 자금이 계속 옮겨 다니는 시소타기 장을 분리한다.
- 거래대금 상위 종목이 어느 섹터에 군집하는지 본다.

### 2. 미모사 — 신고가·명분·지속 거래대금

- 조회순위 1등은 매수 우선순위가 아니라 후보 발견이다.
- 신고가/고가권, 직접 재료, 큰 거래대금의 지속성이 겹치는 종목을 주도 후보로 본다.
- 등락률 대장과 실제 거래대금 주도주를 분리한다.
- 수급 분산 시장에서는 돌파 실패가 반복되므로 공격성을 낮춘다.

### 3. 드림로드 — 강한 종목의 정상 조정

- 시장 → 주도 테마 → 대장주 → 기준봉 → 눌림 → 분할.
- "떨어졌기 때문에"가 아니라 강함이 검증된 종목이 정상 조정 범위에 들어올 때만 본다.
- 5일·10일·20일선은 각각 얕은 관심, 핵심 지지 후보, 추세 경계의 역할로 보되 다른 구조와 중첩해 해석한다.
- 대장 붕괴, 거래대금 동반 장대음봉, 테마 이탈은 취소 규칙이다.

### 4. 천리안 변곡점 — 지수는 비중의 허용 범위를 정한다

- 장중 이탈과 종가 이탈을 구분한다.
- 여러 시간 프레임과 거래량 기억이 겹치는 곳을 한 점이 아닌 밴드로 관리한다.
- 거시 뉴스는 가격과 거래대금, 대형주의 동행으로 확인한다.

## Watch Tier

총점 대신 **조건의 교집합**으로 묶는다.

- `FOCUS`: Radar·Theme·Setup이 함께 확인되고 Catalyst도 인용 근거가 있으며 구조가 훼손되지 않은 종목.
- `PREP`: 구조 또는 재료가 상당 부분 확인됐지만 한 단계가 남은 종목.
- `DISCOVER`: 거래/관심이 먼저 포착된 조사 후보.
- `BLOCKED`: 돌파 실패·추세 훼손 등 신규 실행 후보에서 제외할 종목.

이 Tier 역시 매수 지시가 아니다. 화면에서 **무엇을 먼저 검토할지** 정리하는 용도다.

## Market Stance

`market_regime_snapshots`의 최신 레짐을 읽는다.

- `EXPANDABLE`: 주도주/대형주 집중이 확인되고 하락 레짐이 아닐 때.
- `SELECTIVE`: 혼합·전환·횡보 구간.
- `DEFENSIVE`: 하락, 심리 약화, 수급 분산/광범위 분산 중 하나가 확인될 때.
- `UNKNOWN`: 데이터가 없거나 지연.

비중 자체를 자동 계산하거나 주문하지 않는다.

## 다음 검증 과제

1. 최소 20거래일 이상 Market OS 각 축의 스냅샷을 저장한다.
2. FOCUS/PREP/DISCOVER별로 이후 5분·30분·종가·D+1의 MFE/MAE를 기록한다.
3. 시간대(장초/오전/오후/종가)별 임계값을 분리한다.
4. 강세/중립/분산 레짐에서 같은 Setup의 성과 차이를 검증한다.
5. 숫자 임계값은 검증 전까지 강의의 공식 수치로 표현하지 않는다.

구체 규칙과 출처 메타데이터는 `rulebook/market_os_rules.json`에 둔다.


## 0B Shadow Microstructure

Kiwoom 주식체결 0B는 현재 **live scoring에 직접 넣지 않는다.** 먼저 별도 shadow feature로 저장해 설명력이 있는지 검증한다.

저장 항목:
- 최근 15초 관측 거래대금
- 최근 15초 관측 매수체결 비중
- 최근 15초 tick / gap 수
- 체결강도
- Kiwoom 매수비율

학습 차원:
- `MICRO_STRENGTH`: <80 / 80–99 / 100–119 / 120+
- `MICRO_BUY_SHARE`: <45% / 45–54% / 55–64% / 65%+

이 구간은 **운영 휴리스틱**이며 강사의 공식 임계값이 아니다. 최소 표본을 확보한 뒤 30분·종가 MFE/MAE와 함께 비교하고, 설명력이 확인되기 전에는 Radar/Setup 점수를 변경하지 않는다.

### Look-ahead 방지

- assessment는 실제 관측 초(second)를 보존한다.
- 0B point outcome은 target 이후 첫 **완결된 5초 bucket의 open**을 사용한다.
- MFE/MAE는 outcome 시각 이전 bucket만 사용한다.
- 누락 tick이 감지되면 gap으로 보존하며 값을 보간하지 않는다.
- 0B가 불충분하면 SOR → 보수적 3분봉 fallback 순으로 사용한다.


## Interaction Lab

Market OS는 개별 축의 절대 성과만 보지 않고, 사전등록된 상호작용을 shadow-learning으로 검증한다.

핵심 질문은 다음과 같다.

```text
같은 Trigger라도
어떤 Market Stance에서,
어떤 Setup 구조일 때,
0B 체결상태가 어떻게 붙었는가?
```

### 사전등록 조합

- STANCE × SETUP
- SETUP × TRIGGER
- STANCE × TRIGGER
- STANCE × SETUP × TRIGGER
- STANCE × TRIGGER × MICRO_STATE
- SETUP × TRIGGER × MICRO_STATE
- STANCE × SETUP × TRIGGER × MICRO_STATE

임의로 모든 변수를 조합하지 않는다. 위 조합만 계산해 다중탐색과 사후적 규칙 만들기를 제한한다.

### MICRO_STATE

0B 15초 구간이 gap-free일 때만 사용한다.

- STRONG_CONFIRM: 체결강도 120+ AND 관측 매수체결 65%+
- POSITIVE: 체결강도 100+ AND 관측 매수체결 55%+
- MIXED: 강·약 조건 사이
- NEGATIVE: 체결강도 100 미만 AND 관측 매수체결 45% 미만
- WEAK_CONFIRM: 체결강도 80 미만 AND 관측 매수체결 45% 미만
- NO_DATA: 자료 부족

이 임계값은 강의의 공식 수치가 아니라 **운영 휴리스틱**이다.

### 부모조건의 나머지 표본 대비 Δ

복합조건의 절대 평균만 보면 장 전체가 좋거나 나쁜 효과와 섞일 수 있다. 그래서 복합조건(child)을 더 단순한 부모조건 전체가 아니라, **부모조건에서 child를 제외한 나머지 표본(complement)**과 비교한다.

예:

```text
DEFENSIVE × BREAKOUT_TEST
        ↓ parent

DEFENSIVE × Setup80-100 × BREAKOUT_TEST
        ↓ child

child - parent complement

Δ평균수익률
Δ양(+)비율
ΔMFE
ΔMAE
```

이 Δ는 인과효과를 증명하지 않는다. 같은 장세·Trigger 안에서 해당 child 조건을 만족한 episode와 만족하지 않은 episode의 관측 분포 차이를 보는 비교지표다.

### 복잡도별 신뢰 문턱

상호작용 차수가 높을수록 더 많은 독립 episode, 종목 다양성, 거래일 수를 요구한다. 4-way interaction은 단일축보다 훨씬 엄격한 문턱을 통과해야 한다.

또한 live 후보에 고차 interaction의 과거 성과를 표시하는 것은 **형성 이상 + 부모조건도 형성 이상**인 경우로 제한한다. 자동으로 Radar/Setup 점수를 바꾸지는 않는다.

## Validation Gate v1.3 — Walk-forward Stability

누적 표본에서 평균이 좋다는 사실만으로 live 규칙 후보를 승격하지 않는다. 같은 조건이 **시간을 나눠도 같은 방향으로 반복되는지**를 확인한 뒤에만 사람 검토 단계로 올린다.

### 거래일 단위 분할

- episode-anchor 표본을 거래일 기준으로 정렬한다.
- 서로 다른 거래일이 4일 미만이면 walk-forward 판단을 하지 않는다.
- 거래일 목록의 앞 절반을 `EARLY`, 뒤 절반을 `RECENT`로 사용한다.
- 같은 거래일의 episode가 두 구간에 동시에 들어가는 것을 금지한다.
- 상호작용의 parent-complement도 child와 **동일한 날짜 집합**에서 비교한다.

### 승격 전 시간축 검증

먼저 Validation Gate v1.2의 누적 조건을 통과해야 한다.

- 대상 horizon: 30m / close / D+1
- 평균·중앙값·양(+) 비율의 방향 일치
- 단일축은 형성 이상
- 상호작용은 child와 parent-complement 모두 형성 이상
- 상호작용 Δ평균·Δ양(+)·ΔMAE 방향 일치

그 다음 EARLY/RECENT를 다시 본다.

- 두 기간 모두 최소 2거래일 이상이어야 한다.
- interaction depth가 높을수록 각 기간의 N·종목 다양성 문턱을 높인다.
- `STRENGTH` 후보는 두 기간 모두 평균 > 0, 중앙값 ≥ 0, 양(+) 비율 ≥ 50%를 요구한다.
- `WEAKNESS` 후보는 두 기간 모두 평균 < 0, 중앙값 ≤ 0, 양(+) 비율 ≤ 50%를 요구한다.
- 최근 효과가 누적 기준의 35%보다 작아지면 `WEAKENING`으로 보류한다.
- 최근 평균 방향이 반대로 바뀌면 `REVERSAL`로 보류한다.
- 상호작용은 EARLY/RECENT 각각에서도 parent-complement 대비 Δ평균·Δ양(+)·ΔMAE 방향이 유지되어야 한다.

### 출력 상태

- `STABLE`: 누적 조건과 시간분할 검증 모두 통과
- `WEAKENING`: 방향은 유지하지만 최근 효과 크기가 너무 작아짐
- `UNSTABLE`: 기간별 핵심지표 방향이 충분히 정렬되지 않음
- `REVERSAL`: 최근 구간에서 효과 또는 interaction edge 방향이 반전
- `INSUFFICIENT`: 기간별 표본·종목·거래일 또는 comparator가 부족

`PROMOTE_REVIEW` / `SUPPRESS_REVIEW`는 walk-forward가 `STABLE`일 때만 유지한다. 나머지는 `HOLD`로 내려간다.

이 검증은 **규칙 변경 권한이 없다.** live Radar / Theme / Setup / Catalyst / Trigger 점수와 주문 로직은 자동 수정하지 않는다.

## Promotion Registry v1.4 — Hypothesis Lifecycle

Market OS가 발견한 조건은 화면에 잠깐 나타났다 사라지는 숫자가 아니라 **검증 이력을 가진 가설 객체**로 관리한다.

### 자동 생애주기

```text
HYPOTHESIS
  ↓
FORMING
  ↓
VALIDATED
  ↓
STABLE
  ↓
PROMOTION_CANDIDATE
```

자동 학습은 여기까지다.

`SHADOW_RULE`은 Promotion Registry가 스스로 만들 수 없다. 사람의 별도 승인 절차를 거친 경우에만 사용할 수 있도록 필드만 준비한다.

### 단계 정의

- `HYPOTHESIS`: 아직 탐색 품질. 관찰은 하지만 규칙 후보로 보지 않는다.
- `FORMING`: 초기 품질이거나, 표본은 형성됐지만 누적 Validation Gate를 통과하지 못했다.
- `VALIDATED`: 평균·중앙값·양(+) 비율, 필요 시 parent-complement까지 누적 검증을 통과했다. 아직 시간축 안정성이 확보되지 않았을 수 있다.
- `STABLE`: 누적 검증과 EARLY/RECENT walk-forward 방향 일치를 통과했지만, 전체 품질이 `충분`까지 오르지 않았다.
- `PROMOTION_CANDIDATE`: `충분` 품질 + 누적 검증 + walk-forward `STABLE`을 모두 통과한 사람 검토 대상.
- `SHADOW_RULE`: 수동 승인 후 별도 shadow A/B 실험에 사용하는 단계. 자동 전이 금지.

### 방향과 행동은 단계와 분리한다

Registry는 조건의 생애주기와 함께 두 값을 별도로 저장한다.

- `direction`: STRENGTH / WEAKNESS / MIXED
- `review_action`: PROMOTE / SUPPRESS / NONE

따라서 약한 조건도 검증을 충분히 통과하면 `PROMOTION_CANDIDATE` 단계에서 `SUPPRESS` 검토 대상으로 올라올 수 있다. 여기서 promotion은 “규칙으로 승격할 가치가 있는 가설”이라는 의미이며, 반드시 점수를 올린다는 뜻이 아니다.

### 비단조적 검증

과학적 검증 단계는 한 번 올라가면 영구히 고정되는 계급이 아니다.

예를 들어 과거에는 `STABLE`이었지만 최근 데이터에서 반전되면 현재 단계는 다시 `VALIDATED` 또는 `FORMING`으로 내려갈 수 있다. 이 하향 전이도 실패가 아니라 새로운 증거다.

단, 이미 사람이 승인한 `SHADOW_RULE`은 자동 refresh가 단계 자체를 덮어쓰지 않는다. 대신 최신 성과·방향·근거만 갱신해 재검토할 수 있게 한다.

### 감사 가능성

현재 상태는 `market_os_promotion_registry`에 저장한다.

단계가 처음 발견되거나 바뀌거나 방향/행동이 바뀌면 `market_os_promotion_events`에 별도 이벤트를 남긴다.

기록 항목:
- candidate key
- 이전 단계 / 현재 단계
- 방향 / review action
- 누적 N·종목 수·거래일 수
- 품질 등급
- walk-forward 상태
- EARLY / RECENT 평균
- interaction edge
- reason codes

Registry refresh는 후보를 삭제하지 않는다. 현재 60일 학습창에서 보이지 않는 항목은 `active=false`로 남겨 과거 이력을 보존한다.

이 단계 역시 live 점수, 주문, 실전 비중을 자동 변경하지 않는다.

## Shadow Rule Lab v1.5 — Prospective CONTROL vs CHALLENGER

`PROMOTION_CANDIDATE`가 충분한 과거·walk-forward 근거를 갖더라도 기존 Market OS 규칙을 바로 바꾸지 않는다. 사람의 명시적 승인 이후 **별도 challenger**로만 실행한다.

### 수동 승인 경계

자동 학습은 `SHADOW_RULE`을 만들 수 없다.

수동 도구:

```bash
bash market_radar/local/shadow_rule_admin.sh list
bash market_radar/local/shadow_rule_admin.sh approve <candidate_key> --confirm
bash market_radar/local/shadow_rule_admin.sh disable <shadow_rule_id> --confirm
```

승인은 `PROMOTION_CANDIDATE`에만 허용한다. 승인 시각을 prospective boundary로 고정하며 **승인 이전 assessment는 Shadow A/B에 재사용하지 않는다.** 동일 candidate를 다시 승인해 이 경계를 재설정하는 것도 금지한다.

### Challenger v1의 허용 행동

현재 v1.5에서 challenger는 live score weight를 직접 바꾸지 않는다. 현재 assessment universe 안에서 **review tier를 한 단계만** shadow 이동한다.

- `PROMOTE_ONE_TIER`: DISCOVER → PREP → FOCUS
- `SUPPRESS_ONE_TIER`: FOCUS → PREP → DISCOVER
- FOCUS의 promote와 DISCOVER의 suppress는 더 이동하지 않는다.
- `BLOCKED`는 어떠한 shadow promotion으로도 해제하지 않는다.

규칙의 condition은 Promotion Registry의 사전등록 segment language를 그대로 사용한다. 0B MICRO 조건은 gap-free 자료에서만 match한다.

### 동일한 관측 경로

각 승인 규칙마다 같은 assessment에 대해 두 판단을 저장한다.

```text
CONTROL
= 실제 당시 Market OS watch tier

CHALLENGER
= 같은 assessment + 승인된 shadow rule
```

둘은 동일한 기준가격, 동일한 +5m/+30m/close/D+1 outcome을 공유한다. challenger를 위해 별도 가격을 선택하거나 미래자료를 condition에 사용하지 않는다.

### 비교 cohort

두 운영 관점에서 cohort composition을 비교한다.

- `FOCUS`: 최우선 검토군
- `REVIEW`: FOCUS + PREP

반복 snapshot을 독립 표본으로 세지 않고 기존 episode-anchor 규칙을 동일하게 적용한다.

각 horizon/cohort에 대해 기록:
- CONTROL / CHALLENGER N
- 종목 수 / 거래일 수
- 평균·중앙 수익률
- 양(+) 비율
- 평균 MFE / MAE
- challenger − control Δ평균수익률
- Δ양(+)비율
- ΔMAE
- 실제 cohort membership이 달라진 episode 수

### Evidence state

Shadow A/B는 적은 표본으로 승자를 선언하지 않는다.

- `NO_DIFFERENCE`: challenger가 cohort membership을 바꾸지 않음
- `COLLECTING`: 비교 표본·종목·거래일 부족
- `FORMING`: 차이는 발생하지만 아직 비교 근거가 초기 단계
- `COMPARABLE`: 양쪽 cohort와 membership change가 최소 비교 문턱을 통과

`COMPARABLE` 역시 자동 채택을 뜻하지 않는다. 이 단계는 CONTROL보다 challenger가 실제 prospective 자료에서 어떤 차이를 만들었는지 사람이 검토할 수 있다는 의미다.

### 현재 범위의 한계

v1.5는 기존 Market OS가 이미 assessment로 포착한 종목 안에서 tier priority를 시험한다. 현재 shortlist 밖의 새 종목을 challenger가 추가하는 **universe expansion 실험은 포함하지 않는다.**

Shadow Rule Lab은 live Radar / Theme / Setup / Catalyst / Trigger 계산, 실제 watch tier, 주문, 포지션, 비중을 수정하지 않는다.

## Shadow Decision Gate v1.6 — Challenger Replacement Review

Shadow Rule Lab의 평균 차이가 양수라는 이유만으로 기존 CONTROL을 교체하지 않는다. v1.6은 prospective A/B 결과가 **충분한 표본, 시간축 안정성, 실제 cohort membership 변화, 시장 stance 재현성**을 함께 통과했는지 별도로 판정한다.

### 결정 상태

```text
SHADOW_RULE
  ↓
COLLECTING
  ↓
COMPARABLE
  ↓
CONSISTENT
  ↓
ACCEPT_CANDIDATE
```

중간에 증거가 혼합되면 `MORE_DATA`, 충분한 prospective 증거에서 일관되게 악화되면 `REJECT`가 될 수 있다.

- `COLLECTING`: 30분 비교 문턱 전
- `COMPARABLE`: 30분은 비교 가능하지만 종가 또는 재현성 근거가 부족
- `CONSISTENT`: 30분·종가, 시간분할, stance 방향이 일치하지만 강한 표본 문턱 전
- `ACCEPT_CANDIDATE`: 기존 CONTROL 교체를 사람이 검토할 자격
- `MORE_DATA`: 효과가 혼합되거나 시간/stance 재현성 대기
- `REJECT`: 비교 가능한 prospective 결과에서 명확한 악화가 반복

`ACCEPT_CANDIDATE`와 `REJECT` 모두 자동으로 live 규칙을 교체하거나 Shadow Rule을 enable/disable하지 않는다.

### Primary cohort 선택

FOCUS와 REVIEW(FOCUS+PREP) 중 **실제 membership change가 더 많이 발생한 cohort**를 primary impact surface로 사용한다. 동률이면 REVIEW를 사용한다.

이 선택에는 수익률·MFE·MAE를 사용하지 않는다. 성과를 보고 유리한 cohort를 고르는 사후 선택을 피하기 위한 규칙이다.

### 기본 비교 문턱

한 horizon/cohort cell이 비교 가능하려면 CONTROL과 CHALLENGER 양쪽에서 다음을 요구한다.

- 최소 N 20
- 최소 5종목
- 최소 3거래일
- 실제 cohort membership change 최소 5건

강한 표본 문턱:

- 최소 N 40
- 최소 8종목
- 최소 6거래일
- membership change 최소 10건

### 효과 방향

Challenger − Control 기준의 기본 개선 조건:

- Δ평균수익률 ≥ +0.10%p
- Δ양(+)비율 ≥ +1.0%p
- ΔMAE ≥ 0

강한 개선 조건:

- Δ평균수익률 ≥ +0.20%p
- Δ양(+)비율 ≥ +3.0%p
- ΔMAE ≥ 0

반대 방향의 동일 문턱을 모두 충족하면 HARMFUL로 본다. 나머지는 MIXED다.

이 임계값은 현재 운영 휴리스틱이며 실제 장기 표본을 통해 재검증할 대상이다.

### Horizon 일치

결정의 핵심 horizon은 `30m`와 `close`다.

- 30m가 비교 가능하지 않으면 `COLLECTING`
- 30m만 비교 가능하고 close가 부족하면 `COMPARABLE`
- 30m와 close가 모두 HARMFUL이면 `REJECT`
- 30m와 close가 모두 BENEFICIAL이어야 다음 안정성 검증으로 이동

5m는 초기 반응 관찰용이며 v1.6의 최종 교체 판단을 지배하지 않는다. D+1은 보조 장기 관찰 자료로 유지하며 현재 ACCEPT 문턱의 필수조건은 아니다.

### 시간분할 안정성

승인 후 prospective episode를 거래일 기준 EARLY / RECENT로 나눠 다시 CONTROL과 CHALLENGER를 계산한다.

- EARLY 30m BENEFICIAL
- RECENT 30m BENEFICIAL
- 최근 30m/close가 HARMFUL이면 `REJECT`
- close 시간분할은 ACCEPT_CANDIDATE에서 양쪽 구간 모두 실제 비교 가능 + BENEFICIAL을 요구

따라서 초기 며칠만 좋고 최근에 무너진 challenger는 강한 전체평균 때문에 채택되지 않는다.

### 시장 stance 재현성

`STANCE_...`로 시작하는 stance-scoped 가설은 사전 정의된 target stance 안에서의 재현성을 본다. 다른 stance에서 효과가 없다는 이유로 감점하지 않는다.

stance를 조건에 포함하지 않는 일반 규칙은 EXPANDABLE / SELECTIVE / DEFENSIVE 중 실제 membership change가 발생하고 비교 가능한 stance에서 검증한다.

- 서로 다른 최소 2개 stance에서 BENEFICIAL 재현을 요구
- 비교 가능한 stance에서 HARMFUL이 나타나면 `MORE_DATA`
- target stance 규칙은 해당 stance에서 BENEFICIAL이어야 한다

### ACCEPT_CANDIDATE

다음을 모두 만족해야 한다.

1. 30m와 close 전체 결과 BENEFICIAL
2. 두 horizon의 강한 전체표본 문턱 통과
3. EARLY / RECENT 30m 안정
4. RECENT 30m 강한 개선
5. EARLY / RECENT close가 모두 비교 가능하고 BENEFICIAL
6. stance-scoped 규칙은 target stance 재현
7. 일반 규칙은 최소 2개 stance에서 재현

이 상태는 **사람에게 CONTROL 교체를 검토할 자격**만 부여한다. live Market OS의 Radar / Theme / Setup / Catalyst / Trigger, watch tier, 주문, 포지션 비중은 자동 변경하지 않는다.

### 감사 이력

현재 상태는 `market_os_shadow_decisions`에 저장하고, 상태 변화는 `market_os_shadow_decision_events`에 별도 기록한다.

따라서 `COLLECTING → COMPARABLE → CONSISTENT → ACCEPT_CANDIDATE` 또는 `MORE_DATA / REJECT`로 이동한 이력을 사후 감사할 수 있다.

## Adoption Review Dossier v1.7 — Evidence Before Rule Change

`ACCEPT_CANDIDATE`는 live 규칙 변경 신호가 아니다. 기존 CONTROL을 대체할 가능성을 사람이 검토할 수 있다는 뜻일 뿐이다. 따라서 다음 단계는 코드 변경이 아니라 **증거를 고정한 심사 dossier**다.

### 생성 시점과 revision

Dossier는 Shadow Decision Gate가 `ACCEPT_CANDIDATE`로 **진입한 전이 이벤트당 정확히 1개** 생성한다.

- 단순히 N이나 평균값이 조금 변했다고 새 revision을 만들지 않는다.
- Decision이 ACCEPT에서 내려가면 현재 `PENDING` dossier는 `STALE_DECISION`으로 닫는다.
- 이후 다시 `ACCEPT_CANDIDATE`로 진입하면 새로운 Decision 전이 이벤트에 연결된 다음 revision을 생성한다.
- 증거 revision은 기존 내용을 덮어쓰지 않는다.
- 아직 심사 중인 이전 revision이 새 ACCEPT 전이로 대체되는 경우 `SUPERSEDED`로 보존한다.

각 dossier는 `source_decision_event_id`와 content hash를 저장해 어떤 Decision 전이와 어떤 증거 snapshot을 검토했는지 감사 가능하게 한다.

### Dossier 구성

심사 문서에는 최소 다음을 고정한다.

1. **Shadow rule identity**
   - candidate key
   - condition
   - source horizon
   - prospective 승인 시각
   - action

2. **Decision Gate 근거**
   - 현재 Decision 상태
   - primary cohort
   - 30m / close 방향
   - 시간분할 결과
   - stance 재현성
   - reason codes

3. **Promotion source**
   - 최초 가설 방향
   - 누적 N / 종목 수 / 거래일 수
   - quality
   - walk-forward
   - EARLY / RECENT 성과

4. **CONTROL vs CHALLENGER**
   - 5m / 30m / close / D+1
   - FOCUS / REVIEW cohort
   - membership changes
   - 평균 차이
   - 양(+) 비율 차이
   - MAE 차이

5. **Impact surface**
   - 실제 tier가 바뀐 episode 수
   - DISCOVER→PREP, PREP→FOCUS 등의 transition 수
   - 영향받은 market stance 분포
   - 현재 assessment universe 내부 실험이라는 범위

6. **Counterexamples**
   - promotion rule: challenger가 올렸지만 이후 outcome이 약했던 사례
   - suppression rule: challenger가 내렸지만 이후 outcome이 좋았던 사례

7. **Known limits**
   - randomized causal experiment가 아님
   - 기존 assessment universe 밖의 종목은 포함하지 않음
   - 시장구조 drift 가능성
   - D+1은 보조 근거
   - 운영 threshold 자체도 재검증 대상

8. **Rollback criteria**
   - Decision이 `REJECT`로 하락
   - RECENT 30m 또는 close가 HARMFUL
   - 전체 30m / close BENEFICIAL 조건 붕괴
   - 비교 가능한 stance에서 HARMFUL
   - look-ahead / data-quality 통제가 잘못된 것으로 확인

### 반례 우선 심사

Dossier는 좋은 사례만 보여주지 않는다.

`PROMOTE_ONE_TIER`에서는 실제로 tier를 올렸지만 이후 30m/close outcome이 가장 약했던 사례를 반례로 먼저 저장한다.

`SUPPRESS_ONE_TIER`에서는 tier를 낮췄지만 이후 outcome이 가장 좋았던 사례를 반례로 저장한다.

이는 challenger를 정당화하기 위한 문서가 아니라 **교체하지 말아야 할 이유를 먼저 찾는 문서**다.

### 사람의 심사 상태

허용되는 review state:

- `PENDING`
- `APPROVED_DRY_RUN`
- `REJECTED`
- `SUPERSEDED`
- `STALE_DECISION`

명시적 명령:

```bash
bash market_radar/local/shadow_rule_admin.sh dossier <dossier_id>
bash market_radar/local/shadow_rule_admin.sh review <dossier_id> approve-dry-run --confirm
bash market_radar/local/shadow_rule_admin.sh review <dossier_id> reject --confirm
```

`approve-dry-run`은 현재 Shadow Decision이 여전히 `ACCEPT_CANDIDATE`이고 `review_eligible=true`일 때만 가능하다.

### APPROVED_DRY_RUN의 의미

`APPROVED_DRY_RUN`은 다음 단계를 만들 수 있다는 사람의 승인이다.

이 상태에서도:

- versioned ruleset 생성 안 함
- live Market OS threshold 변경 안 함
- 실제 watch tier 변경 안 함
- 주문/포지션/비중 변경 안 함

따라서 v1.7의 끝은 **HUMAN_APPROVED_DRY_RUN**이며, 실제 versioned ruleset과 dry-run execution은 별도 후속 단계에서만 설계한다.

### 저장 구조

현재 dossier:
- `market_os_adoption_dossiers`

심사/상태 변경 이력:
- `market_os_adoption_dossier_events`

모든 revision은 immutable evidence snapshot을 유지한다.

## Versioned Ruleset Dry Run v1.8 — CONTROL vs Candidate System

`APPROVED_DRY_RUN`은 versioned ruleset을 자동으로 만들지 않는다. 사람이 다시 명시적으로 dry run을 시작해야 한다.

```bash
bash market_radar/local/shadow_rule_admin.sh dry-run-start <dossier_id> --confirm
bash market_radar/local/shadow_rule_admin.sh ruleset <ruleset_id>
bash market_radar/local/shadow_rule_admin.sh dry-run-stop <ruleset_id> --confirm
```

### 두 번째 prospective boundary

`dry-run-start` 실행 시각을 ruleset의 `activated_at`으로 고정한다.

- 활성시각 이전 assessment는 Versioned Ruleset Dry Run에 포함하지 않는다.
- 같은 dossier에서 다시 start해 prospective boundary를 재설정하는 것을 금지한다.
- source dossier는 반드시 `APPROVED_DRY_RUN`이어야 한다.
- 시작 순간에도 source Shadow Decision이 여전히 `ACCEPT_CANDIDATE` + `review_eligible=true`인지 재검증한다.
- source Shadow Rule도 enabled 상태여야 한다.

### Candidate ruleset v1

v1.8의 candidate system은 현재 CONTROL engine을 base로 하는 immutable spec이다.

```text
base_rule_version = market-os-v1
+
Adoption Dossier에서 승인된 1개 tier overlay
=
candidate versioned ruleset
```

Ruleset spec에는 다음을 저장한다.

- spec version
- base rule version
- source dossier ID / dossier hash
- source Shadow Rule ID
- prospective_only=true
- live_activation=false
- max_tier_shift=1
- blocked_override=false
- overlay condition
- overlay action

spec 전체를 canonical JSON으로 hash해 `ruleset_id`와 `version_label`을 생성한다.

같은 dossier 증거에서 같은 spec을 만들면 동일한 hash가 나온다.

### CONTROL과 CANDIDATE

각 assessment마다:

- CONTROL tier = 실제 당시 Market OS가 저장한 `watch_tier`
- CANDIDATE tier = 같은 assessment + immutable ruleset overlay
- Radar / Theme / Setup / Catalyst / Trigger / Risk는 같은 관측값을 공유한다.
- v1.8에서는 candidate가 기존 assessment universe 밖의 종목을 추가하지 않는다.
- `BLOCKED`는 candidate overlay로 해제하지 않는다.

따라서 v1.8은 아직 base axis 계산 알고리즘 전체를 바꾸는 실험이 아니라, **현재 시스템 전체에 승인된 정책 overlay를 얹은 차기 버전 후보**를 prospective로 검증하는 단계다.

### Dry-run 저장

- ruleset 정의: `market_os_versioned_rulesets`
- 당시 CONTROL/CANDIDATE 판단: `market_os_ruleset_dry_run_observations`
- 5m/30m/close/D+1 cohort summary: `market_os_ruleset_dry_run_summary`
- 시작/중지/stale 이력: `market_os_ruleset_events`

반복 snapshot은 기존 episode-anchor 규칙을 동일하게 적용한다.

비교 cohort:
- FOCUS
- REVIEW = FOCUS + PREP

측정:
- CONTROL/CANDIDATE N
- 종목 수
- 거래일 수
- 평균/중앙값/양(+)비율
- MFE/MAE
- Δ평균
- Δ양(+)
- ΔMAE
- 실제 membership change 수

### Source stale 자동 중단

Dry Run이 활성화되어 있어도 source Shadow Decision이 더 이상 `ACCEPT_CANDIDATE`가 아니거나 `review_eligible=false`, 또는 source Shadow Rule이 disable되면:

```text
DRY_RUN_ACTIVE
→ STALE_SOURCE
```

으로 자동 전환하고 새 관측을 중단한다.

이 ruleset을 다시 활성화하지 않는다. 이후 다시 증거가 회복되면:

```text
새 ACCEPT transition
→ 새 dossier revision
→ 새 human approval
→ 새 ruleset
```

경로를 밟아 새로운 prospective boundary를 만든다.

### 상태

- `DRY_RUN_ACTIVE`: prospective candidate 관측 중
- `DRY_RUN_STOPPED`: 사람이 수동 중지
- `STALE_SOURCE`: source Decision/Shadow Rule이 무효화되어 자동 중단

### Kill switch

`MARKET_OS_RULESET_DRY_RUN_ENABLED=0`이면 새로운 ruleset observation과 summary 계산을 중단한다.

이 설정도 live CONTROL Market OS에는 영향을 주지 않는다.

### v1.8이 하지 않는 것

- live Market OS ruleset 교체 안 함
- 실제 watch tier 변경 안 함
- 주문/포지션/비중 변경 안 함
- 여러 overlay 조합 안 함
- base axis 계산식 변경 안 함
- universe expansion 안 함

v1.8의 목적은 **사람이 승인한 차기 ruleset candidate를 기존 CONTROL과 완전히 분리된 prospective 버전으로 운영 검증**하는 것이다.

