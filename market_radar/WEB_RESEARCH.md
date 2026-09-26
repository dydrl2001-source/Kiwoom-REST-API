# Market Radar — 외부 웹 조사 · AI 종합

## 구현 범위와 현재 상태

기존 deep_research_engine.py는 DB 조회 함수를 여러 분석축으로 나누고 정해진 문장을 조합하는 로컬 규칙 엔진이다. 여러 독립 LLM이 합의하는 구조가 아니며, 기존 confidence 값은 검증된 정답 확률이 아니다.

이번 추가 모듈은 OpenAI Responses API의 web_search를 실제 호출하는 연결부다. 검색·출처 대조·과거 재료 비교·반대 근거 검토를 하나의 모델 실행에서 수행하도록 요청한다. 독립된 여러 AI의 합의로 표시하지 않는다.

기본값은 비활성이다. GitHub에 코드와 테스트를 추가했지만 사용자의 Mac mini 배포 상태와 실제 API 인증/과금 호출은 개발 환경에서 검증하지 않았다. 현재 파일을 내려받는 것만으로 API 호출이 활성화되지 않는다.

## 추가 파일

- web_research_engine.py: 작업 큐, 출처 포함 응답 처리, 호출 횟수 제한, 작업기.
- radar_web_app.py: 기존 API에 별도 인증 경로와 스크립트만 추가하는 진입점.
- web_research_ui.js: 리서치 탭 상단의 색상 패널, 상태, 수동 조사, 펼쳐보기, 클릭 가능한 인용.
- local/web_research.env.example: 비활성 기본 설정 예시. 기존 .env를 이 파일로 덮어쓰지 않는다.
- local/check_web_research.sh: 키나 원문을 출력하지 않는 상태 확인.
- tests/test_web_research_engine.py, tests/test_radar_web_app.py: 오프라인 회귀 테스트.

## Mac 업데이트

```bash
(
  set -e
  cd "$HOME/Kiwoom-REST-API"
  git -c core.fileMode=false pull --ff-only
  cd market_radar/local
  docker compose up -d --build radar-api web-research-worker
  bash check_web_research.sh
)
```

충돌 시 명령이 멈춘다. git restore/reset이나 .env, Telegram session, DB 삭제를 자동으로 실행하지 않는다.

브라우저의 기존 주소에서 새로고침하고 리서치 탭을 연다. 첫 상태는 '외부 AI 꺼짐 · 추가 호출 없음'이다. 기존 로컬 요약은 아래에 유지된다. localhost는 사용자의 Mac mini에 있는 서버이며 외부 개발 환경에서 직접 열 수 있는 주소가 아니다.

## 실제 AI 사용을 선택할 때

OpenAI API 사용은 ChatGPT 구독과 별도 과금이다. 별도 API 사용에 동의한 뒤 키와 사용 가능한 모델을 Mac mini의 .env에 직접 추가한다. 키는 GitHub, 채팅, 브라우저 입력란에 붙이지 않는다.

```dotenv
WEB_RESEARCH_ENABLED=1
WEB_RESEARCH_AUTO=0
OPENAI_API_KEY=본인이_발급한_API_키
WEB_RESEARCH_MODEL=본인_계정에서_사용가능한_웹검색지원_모델
WEB_RESEARCH_DAILY_LIMIT=10
WEB_RESEARCH_HOURLY_LIMIT=2
WEB_RESEARCH_COOLDOWN_MINUTES=60
WEB_RESEARCH_MAX_TOOL_CALLS=3
WEB_RESEARCH_MAX_OUTPUT_TOKENS=3000
```

설정 변경 후 두 프로세스를 재생성한다.

```bash
docker compose up -d --force-recreate radar-api web-research-worker
```

처음에는 수동 1건으로 API 권한, 응답 시간, 인용, 실제 사용량을 확인한다. 그 뒤 WEB_RESEARCH_AUTO=1로 바꾸면 최근 15분의 높은 우선순위 작업 중 최근 가격봉이 10분 이내인 종목만 자동 큐에 들어간다. 오래된 장마감 자료의 재수집은 최근 가격봉으로 간주하지 않는다. 뉴스만 새로 생긴 장외 사건은 현재 자동 모드의 대상이 아니며 수동 조사가 가능하다.

