# 키움 인증 구조와 조회 전용 실행

분석/작성일: 2026-09-17. 대상: `dydrl2001-source/Kiwoom-REST-API`의 현재 `main`에서 읽은 코드.
이 문서는 GitHub 로그인과 **키움 API 인증을 구분**한다. GitHub 연결은 저장소 접근 권한이며, 키움의 App Key/Secret이나 사용자 Mac 키체인 접근 권한을 제공하지 않는다.

## 1. 현재 검증 수준

| 항목 | 결과 |
| --- | --- |
| 기존 인증 코드와 문서 검토 | 완료: 아래 파일/함수 참조 |
| 조회 전용 실행기 | `tools/kiwoom_readonly.py` 추가 |
| 오프라인 단위 테스트 | Python 3.13.5에서 23개 통과; SDK 객체는 대역 사용 |
| Python 문법 검사 | 실행기와 테스트 모두 통과 |
| 전체 SDK 설치·실행 검증 | 미완료: 작업 컨테이너에서 GitHub DNS 접근 실패, 필요한 패키지 일부 미설치 |
| 실제 토큰 발급·종목 조회 | 미검증: 작업 컨테이너에 키/토큰 없음 |
| 주문·계좌조회·원격 토큰 폐기 | 실행하지 않음 |
| 사용자 Mac 설치·상시 서버 배포 | 실행하지 않음 |

단위 테스트 성공을 키움 연결 성공으로 해석하지 않는다. 작업 컨테이너에서 실행기를 직접 호출한 결과는 `dependencies_missing`, `api_connected: false`였다. 아래 명령은 키움이 허용한 IP의 사용자 컴퓨터에서 마저 실행하는 절차다.

## 2. Mac에서 첫 연결

먼저 키움 REST API 사용 신청, 모의투자용 키 발급, 실행 컴퓨터의 외부 IP 등록을 완료한다. 실전 키와 모의투자 키를 혼용하지 않는다. 키는 채팅·GitHub 파일·이슈·명령 인자로 전달하지 않는다.

`git`과 `uv`가 설치된 Mac 터미널에서 실행한다. 기존 작업폴더를 덮어쓰지 않도록 새 폴더에 받는다. 같은 이름의 폴더가 있으면 새 이름을 사용한다.

```bash
git clone --single-branch --branch codex/kiwoom-readonly-20260917 \
  https://github.com/dydrl2001-source/Kiwoom-REST-API.git Kiwoom-readonly
cd Kiwoom-readonly
uv sync --frozen
uv run python tools/kiwoom_readonly.py --prompt
```

마지막 명령이 요구하는 App Key와 App Secret을 **이 터미널 안에서만 숨김 입력**한다. 입력 문자가 보이지 않는 것이 정상이다. 기본 모드는 `demo`; 요청 종목은 `005930`이다. 선택 이유는 저장소 예제의 연결 점검용 코드이며 투자 추천이 아니다.

실전 키만 발급받은 경우에는 실전 서버에 **종목정보 조회만** 요청하는 다음 명령을 사용한다. 주문 기능은 없다.

```bash
uv run python tools/kiwoom_readonly.py --mode real --allow-real-read --prompt
```

인증 전 로컬 코드 점검:

```bash
uv run python tools/kiwoom_readonly.py --check
```

`local_check_passed`는 설치·모드·주소 선택만 통과했다는 뜻이다. 키는 읽지 않으며 `api_connected`는 항상 `false`다. 실제 토큰 발급과 요청 종목 조회에 성공할 때만 `api_read_succeeded`, `api_connected: true`가 출력된다. 출력 주가는 API 원문 값이며, 체결 시각이나 단위·장 운영 상태를 추가 검증한 시세 서비스가 아니다.

### 기존 키를 재사용하기

이미 키체인 프로필을 설정했다면 `--prompt` 대신 명시적으로 계좌 별칭을 선택한다. 별칭은 만들거나 변경하지 않는다.

```bash
uv run python tools/kiwoom_readonly.py --profile my-demo --mode demo
```

별칭 없는 기존 모드별 키체인이나 현재 프로세스 환경변수를 사용하려면 `--prompt` 없이 실행한다. 올바른 환경변수명은 다음과 같다.

| 모드 | App Key | App Secret |
| --- | --- | --- |
| `demo` | `APP_KEY_MOCK` | `APP_SECRET_MOCK` |
| `real` | `APP_KEY` | `APP_SECRET` |

`KIWOOM_APP_KEY` 등의 다른 이름은 이 저장소의 `EnvSecretProvider`가 읽지 않는다. `.env`를 만들어 두기만 해서는 이 실행기/SDK가 자동으로 읽지 않는다. `uv run --env-file .env python ...`처럼 파일 로딩을 명시해야 하며 파일은 Git에 추가하지 않는다. 첫 점검에는 파일을 만들지 않는 `--prompt`가 더 단순하다.

