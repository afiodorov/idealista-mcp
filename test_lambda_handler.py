"""HTTP, process isolation, timeout and credential-redaction regression checks."""

import base64
import json
import io
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

import lambda_handler as bridge


class BridgeTests(unittest.TestCase):
    def setUp(self):
        bridge._config_root = None
        bridge._secrets = []
        self.env = patch.dict(os.environ, {
            "IDEALISTA_CLIENT_KEY": "test-client-key",
            "IDEALISTA_CLIENT_SECRET": "test-client-secret",
            "IDEALISTA_SIGNING_SECRET": "test-signing-secret",
            "AUTH_SIGNING_KEY": "test-github-key",
            "AWS_SECRET_ACCESS_KEY": "must-not-reach-child",
            "IDEALISTA_DEBUG": "1",
            "APP_HANDLER": "lambda_handler.handler",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.cleanup_config)

    def cleanup_config(self):
        if bridge._config_root:
            shutil.rmtree(bridge._config_root)
        bridge._config_root = None

    def event(self, message=None, method="POST"):
        return {"requestContext": {"http": {"method": method}}, "rawPath": "/idealista/mcp",
                "body": json.dumps(message or {"jsonrpc": "2.0", "id": 7, "method": "tools/list"})}

    def child_response(self, **fields):
        return subprocess.CompletedProcess([], 0, json.dumps({"jsonrpc": "2.0", "id": 7, **fields}) + "\n", "")

    def test_protocol_roundtrip_and_private_cached_config(self):
        result = {"tools": [{"name": "search_ads"}]}
        with patch.object(bridge.subprocess, "run", return_value=self.child_response(result=result)) as child:
            response = bridge.handler(self.event(), None)
            self.assertEqual(json.loads(response["body"])["result"], result)
            first_root = bridge._config_root
            bridge.handler(self.event(), None)
        self.assertEqual(first_root, bridge._config_root)
        config = first_root / "idealista-mcp/config.json"
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(first_root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads(config.read_text())["signing_secret"], "test-signing-secret")
        environment = child.call_args.kwargs["env"]
        self.assertEqual(set(environment), {"XDG_CONFIG_HOME", "PATH"})
        self.assertNotIn("test-client-secret", str(child.call_args.args))

    def test_base64_function_url_body(self):
        event = self.event()
        event.update(body=base64.b64encode(event["body"].encode()).decode(), isBase64Encoded=True)
        with patch.object(bridge.subprocess, "run", return_value=self.child_response(result={})):
            self.assertEqual(bridge.handler(event, None)["statusCode"], 200)

    def test_bad_payloads_do_not_start_process(self):
        for body in ["{", "[]", "null", '"text"', '{"jsonrpc":"2.0","method":2}',
                     '{"jsonrpc":"2.0","method":"tools/list","params":[]}']:
            with self.subTest(body=body), patch.object(bridge.subprocess, "run") as child:
                event = self.event()
                event["body"] = body
                self.assertEqual(bridge.handler(event, None)["statusCode"], 400)
                child.assert_not_called()

    def test_lifecycle_notification_and_preflight(self):
        with patch.object(bridge.subprocess, "run") as child:
            event = self.event({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self.assertEqual(bridge.handler(event, None)["statusCode"], 202)
            self.assertEqual(bridge.handler(self.event(method="OPTIONS"), None)["statusCode"], 204)
            self.assertEqual(bridge.handler(self.event(method="GET"), None)["statusCode"], 405)
            child.assert_not_called()

    def test_timeout_respects_lambda_remaining_time(self):
        class Context:
            def get_remaining_time_in_millis(self):
                return 8000
        with patch.object(bridge.subprocess, "run", side_effect=subprocess.TimeoutExpired("binary", 7)) as child:
            response = bridge.handler(self.event(), Context())
        self.assertEqual(response["statusCode"], 504)
        self.assertEqual(child.call_args.kwargs["timeout"], 7)

    def test_credentials_and_cached_token_are_redacted(self):
        bridge.child_environment()
        (bridge._config_root / "idealista-mcp/session.json").write_text(json.dumps({"access_token": "private-bearer-token"}))
        error = {"code": -32603, "message": "test-client-secret private-bearer-token test-signing-secret"}
        with patch.object(bridge.subprocess, "run", return_value=self.child_response(error=error)):
            response = bridge.handler(self.event(), None)
        self.assertNotIn("test-client-secret", response["body"])
        self.assertNotIn("private-bearer-token", response["body"])
        self.assertNotIn("test-signing-secret", response["body"])

    def test_child_failure_hides_stderr(self):
        failed = subprocess.CompletedProcess([], 1, "", "test-client-secret")
        with patch.object(bridge.subprocess, "run", return_value=failed):
            response = bridge.handler(self.event(), None)
        self.assertEqual(response["statusCode"], 502)
        self.assertNotIn("test-client-secret", response["body"])

    def test_error_log_has_status_without_query_or_credentials(self):
        message = {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {
            "name": "search_locations", "arguments": {"prefix": "private-search"}}}
        error = {"code": -32603, "message": "API returned 400: test-client-secret private-search"}
        output = io.StringIO()
        with patch.object(bridge.subprocess, "run", return_value=self.child_response(error=error)), redirect_stdout(output):
            bridge.handler(self.event(message), None)
        entry = json.loads(output.getvalue())
        self.assertEqual(entry["tool"], "search_locations")
        self.assertEqual(entry["outcome"], "error")
        self.assertEqual(entry["api_status"], 400)
        self.assertNotIn("private-search", output.getvalue())
        self.assertNotIn("test-client-secret", output.getvalue())



if __name__ == "__main__":
    unittest.main()