## 호출 제한

기본은 한국시간 하루 10회, 최근 1시간 2회, 동일 종목 60분 유예다. DB에 시도 기록을 먼저 저장하고 서버 잠금으로 중복 작업을 막는다. 재시작 후에도 같은 날의 사용 기록을 유지한다.

이 제한은 이 작업기의 API 요청 수 제한이지 금액 상한을 보장하지 않는다. 한 요청 안의 검색 도구 호출과 토큰 비용이 별도 발생할 수 있고, 같은 API 키를 다른 프로그램에서 쓰는 비용은 포함하지 않는다.

타임아웃이나 연결 오류는 이미 과금됐을 가능성이 있으므로 자동 재호출하지 않는다. 완료 여부 미확인으로 남긴다. 1시간 넘게 대기한 작업은 EXPIRED로 처리한다.

## 데이터와 판단

외부 전송 정보는 종목명/코드, 관측 시각, 조회·거래대금 순위, 등락률, 공개 뉴스 제목/URL로 한정한다. Telegram 원문, 비공개 채널명, 계좌정보, 세션, DB 연결 문자열은 보내지 않는다.

거래대금·시총의 원시 단위는 기존 수집부에서 별도 검증이 필요하므로 이 단계의 AI 요청에는 금액/시총비율을 넣지 않는다. 수집 시각과 실제 가격봉 시각을 구별한다.

보고서에는 핵심 재료, 새로움과 반복, 시장 연결, 반대 근거·미확인을 요청한다. 공식 공시라는 사실만으로 가격 상승의 원인으로 확정하지 않도록 한다. 같은 기사에 함께 등장한 다른 회사의 사건, 과거 기사 재배포, 복제된 보도를 점검하도록 요청한다. 이 검토 지시는 모델의 정확성을 보장하지 않는다.

웹 검색 도구 실행과 유효한 인용 위치가 둘 다 있어야 CITED_REPORT가 된다. 이것은 출처 포함 응답이라는 뜻이지 재료의 진실성, 인과관계, 투자 성공 확률을 인증했다는 뜻이 아니다. 검색/인용이 빠진 응답은 EVIDENCE_INCOMPLETE로 분리한다. 매수·매도·비중·목표가 추천은 요청하지 않는다.

## UI

파랑은 검색, 초록은 출처 대조 단계, 주황은 반복/미확인 점검, 보라는 종합을 구분한다. 단계 표시는 작업 구조 설명이며 독립 에이전트의 실시간 진행률이 아니다. 카드에는 요청/완료 시각, 사용 모델, 검색 도구 호출 수와 인용 수를 표시한다.

기사나 모델 출력을 HTML로 실행하지 않고 textContent로 표시한다. 문장 속 인용은 클릭 가능한 링크로 보존한다. 새 모듈의 로딩/오류 처리는 기존 대시보드 스크립트와 분리했다.

## 검증 범위

개발 환경에서 19개 오프라인 단위/인증/경로 테스트와 JavaScript 문법 검사를 통과했다. Chromium의 가상 응답으로 비활성 상태, 활성 상태, 인용 링크, 악성 문자열의 텍스트 표시, 모바일 가로 넘침을 확인했다.

실제 OpenAI API 요청은 실행하지 않았고 실제 Postgres/사용자의 Mac mini 통합 테스트도 아직 수행하지 않았다. 따라서 실제 키·모델 접근·사용량·응답시간·DB 생성 여부는 최초 로컬 실행에서 확인해야 한다.

테스트용 별도 개발 환경:

```bash
python -m pip install fastapi httpx
python -m unittest discover -s market_radar/tests -p 'test_*web*.py' -v
node --check market_radar/web_research_ui.js
```

## 공식 문서

- Responses 웹 검색 및 인용: https://developers.openai.com/api/docs/guides/tools-web-search
- ChatGPT/API 별도 과금: https://help.openai.com/en/articles/9039756