`KIWOOM_PROFILE`이 이미 설정되어 있으면 이 실행기는 자동 선택을 거부하고 `--profile`을 요구한다. 숨김 입력 방식으로 전환할 때는 현재 셸에서 `unset KIWOOM_PROFILE` 후 다시 실행한다. 사전발급 토큰 변수 `KIWOOM_ACCESS_TOKEN`, `KIWOOM_ACCESS_TOKEN_EXPIRES_AT`도 첫 발급을 검증하기 위해 거부한다. 사용 중인 다른 프로세스나 저장된 프로필은 수정하지 않는다.

## 3. 인증을 담당하는 구성요소

| 파일 / 핵심 심볼 | 역할 |
| --- | --- |
| [`kiwoom/core/runtime.py`](../kiwoom/core/runtime.py): `get_auth`, `get_client`, `describe_selection` | 모드·프로필을 해석하고 자격증명 공급자, 토큰 저장소, HTTP 클라이언트를 구성 |
| [`kiwoom/core/secrets.py`](../kiwoom/core/secrets.py): `EnvSecretProvider`, `KeyringSecretProvider`, `ProfileKeyringSecretProvider`, `StaticSecretProvider` | 키를 환경변수·OS 키체인·호출자가 제공한 메모리 객체에서 읽음 |
| [`kiwoom/core/auth.py`](../kiwoom/core/auth.py): `KiwoomAuth` | 토큰 유효성 검사, 발급, 조기 재발급, Bearer 헤더 생성, 원격 폐기 |
| [`kiwoom/core/token_store.py`](../kiwoom/core/token_store.py): `FileTokenStore`, `MemoryTokenStore` | 토큰·만료시각·키 지문을 파일 또는 프로세스 메모리에 보관 |
| [`kiwoom/core/client.py`](../kiwoom/core/client.py): `KiwoomClient.request` | API ID와 Bearer 토큰을 붙여 HTTP 요청, 응답 코드 검사, 제한된 인증 재시도 |
| [`kiwoom/core/settings.py`](../kiwoom/core/settings.py) | 선택 설정, 토큰 저장 방식, 사전발급 토큰 환경변수 처리 |

프로필을 지정하지 않은 기본 자격증명 공급자는 **환경변수 → 모드별 키체인** 순서다. 프로필을 지정하면 **그 프로필의 키체인**을 사용하며 환경변수 키로 조용히 대체하지 않는다. 실제 프로필과 모드의 충돌은 오류로 처리된다.

## 4. 요청 흐름 — SDK 일반 경로

```text
호출자가 mode/profile 선택
   ↓
runtime.get_auth → SecretProvider + TokenStore
   ↓
client.request(api_id, path, body)
   ↓
auth.authorization_header → get_access_token
   ├─ 같은 자격증명의 유효한 캐시: 재사용
   └─ 캐시 없음 / 만료 임박 / 키 변경: POST /oauth2/token
   ↓
토큰·만료시각·키 지문 저장
   ↓
Authorization: Bearer <access token>
api-id: <호출할 API ID>
   ↓
키움 데이터 API 응답 → HTTP 상태 + 업무 return_code 검사
```

발급 본문은 `grant_type=client_credentials`, `appkey`, `secretkey`다. 사용자가 웹 로그인 후 콜백으로 인증 코드를 받는 흐름이 아니다. 다음은 키값을 표시하지 않은 구조 설명이다.

```python
# KiwoomAuth.refresh_access_token의 요청 구조
payload = {
    "grant_type": "client_credentials",
    "appkey": credentials.appkey,
    "secretkey": credentials.secretkey,
}
# HTTPS POST /oauth2/token → token, expires_dt 등 수신
# payload, credentials, token, authorization은 로그로 출력하지 않는다.
```

`expires_dt`는 코드에서 한국시간으로 해석해 UTC 만료시각으로 변환한다. 기본적으로 만료 **600초 전**부터 새 토큰을 발급한다. 여기서 갱신은 refresh token을 사용하는 것이 아니라 같은 키로 `/oauth2/token`을 다시 요청하는 방식이다.

일반 HTTP 클라이언트는 401이나 판별 가능한 토큰 오류에 대해 토큰을 다시 발급하고 **한 번** 재요청할 수 있다. HTTP 200이어도 업무 응답 코드가 실패이면 성공이 아니다. 이 신규 점검기는 횟수를 제한하기 위해 `retry_on_auth_failure=False`를 지정한다.

종목정보 예제 근거: [`examples/국내주식/종목정보/get_domestic_stock_info.py`](../examples/국내주식/종목정보/get_domestic_stock_info.py). 신규 실행기의 유일한 데이터 호출은 다음과 같다.

```python
auth = get_auth(mode="demo", token_store_kind="memory")
client = get_client(auth=auth, timeout_seconds=15)
response = client.request(
    api_id="ka10001",
    path="/api/dostk/stkinfo",
    body={"stk_cd": "005930"},
    method="POST",
    retry_on_auth_failure=False,
)
```

위 코드는 호출 구조 발췌다. 실제 실행기는 입력/주소/응답 검증, 예외 처리, 세션 닫기와 로컬 메모리 캐시 삭제까지 포함한다.

## 5. 키와 토큰은 어디에 남는가

