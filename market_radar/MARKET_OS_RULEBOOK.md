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

