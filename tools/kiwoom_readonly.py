#!/usr/bin/env python3
"""Check local setup or authenticate and read ONE stock; never submit an order.

Run from this checkout with: uv run python tools/kiwoom_readonly.py --prompt
The default mode is demo. Keys and access tokens are not printed or written here.
"""
from __future__ import annotations

import argparse
import contextlib
import getpass
import importlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import warnings

OFFICIAL_HOSTS = {
    "demo": "https://mockapi.kiwoom.com",
    "real": "https://api.kiwoom.com",
}
API_ID = "ka10001"
API_PATH = "/api/dostk/stkinfo"


class ProbeError(Exception):
    """Only fixed, non-secret messages should be raised with this exception."""


def stock_code(value: str) -> str:
    if not re.fullmatch(r"[0-9]{6}", value):
        raise argparse.ArgumentTypeError("KRX 종목코드를 숫자 6자리로 입력하세요.")
    return value


def timeout_value(value: str) -> int:
    try:
        timeout = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("제한시간은 1~60초의 정수입니다.") from None
    if not 1 <= timeout <= 60:
        raise argparse.ArgumentTypeError("제한시간은 1~60초의 정수입니다.")
    return timeout


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="키움 인증/종목정보 1건 조회. 주문 기능 없음.")
    result.add_argument("--mode", choices=("demo", "real"), default="demo")
    result.add_argument("--allow-real-read", action="store_true",
                        help="실전 서버 조회를 명시적으로 허용합니다. 주문은 지원하지 않습니다.")
    source = result.add_mutually_exclusive_group()
    source.add_argument("--profile", help="기존 키체인 계좌 별칭(새로 만들거나 변경하지 않음)")
    source.add_argument("--prompt", action="store_true",
                        help="사용자 터미널에서 키를 숨김 입력. 이번 실행의 메모리에서만 사용.")
    result.add_argument("--code", type=stock_code, default="005930")
    result.add_argument("--timeout", type=timeout_value, default=15)
    result.add_argument("--check", action="store_true",
                        help="코드/주소/선택만 점검. 키를 읽거나 네트워크 요청을 하지 않음.")
    return result


def validate(args: argparse.Namespace) -> None:
    if args.mode == "real" and not args.allow_real_read:
        raise ProbeError("실전 조회에는 --mode real --allow-real-read를 함께 지정하세요.")
    if args.allow_real_read and args.mode != "real":
        raise ProbeError("--allow-real-read는 --mode real에서만 사용하세요.")
    if os.getenv("KIWOOM_PROFILE") and not args.profile:
        raise ProbeError("자동 계좌 선택을 막았습니다. --profile로 계좌 별칭을 직접 지정하세요.")
    if os.getenv("KIWOOM_ACCESS_TOKEN") or os.getenv("KIWOOM_ACCESS_TOKEN_EXPIRES_AT"):
        raise ProbeError("이 점검은 신규 인증을 확인합니다. 사전발급 토큰 환경변수 두 개를 해제하세요.")
    # Check the active URL before importing the SDK or resolving credentials.
    override = os.getenv("MOCK" if args.mode == "demo" else "PRD")
    if override and override.rstrip("/") != OFFICIAL_HOSTS[args.mode]:
        raise ProbeError("공식 키움 HTTPS 주소가 아닌 API 주소 설정을 차단했습니다.")


def load_sdk() -> Any:
    # Prefer this checkout, not an unrelated globally installed package.
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    return importlib.import_module("kiwoom.core.runtime")


def prompt_provider() -> Any:
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise ProbeError("숨김 입력은 사용자 Mac/PC의 터미널에서 직접 실행하세요.")
    module = importlib.import_module("kiwoom.core.secrets")
    # Refuse getpass's fallback to echoed stdin on a broken terminal.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        appkey = getpass.getpass("App Key (화면에 표시되지 않음): ")
        secretkey = getpass.getpass("App Secret (화면에 표시되지 않음): ")
    if not appkey.strip() or not secretkey.strip():
        raise ProbeError("키 또는 시크릿이 비어 있습니다. 다시 실행하세요.")
    return module.StaticSecretProvider(appkey.strip(), secretkey.strip(), source="prompt")


