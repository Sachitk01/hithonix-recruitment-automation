"""Shared helpers for validating Slack signatures."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Optional

from fastapi import HTTPException, Request


def verify_slack_request(request: Request, body: bytes, signing_secret: Optional[str]) -> None:
    """Validate Slack signature headers for an incoming request."""
    if not signing_secret:
        raise HTTPException(status_code=500, detail="Slack signing secret not configured")

    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    signature = request.headers.get("X-Slack-Signature")

    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")

    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=401, detail="Invalid Slack timestamp") from exc

    current = int(time.time())
    if abs(current - timestamp_int) > 60 * 5:
        raise HTTPException(status_code=401, detail="Slack request timestamp expired")

    try:
        decoded_body = body.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=400, detail="Invalid Slack payload encoding") from exc

    base_string = f"v0:{timestamp}:{decoded_body}"
    expected = "v0=" + hmac.new(
        signing_secret.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Slack signature mismatch")
