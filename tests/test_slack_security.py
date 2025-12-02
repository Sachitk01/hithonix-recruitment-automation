import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException, Request

from slack_security import verify_slack_request


def _build_request(timestamp: str, signature: str) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/slack/test",
        "headers": [
            (b"x-slack-request-timestamp", timestamp.encode("utf-8")),
            (b"x-slack-signature", signature.encode("utf-8")),
        ],
    }

    async def receive():  # pragma: no cover - unused but required by interface
        return {"type": "http.request"}

    return Request(scope, receive)


def _sign_payload(signing_secret: str, timestamp: str, body: bytes) -> str:
    base_string = f"v0:{timestamp}:{body.decode('utf-8')}"
    digest = hmac.new(signing_secret.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha256)
    return "v0=" + digest.hexdigest()


def test_verify_slack_request_accepts_valid_signature():
    body = b"token=abc&text=hello"
    timestamp = str(int(time.time()))
    secret = "test-secret"
    signature = _sign_payload(secret, timestamp, body)

    request = _build_request(timestamp, signature)
    # Should not raise
    verify_slack_request(request, body, secret)


def test_verify_slack_request_rejects_mismatched_signature():
    body = b"token=abc&text=hello"
    timestamp = str(int(time.time()))
    secret = "test-secret"
    bad_signature = "v0=" + "0" * 64

    request = _build_request(timestamp, bad_signature)

    with pytest.raises(HTTPException):
        verify_slack_request(request, body, secret)


def test_verify_slack_request_rejects_expired_timestamp(monkeypatch):
    body = b"token=abc&text=hello"
    timestamp = "100"
    secret = "test-secret"
    signature = _sign_payload(secret, timestamp, body)

    request = _build_request(timestamp, signature)

    # Force current time far from timestamp to trigger expiry check
    monkeypatch.setattr(time, "time", lambda: 1_000_000)

    with pytest.raises(HTTPException):
        verify_slack_request(request, body, secret)


def test_verify_slack_request_rejects_wrong_secret():
    body = b"token=abc&text=hello"
    timestamp = str(int(time.time()))
    request_secret = "test-secret"
    provided_secret = "other-secret"
    signature = _sign_payload(request_secret, timestamp, body)

    request = _build_request(timestamp, signature)

    with pytest.raises(HTTPException) as exc:
        verify_slack_request(request, body, provided_secret)

    assert exc.value.status_code == 401


def test_verify_slack_request_requires_headers():
    body = b"token=abc&text=hello"
    secret = "test-secret"

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/slack/test",
        "headers": [],
    }

    async def receive():  # pragma: no cover - unused but required by interface
        return {"type": "http.request"}

    request = Request(scope, receive)

    with pytest.raises(HTTPException) as exc:
        verify_slack_request(request, body, secret)

    assert exc.value.status_code == 401
