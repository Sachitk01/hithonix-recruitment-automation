from types import SimpleNamespace

import pytest

import slack_riva_handlers as handlers


pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def immediate_to_thread(monkeypatch):
    async def immediate(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(handlers, "to_thread", SimpleNamespace(run_sync=immediate))


class StubWebClient:
    def __init__(self):
        self.calls = []

    def chat_postMessage(self, *, channel, text):
        self.calls.append({"channel": channel, "text": text})


class StubSlackClient:
    def __init__(self):
        self.calls = []

    def post_message(self, text, channel):
        self.calls.append({"channel": channel, "text": text})


@pytest.fixture()
def anyio_backend():
    return "asyncio"


async def test_riva_dm_sends_ack_and_runs_pipeline(monkeypatch):
    ack_client = StubWebClient()
    monkeypatch.setattr(handlers, "_riva_web_client", ack_client)

    pipeline_calls = []

    def fake_pipeline(text, channel, user):
        pipeline_calls.append((text, channel, user))

    monkeypatch.setattr(handlers, "_run_riva_pipeline", fake_pipeline)

    event = {
        "type": "message",
        "channel_type": "im",
        "user": "U123",
        "channel": "D123",
        "text": "help",
    }

    await handlers.handle_riva_event(event)

    assert ack_client.calls
    assert ack_client.calls[0]["channel"] == "D123"
    assert pipeline_calls == [("help", "D123", "U123")]


async def test_riva_dm_pipeline_error_posts_message(monkeypatch, caplog):
    ack_client = StubWebClient()
    monkeypatch.setattr(handlers, "_riva_web_client", ack_client)

    def failing_pipeline(*_):
        raise RuntimeError("boom")

    monkeypatch.setattr(handlers, "_run_riva_pipeline", failing_pipeline)

    slack_client = StubSlackClient()
    monkeypatch.setattr(handlers, "riva_slack_client", slack_client)

    event = {
        "type": "message",
        "channel_type": "im",
        "user": "U123",
        "channel": "D123",
        "text": "help",
    }

    with caplog.at_level("ERROR"):
        await handlers.handle_riva_event(event)

    assert "riva_dm_pipeline_crashed" in caplog.text
    assert slack_client.calls
    assert slack_client.calls[0]["channel"] == "D123"


async def test_riva_ignores_bot_messages(monkeypatch):
    ack_client = StubWebClient()
    monkeypatch.setattr(handlers, "_riva_web_client", ack_client)

    pipeline_called = False

    def fake_pipeline(*_):
        nonlocal pipeline_called
        pipeline_called = True

    monkeypatch.setattr(handlers, "_run_riva_pipeline", fake_pipeline)

    event = {
        "type": "message",
        "channel_type": "im",
        "user": "U123",
        "channel": "D123",
        "text": "help",
        "subtype": "bot_message",
    }

    await handlers.handle_riva_event(event)

    assert not ack_client.calls
    assert pipeline_called is False


async def test_riva_ignores_non_message_events(monkeypatch):
    ack_client = StubWebClient()
    monkeypatch.setattr(handlers, "_riva_web_client", ack_client)

    pipeline_called = False

    def fake_pipeline(*_):
        nonlocal pipeline_called
        pipeline_called = True

    monkeypatch.setattr(handlers, "_run_riva_pipeline", fake_pipeline)

    event = {
        "type": "reaction_added",
        "channel_type": "im",
        "user": "U123",
        "channel": "D123",
        "text": "help",
    }

    await handlers.handle_riva_event(event)

    assert not ack_client.calls
    assert pipeline_called is False


async def test_riva_channel_messages_do_not_trigger_dm_flow(monkeypatch):
    ack_client = StubWebClient()
    monkeypatch.setattr(handlers, "_riva_web_client", ack_client)

    pipeline_called = False

    def fake_pipeline(*_):
        nonlocal pipeline_called
        pipeline_called = True

    monkeypatch.setattr(handlers, "_run_riva_pipeline", fake_pipeline)

    event = {
        "type": "message",
        "channel_type": "channel",
        "user": "U123",
        "channel": "C123",
        "text": "help",
    }

    await handlers.handle_riva_event(event)

    assert not ack_client.calls
    assert pipeline_called is False
