"""Offline unit tests: SDK boundaries are mocked, not live Kiwoom integration tests."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "tools" / "kiwoom_readonly.py"
SPEC = importlib.util.spec_from_file_location("kiwoom_readonly", SOURCE)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.auth = SimpleNamespace(mode="demo", timeout_seconds=30, clear_token=Mock())
        self.client = SimpleNamespace(
            request=Mock(return_value=SimpleNamespace(body={
                "return_code": 0, "stk_cd": "005930", "stk_nm": "테스트종목",
                "cur_prc": "12345", "token": "DO-NOT-PRINT", "other": "private",
            })), session=SimpleNamespace(close=Mock()))
        self.sdk = SimpleNamespace(
            get_base_url=Mock(return_value=runner.OFFICIAL_HOSTS["demo"]),
            get_auth=Mock(return_value=self.auth), get_client=Mock(return_value=self.client))

    def args(self, *values):
        return runner.parser().parse_args(list(values))

    def test_default_is_demo(self):
        self.assertEqual(self.args().mode, "demo")

    def test_real_requires_explicit_opt_in(self):
        with self.assertRaises(runner.ProbeError):
            runner.probe(self.args("--mode", "real"), self.sdk)
        self.sdk.get_auth.assert_not_called()

    def test_real_read_only_is_supported_explicitly(self):
        self.sdk.get_base_url.return_value = runner.OFFICIAL_HOSTS["real"]
        self.auth.mode = "real"
        result = runner.probe(self.args("--mode", "real", "--allow-real-read"), self.sdk)
        self.assertFalse(result["orders_supported"])
        self.assertEqual(result["mode"], "real")

    def test_real_flag_cannot_be_used_in_demo(self):
        with self.assertRaises(runner.ProbeError):
            runner.probe(self.args("--allow-real-read"), self.sdk)

    def test_check_never_reads_credentials_or_calls_api(self):
        result = runner.probe(self.args("--check", "--prompt"), self.sdk)
        self.sdk.get_auth.assert_not_called()
        self.sdk.get_client.assert_not_called()
        self.assertFalse(result["api_connected"])
        self.assertFalse(result["credentials_checked"])

    def test_ambient_profile_is_not_selected_silently(self):
        os.environ["KIWOOM_PROFILE"] = "other-account"
        with self.assertRaises(runner.ProbeError):
            runner.probe(self.args(), self.sdk)
        self.sdk.get_auth.assert_not_called()

    def test_explicit_profile_is_forwarded(self):
        runner.probe(self.args("--profile", "my-demo"), self.sdk)
        self.sdk.get_auth.assert_called_once_with(mode="demo", profile="my-demo", token_store_kind="memory")

    def test_wrong_endpoint_rejected_before_credentials(self):
        self.sdk.get_base_url.return_value = "https://example.invalid"
        with self.assertRaises(runner.ProbeError):
            runner.probe(self.args(), self.sdk)
        self.sdk.get_auth.assert_not_called()

    def test_endpoint_override_rejected_before_sdk_import(self):
        os.environ["MOCK"] = "http://mockapi.kiwoom.com"
        with patch.object(runner, "load_sdk") as load, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(runner.main(["--check"]), 2)
        load.assert_not_called()

    def test_preissued_tokens_not_used_to_fake_new_auth(self):
        for name in ("KIWOOM_ACCESS_TOKEN", "KIWOOM_ACCESS_TOKEN_EXPIRES_AT"):
            with self.subTest(name=name), patch.dict(os.environ, {name: "hidden"}):
                with self.assertRaises(runner.ProbeError):
                    runner.probe(self.args(), self.sdk)

    def test_only_fixed_read_operation_is_called_once(self):
        result = runner.probe(self.args(), self.sdk)
        self.assertTrue(result["api_connected"])
        self.client.request.assert_called_once_with(
            api_id="ka10001", path="/api/dostk/stkinfo", body={"stk_cd": "005930"},
            method="POST", retry_on_auth_failure=False)
        self.sdk.get_auth.assert_called_once_with(mode="demo", profile=None, token_store_kind="memory")
        self.client.session.close.assert_called_once()
        self.auth.clear_token.assert_called_once()
        self.assertNotIn("DO-NOT-PRINT", json.dumps(result))
        self.assertNotIn("private", json.dumps(result))

    def test_string_success_code_allowed(self):
        self.client.request.return_value.body["return_code"] = "0"
        self.assertTrue(runner.probe(self.args(), self.sdk)["api_connected"])

    def test_http_success_without_valid_business_success_is_failure(self):
        for value in (None, 3, "8005", False, True):
            with self.subTest(value=value):
                self.client.request.return_value.body["return_code"] = value
                with self.assertRaises(runner.ProbeError):
                    runner.probe(self.args(), self.sdk)

    def test_wrong_stock_is_failure(self):
        self.client.request.return_value.body["stk_cd"] = "000000"
        with self.assertRaises(runner.ProbeError):
            runner.probe(self.args(), self.sdk)

    def test_missing_stock_name_is_failure(self):
        self.client.request.return_value.body.pop("stk_nm")
        with self.assertRaises(runner.ProbeError):
            runner.probe(self.args(), self.sdk)

    def test_timeout_is_applied(self):
        runner.probe(self.args("--timeout", "7"), self.sdk)
        self.assertEqual(self.auth.timeout_seconds, 7)
        self.sdk.get_client.assert_called_once_with(auth=self.auth, timeout_seconds=7)

    def test_session_and_memory_are_cleaned_on_failure(self):
        self.client.request.side_effect = RuntimeError("hidden")
        with self.assertRaises(RuntimeError):
            runner.probe(self.args(), self.sdk)
        self.client.session.close.assert_called_once()
        self.auth.clear_token.assert_called_once()

    def test_errors_never_print_raw_secret_text(self):
        self.sdk.get_auth.side_effect = RuntimeError("SECRET-MUST-NOT-APPEAR")
        stream = io.StringIO()
        with patch.object(runner, "load_sdk", return_value=self.sdk), contextlib.redirect_stdout(stream):
            self.assertEqual(runner.main([]), 2)
        self.assertNotIn("SECRET-MUST-NOT-APPEAR", stream.getvalue())
        self.assertFalse(json.loads(stream.getvalue())["api_connected"])

    def test_dependency_error_is_reported_without_success(self):
        with patch.object(runner, "load_sdk", side_effect=ModuleNotFoundError("keyring")), contextlib.redirect_stdout(io.StringIO()) as stream:
            self.assertEqual(runner.main(["--check"]), 2)
        self.assertEqual(json.loads(stream.getvalue())["status"], "dependencies_missing")

    def test_hidden_prompt_refuses_non_tty(self):
        with patch.object(runner.sys.stdin, "isatty", return_value=False):
            with self.assertRaises(runner.ProbeError):
                runner.prompt_provider()

    def test_invalid_stock_or_timeout_rejected(self):
        for values in (("--code", "../order"), ("--code", "12345"), ("--timeout", "0"), ("--timeout", "61"), ("--timeout", "abc")):
            with self.subTest(values=values), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.args(*values)

    def test_order_or_arbitrary_api_option_does_not_exist(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.args("--api-id", "kt10000")

    def test_prompt_and_profile_are_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.args("--prompt", "--profile", "my-demo")


if __name__ == "__main__":
    unittest.main()
