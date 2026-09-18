# -*- coding: utf-8 -*-
"""Talk to 课件工作室 courseware Agent. Token from JX_TOKEN, never from the repo.

Never call production https://jx-admin.zmexing.com/mymath.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

PRODUCTION_HOST = "jx-admin.zmexing.com"
TEST_BASE = "https://test-jx-admin.zmexing.com/mymath"
POLL_SEC = 2.0
POLL_TIMEOUT_SEC = 300.0


def resolve_base(explicit: str | None = None) -> str:
    raw = (explicit or os.environ.get("JX_BASE") or TEST_BASE).strip().rstrip("/")
    host = raw.split("://", 1)[-1].split("/", 1)[0].lower()
    if host == PRODUCTION_HOST:
        raise SystemExit(
            "拒绝访问生产环境 https://jx-admin.zmexing.com/mymath ，一步也不要调。"
        )
    return raw


class JxError(Exception):
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body}")


def get_token(explicit: str | None = None) -> str:
    token = (explicit or os.environ.get("JX_TOKEN") or "").strip()
    if not token:
        raise SystemExit(
            "没有 token。请在浏览器打开 https://test-jx-admin.zmexing.com/mymath/token ，复制后设置 JX_TOKEN，或把 token 发给我。"
        )
    return token


def request_json(
    method: str,
    path: str,
    token: str,
    body: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> Any:
    base = resolve_base()
    url = base + path
    headers = {
        "Cookie": f"jx_token={token}",
        "x-device-id": "d_ai",
        "x-trace-id": uuid.uuid4().hex[:16],
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(raw) if raw else {"error": raw}
        except json.JSONDecodeError:
            parsed = {"error": raw}
        if exc.code == 401:
            raise JxError(401, "token 失效，请到测试环境 /token 重新获取") from exc
        raise JxError(exc.code, parsed) from exc


def fetch_courseware(course_id: str, token: str) -> Any:
    return request_json("GET", f"/api/x/courseware/{course_id}", token)


def post_agent(course_id: str, message: str, token: str, model_id: str | None = None) -> Any:
    payload: dict[str, Any] = {"message": message}
    if model_id:
        payload["modelId"] = model_id
    return request_json("POST", f"/api/x/courseware/{course_id}/agent", token, payload)


def poll_agent(course_id: str, token: str) -> Any:
    return request_json("GET", f"/api/x/courseware/{course_id}/agent", token)


def send_and_wait(
    course_id: str,
    message: str,
    token: str,
    *,
    model_id: str | None = None,
    interval: float = POLL_SEC,
    timeout: float = POLL_TIMEOUT_SEC,
) -> dict[str, Any]:
    post_agent(course_id, message, token, model_id=model_id)
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        time.sleep(interval)
        got = poll_agent(course_id, token) or {}
        if not isinstance(got, dict):
            last = {"raw": got}
            continue
        last = got
        if not got.get("streaming"):
            return got
    raise TimeoutError(f"agent poll timed out after {timeout:.0f}s; last={last}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Send a message to the courseware Agent")
    parser.add_argument("--course-id", required=True, help="测试环境课件 ID")
    parser.add_argument("--message", help="message text")
    parser.add_argument("--message-file", help="UTF-8 file with the message")
    parser.add_argument("--model-id", help="optional provider/model")
    parser.add_argument("--token", help="jx_token; default env JX_TOKEN")
    parser.add_argument("--timeout", type=float, default=POLL_TIMEOUT_SEC)
    args = parser.parse_args()
    resolve_base()
    if args.message_file:
        message = Path(args.message_file).read_text(encoding="utf-8")
    elif args.message:
        message = args.message
    else:
        print("need --message or --message-file", file=sys.stderr)
        return 1
    if not message.strip():
        print("empty message", file=sys.stderr)
        return 1
    token = get_token(args.token)
    try:
        result = send_and_wait(
            str(args.course_id),
            message,
            token,
            model_id=args.model_id,
            timeout=args.timeout,
        )
    except JxError as exc:
        print(json.dumps({"ok": False, "status": exc.status, "error": exc.body}, ensure_ascii=False))
        return 1
    except TimeoutError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    out = {
        "ok": True,
        "course_id": str(args.course_id),
        "text": result.get("text"),
        "error": result.get("error"),
        "tools": result.get("tools") or [],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