def probe(args: argparse.Namespace, sdk: Any) -> dict[str, Any]:
    validate(args)
    base_url = sdk.get_base_url(mode=args.mode, profile=args.profile)
    if base_url.rstrip("/") != OFFICIAL_HOSTS[args.mode]:
        raise ProbeError("선택한 모드와 공식 API 주소가 일치하지 않습니다.")
    common: dict[str, Any] = {
        "mode": args.mode,
        "operation": "stock_info_read_only",
        "api_id": API_ID,
        "token_storage": "memory",
        "orders_supported": False,
    }
    if args.check:
        return {**common, "status": "local_check_passed", "api_connected": False,
                "credentials_checked": False,
                "message": "로컬 실행 경로만 확인했습니다. 실제 인증/조회는 아직 확인하지 않았습니다."}

    options: dict[str, Any] = {"profile": args.profile, "token_store_kind": "memory"}
    if args.prompt:
        options["secret_provider"] = prompt_provider()
    auth = sdk.get_auth(mode=args.mode, **options)
    if auth.mode != args.mode:
        raise ProbeError("요청한 모드와 인증 객체의 모드가 다릅니다. 조회를 중단했습니다.")
    auth.timeout_seconds = args.timeout
    client = None
    try:
        client = sdk.get_client(auth=auth, timeout_seconds=args.timeout)
        # Fixed operation: no arbitrary API, pagination, order, account or revoke path.
        # Disable auth retry: one authentication attempt and one quote attempt at most.
        response = client.request(api_id=API_ID, path=API_PATH,
                                  body={"stk_cd": args.code}, method="POST",
                                  retry_on_auth_failure=False)
        body = response.body
        if not isinstance(body, dict) or str(body.get("return_code")) != "0":
            raise ProbeError("API가 성공 응답을 반환하지 않았습니다. 연결 성공으로 처리하지 않습니다.")
        if body.get("stk_cd") != args.code or not isinstance(body.get("stk_nm"), str) or not body["stk_nm"].strip():
            raise ProbeError("요청 종목과 응답 정보가 일치하지 않습니다. 연결 성공으로 처리하지 않습니다.")
        quote = {name: body[name] for name in ("stk_cd", "stk_nm", "cur_prc") if name in body}
        # Raw response, auth object, HTTP headers and exception text are not printed.
        return {**common, "status": "api_read_succeeded", "api_connected": True,
                "credentials_checked": True, "quote": quote}
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                client.session.close()
        # Local memory clear only. Never remotely revoke a token another app may use.
        with contextlib.suppress(Exception):
            auth.clear_token()


def safe_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, ProbeError):
        return "configuration_or_response_error", str(exc)
    if isinstance(exc, ImportError):
        return "dependencies_missing", "필수 패키지를 불러오지 못했습니다. 저장소 루트에서 uv sync --frozen을 실행하세요."
    name = type(exc).__name__
    if name == "CredentialsNotFoundError":
        return "credentials_missing", "키가 없습니다. --prompt로 사용자 터미널에서 숨김 입력하거나 올바른 환경변수/계좌 별칭을 설정하세요."
    if name in {"ConnectionError", "Timeout", "ConnectTimeout", "ReadTimeout", "SSLError", "ProxyError"}:
        return "network_error", "통신에 실패했습니다. 인터넷, 인증서, 방화벽과 키움 허용 IP 설정을 확인하세요."
    if isinstance(exc, ValueError):
        return "selection_error", "계좌 별칭과 demo/real 모드 등 설정이 맞는지 확인하세요."
    return "authentication_or_api_error", "인증 또는 조회에 실패했습니다. 키의 demo/real 구분, 사용 신청, 허용 IP를 확인하세요. 비밀값 보호를 위해 원본 오류는 출력하지 않습니다."


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        validate(args)
        result = probe(args, load_sdk())
    except (KeyboardInterrupt, EOFError):
        result = {"status": "cancelled", "api_connected": False,
                  "message": "사용자가 입력 또는 실행을 취소했습니다."}
        code = 130
    except Exception as exc:
        category, message = safe_error(exc)
        result = {"status": category, "api_connected": False, "message": message}
        code = 2
    else:
        code = 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
