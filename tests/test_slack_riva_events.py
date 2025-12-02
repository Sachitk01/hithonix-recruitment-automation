import asyncio
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from main import app
import slack_riva


@pytest.fixture()
def test_client():
    with TestClient(app) as client:
        yield client


def _sign_headers(secret: str, body: str) -> dict:
    timestamp = str(int(time.time()))
    base_string = f"v0:{timestamp}:{body}"
    signature = "v0=" + hmac.new(secret.encode(), base_string.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": signature,
        "Content-Type": "application/json",
    }


def test_riva_url_verification(monkeypatch, test_client):
    secret = "riva-secret"
    monkeypatch.setattr(slack_riva, "SLACK_RIVA_SIGNING_SECRET", secret)
    body = json.dumps({"type": "url_verification", "challenge": "test-challenge"})
    headers = _sign_headers(secret, body)

    response = test_client.post("/slack-riva/events", data=body, headers=headers)

    assert response.status_code == 200
    assert response.json()["challenge"] == "test-challenge"


def test_riva_event_callback_dispatch(monkeypatch, test_client):
    secret = "riva-secret"
    monkeypatch.setattr(slack_riva, "SLACK_RIVA_SIGNING_SECRET", secret)
    monkeypatch.setattr(slack_riva, "BOT_USER_ID_RIVA", "URIVA")

    captured_event = {}

    async def fake_dispatch(event):
        captured_event["payload"] = event

    monkeypatch.setattr(slack_riva, "_dispatch_riva_event", fake_dispatch)

    created_task = {}

    def fake_create_task(coro):
        created_task["coro"] = coro
        class _Dummy:
            def cancel(self):
                pass
        return _Dummy()

    monkeypatch.setattr(slack_riva.asyncio, "create_task", fake_create_task)

    payload = {
        "type": "event_callback",
        "event": {
            "type": "message",
            "channel_type": "im",
            "user": "U123",
            "channel": "D123",
            "text": "hi",
        },
    }
    body = json.dumps(payload)
    headers = _sign_headers(secret, body)

    response = test_client.post("/slack-riva/events", data=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"ok": True}

    # Run the captured coroutine to completion to assert dispatch behavior
    assert "coro" in created_task
    asyncio.run(created_task["coro"])

    assert captured_event["payload"] == payload["event"]
