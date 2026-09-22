# Market Radar V2

## 화면 구조
- 홈: 오늘 장세, RADAR 해석, 조회관심 집중 섹터, 급부상 종목
- 조회순위: Kiwoom 실시간종목조회순위
- 섹터: 조회상위 종목의 섹터 집중 순위 + 공식 업종 데이터
- 거래대금: 거래대금 순위를 조회순위와 분리
- 재료·뉴스: Telegram + 외부뉴스를 종목별로 합쳐 요약/상태/근거 제공
- 미모사: 분봉·일봉 데이터를 별도 수집해 상태 분류

## 데이터 흐름
Kiwoom Feed -> rank/trade/sector
Chart Feed -> 3분봉 + 일봉
Telegram Collector + News Feed -> catalyst evidence
Market Regime -> market state
Mimosa Engine -> chart_states
Radar API -> V2 UI

## 미모사 기반 내부 상태
아래 명칭은 원 강의의 공식 용어를 그대로 복제한 분류표가 아니라, 강의 원칙을 시스템에서 다루기 위해 만든 내부 상태명이다.

- M_CONTRACTION: M 수렴
- M_BREAKOUT_TEST: M 수렴 후 돌파 시도
- PREV_HIGH_APPROACH: 전고점 접근
- NEW_HIGH: 일봉 신고가/전고 돌파
- BREAKOUT_HOLD: 돌파 후 지지
- PULLBACK_INTACT: 분봉 추세 유지
- BREAKOUT_FAIL: 전고 돌파 실패
- TREND_DAMAGE: 분봉 추세 훼손

근거로 반영한 핵심 원칙:
- 미모사 2강: 삼각수렴, M 타점, 주도주/신규주의 급등 초입
- 5강 강사 피드백: 거래대금이 큰 당일 주도주, 신고가 돌파, 연속 상승 주도주, 분봉 추세가 아래로 꺾이면 안 됨
- 거래대금·신고가만으로 끝내지 않고 추가적인 재료/근거를 확인

## 주의
- 상태는 매수/매도 추천이 아니라 관찰용 구조화다.
- 시총대비 거래대금 단위는 첫 실전장 샘플 검증 전까지 잠정값으로 표시한다.
- 재료 요약은 현재 규칙 기반/헤드라인 기반이며, 별도 LLM 연결 전에는 ChatGPT 생성 요약으로 표기하지 않는다.
