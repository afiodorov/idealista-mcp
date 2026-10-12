"""Stateless Streamable HTTP adapter for the Idealista stdio binary.

Deploy behind an authentication gate. Each request gets a fresh child process, while
the upstream OAuth token/device cache survives in the Lambda's private /tmp.
The upstream binary owns all MCP schemas, validation, signing and API calls.
"""

import base64
import binascii
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import urllib.parse

BINARY = Path(__file__).with_name("idealista-mcp")
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Accept, Authorization, Mcp-Session-Id, Mcp-Protocol-Version",
    "Access-Control-Expose-Headers": "Mcp-Protocol-Version, WWW-Authenticate",
}
_config_root = None
_secrets = []


def child_environment():
    global _config_root, _secrets
    if _config_root is None:
        config = {field: os.environ[env] for field, env in {
            "client_key": "IDEALISTA_CLIENT_KEY",
            "client_secret": "IDEALISTA_CLIENT_SECRET",
            "signing_secret": "IDEALISTA_SIGNING_SECRET",
        }.items()}
        if not all(config.values()):
            raise ValueError("Idealista credentials are not configured")
        root = Path(tempfile.mkdtemp(prefix="idealista-"))
        folder = root / "idealista-mcp"
        folder.mkdir(mode=0o700)
        with open(folder / "config.json", "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
            json.dump(config, stream)
        _secrets = list(config.values())
        _secrets += [urllib.parse.quote_plus(v) for v in config.values()]
        _secrets.append(base64.b64encode((urllib.parse.quote_plus(config["client_key"]) + ":" +
                                        urllib.parse.quote_plus(config["client_secret"])).encode()).decode())
        _config_root = root
    # Do not pass AWS credentials, the GitHub signing key, or debug flags to the child.
    return {"XDG_CONFIG_HOME": str(_config_root), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}


def redact(text):
    secrets = list(_secrets)
    if _config_root is not None:
        try:
            token = json.loads((_config_root / "idealista-mcp/session.json").read_text()).get("access_token")
            if token:
                secrets.append(token)
        except (OSError, ValueError):
            pass
    for value in sorted(set(secrets), key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    return text


def rpc_error(identifier, code, message):
    return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}


def http(status, body=None):
    return {"statusCode": status, "headers": {**CORS, "Content-Type": "application/json", "Cache-Control": "no-store"},
            "body": json.dumps(body) if body is not None else ""}


def log_response(message, response):
    """Log diagnostic status without request arguments, headers or API bodies."""
    result = response.get("result") or {}
    failed = "error" in response or bool(result.get("isError"))
    entry = {"event": "idealista_rpc", "method": message["method"],
             "outcome": "error" if failed else "ok"}
    if message["method"] == "tools/call":
        name = (message.get("params") or {}).get("name")
        known = {"search_locations", "search_ads", "get_ad_details", "get_ad_details_by_url", "get_ad_stats"}
        entry["tool"] = name if isinstance(name, str) and name in known else "unknown"
    if "error" in response:
        entry["rpc_code"] = response["error"].get("code")
    if failed:
        status = re.search(r"returned ([1-5][0-9]{2}):", json.dumps(response))
        if status:
            entry["api_status"] = int(status[1])
    print(json.dumps(entry))


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "POST")
    if method == "OPTIONS":
        return http(204)
    if method != "POST":
        return http(405, rpc_error(None, -32000, "POST JSON-RPC here; SSE and sessions are not supported"))
    body = event.get("body") or ""
    try:
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body, validate=True).decode()
        message = json.loads(body)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return http(400, rpc_error(None, -32700, "Parse error"))
    if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)):
        return http(400, rpc_error(None, -32600, "Expected one JSON-RPC request"))
    if "params" in message and not isinstance(message["params"], dict):
        return http(400, rpc_error(message.get("id"), -32602, "params must be an object"))
    if "id" not in message:
        return http(202)  # Stateless lifecycle notifications require no work.
    identifier = message["id"]
    if isinstance(identifier, (dict, list, bool)):
        return http(400, rpc_error(None, -32600, "Invalid request id"))
    timeout = 55
    if context is not None:
        timeout = max(0.1, min(timeout, context.get_remaining_time_in_millis() / 1000 - 1))
    try:
        result = subprocess.run([str(BINARY)], input=json.dumps(message) + "\n", text=True,
                                capture_output=True, timeout=timeout, env=child_environment())
        if result.returncode:
            raise RuntimeError("MCP process failed")
        # Upstream owns protocol-version negotiation and all the tool responses.
        responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        response = next(r for r in responses if r.get("id") == identifier and ("result" in r or "error" in r))
        response = json.loads(redact(json.dumps(response)))
    except subprocess.TimeoutExpired:
        print("idealista request timed out")
        return http(504, rpc_error(identifier, -32000, "Idealista request timed out"))
    except (OSError, ValueError, KeyError, RuntimeError, StopIteration):
        # Never log child stderr or the exception: either may contain credentials.
        print("idealista adapter failed")
        return http(502, rpc_error(identifier, -32603, "Idealista MCP process failed"))
    log_response(message, response)
    return http(200, response)