**기존 SDK 기본 설정:** 토큰은 사용자 OS 캐시 경로의 JSON 파일에 저장된다. `FileTokenStore`는 파일 권한 확인과 원자적 교체를 사용하지만, 내용 자체를 암호화하지 않는다. App Key/Secret의 SHA-256 지문은 키가 달라졌는지 비교하기 위한 것이며 토큰 암호화가 아니다. 키와 토큰은 모두 민감정보로 다뤄야 한다. 자격증명 dataclass나 HTTP 요청 객체를 그대로 로깅하지 않는다.

**신규 실행기:** 토큰 저장소를 `memory`로 고정한다. `--prompt`로 받은 키도 이번 실행의 메모리에서만 사용하고 OS 키체인·`.env`·저장소에 쓰지 않는다. 기존 keychain/env 모드로 실행하면 그 원본 키는 원래 있던 곳에 그대로 남는다. 파일을 쓰지 않는 것이 메모리 덤프, 운영체제 스왑, 악성 로컬 프로세스까지 막는다는 뜻은 아니다.

정상 또는 오류 종료 시 자신의 메모리 토큰 캐시를 비우지만 `/oauth2/revoke`를 호출하지 않는다. **로컬 캐시 삭제와 키움 서버의 토큰 폐기는 별개**다. 기존 SDK의 `revoke_access_token`은 자격증명과 토큰으로 폐기 요청을 보내 성공 응답을 확인한 후 로컬 캐시를 비운다.

기존 SDK의 `PRD`/`MOCK` 환경변수는 서버 주소를 바꿀 수 있다. 신규 실행기는 키를 사용하기 전에 해당 모드의 공식 HTTPS 주소와 일치하는지 검사한다. SDK 전체에 이 제한을 적용한 것은 아니다.

## 6. MCP 경로는 별도다

[`mcp_exec/src/kiwoom_exec_mcp/server.py`](../mcp_exec/src/kiwoom_exec_mcp/server.py), [`tenant.py`](../mcp_exec/src/kiwoom_exec_mcp/tenant.py), [`tokens.py`](../mcp_exec/src/kiwoom_exec_mcp/tokens.py)를 함께 읽어야 한다.

HTTP 경로는 `X-Kiwoom-App-Key`, `X-Kiwoom-App-Secret`, `X-Kiwoom-Mode` 요청 헤더를 읽는다. **현재 `TenantCredentials.from_headers`의 모드 미지정 기본값은 `real`**이다. 이는 신규 점검기의 `demo` 기본값과 다르다. 헤더 자격증명이 없는 로컬 경로는 프로세스 환경설정/프로필을 사용하는 구조다.

헤더 경로에서는 서버가 자격증명 지문별 메모리 토큰 캐시와 동시 발급 잠금을 사용하고, 토큰을 하위 CLI 프로세스에 환경변수로 전달하도록 설계되어 있다. `KIWOOM_ACCESS_TOKEN`과 `KIWOOM_ACCESS_TOKEN_EXPIRES_AT`은 이 전달 경로에 쓰인다. 서버의 TTL과 키움 토큰 자체의 만료는 서로 다르다. 서버가 키를 받지 않는 구조가 아니므로 HTTPS, 접근 제한, 프록시 헤더 로그 제거, 운영자 신뢰가 필요하다.

`kiwoom_query`는 `read`/`account_read` 정책의 명령만 허용한다. 반면 기본 `KiwoomClient` 자체는 범용 클라이언트이며 주문을 막는 보안 경계가 아니다. 이번 작업은 MCP 서버를 외부에 공개하거나 주문 도구를 활성화하지 않는다. 외부 MCP 배포 전체의 보안 심사도 완료한 것이 아니다.

저장소 루트에는 `kiwoom` 런타임 패키지가 있지만 `kiwoomcli`의 전체 구현과 console script 설정은 없다. [`SETUP-CLI.md`](../SETUP-CLI.md)의 `uv tool install kwcli`는 별도로 배포되는 CLI를 설치하는 절차다. 신규 실행기는 그 CLI 설치를 가정하지 않고 이 체크아웃의 `kiwoom` 라이브러리를 직접 호출한다.

## 7. 테스트 재현과 제한

```bash
python -m unittest discover -s tests -v
python -m py_compile tools/kiwoom_readonly.py tests/test_kiwoom_readonly.py
```

23개 단위 테스트는 기본 demo, 실전 명시 동의, 임의 API/주문 옵션 부재, 허용 주소, 비밀값 출력 방지, 실패 응답 판정, 토큰 메모리 선택, 세션 정리, 제한시간, 비대화형 숨김 입력 차단 등을 검사한다. SDK와 네트워크 경계는 대역을 사용한다. 전체 SDK 호환성, 키움 인증, 등록 IP, 실제 종목 응답, Mac 키체인은 별도의 통합 검증이 필요하다.

공식 서비스 신청/접속 조건: https://openapi.kiwoom.com/intro/serviceInfo
공식 API 가이드: https://openapi.kiwoom.com/guide/apiguide
그 밖의 구조 설명은 위에 연결한 저장소 코드와 [`README.md`](../README.md), [`SETUP-CLI.md`](../SETUP-CLI.md)를 기준으로 한다.
