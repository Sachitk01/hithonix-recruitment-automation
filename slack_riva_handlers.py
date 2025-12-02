"""Async helpers for handling Slack Riva events."""

from __future__ import annotations

import logging
import os
from functools import partial
from typing import Any, Dict, Optional

from anyio import to_thread
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from decision_engine import Intent, decide_intent
from slack_bots import RivaSlackBot
from slack_service import SlackClient

logger = logging.getLogger(__name__)
PIPELINE_ERROR_TEXT = "I hit a snag while processing that request. Please try again in a moment."

BOT_USER_ID_RIVA = (
    os.getenv("BOT_USER_ID_RIVA", "").strip()
    or os.getenv("SLACK_RIVA_BOT_USER_ID", "").strip()
)

_riva_bot_token = os.getenv("SLACK_RIVA_BOT_TOKEN")
_riva_web_client: Optional[WebClient] = (
    WebClient(token=_riva_bot_token) if _riva_bot_token else None
)

riva_slack_client = SlackClient(
    name="riva",
    bot_token=_riva_bot_token,
    default_channel=os.getenv("SLACK_RIVA_DEFAULT_CHANNEL_ID"),
    signing_secret=os.getenv("SLACK_RIVA_SIGNING_SECRET"),
)

riva_bot = RivaSlackBot(slack_client=riva_slack_client)

RIVA_GREETING_MESSAGE = (
    "Hello! I’m Riva, your L1 recruitment assistant. I can evaluate candidates, summarize resumes or JDs, "
    "and share quick L1 insights. What would you like to do?"
)

RIVA_HELP_MESSAGE = (
    "I’m Riva – your L1 recruitment assistant. I can:"
    "\n1) Evaluate a candidate for a role"
    "\n2) Summarize a resume or interview transcript"
    "\n3) Check L1 batch status or pipeline readiness"
    "\n4) Extract JD must-haves"
    "\n5) Answer quick L1 questions\n"
    "Try: “Evaluate John Doe for the HR Support role” or “Summarize this JD.”"
)

RIVA_UNSURE_MESSAGE = (
    "I’m not sure what you need yet. Try one of these formats:\n"
    "• “Evaluate Priya Shah for the IT Support role”\n"
    "• “Summarize this resume”\n"
    "• “What did you run for L1 today?”"
)

RIVA_SMALL_TALK_MESSAGE = (
    "Thanks for the note! Whenever you need me, try something like "
    "“Evaluate Jane Doe for the HR Support role” or “Summarize this JD.”"
)

_RIVA_PIPELINE_INTENTS = {
    Intent.L1_EVAL_SINGLE,
    Intent.L1_EVAL_BATCH_STATUS,
    Intent.PIPELINE_STATUS,
    Intent.DEBUG,
}


async def handle_riva_event(event: Dict[str, Any]) -> None:
    """Entry point for Slack Riva events (DMs, mentions)."""
    event_type = event.get("type")
    subtype = event.get("subtype")
    channel_type = event.get("channel_type")
    channel = event.get("channel")
    user = event.get("user")

    logger.info(
        "riva_event_received",
        extra={
            "event_type": event_type,
            "subtype": subtype,
            "channel": channel,
            "channel_type": channel_type,
            "user": user,
        },
    )

    if subtype == "bot_message":
        logger.info("riva_ignore_bot_message", extra={"channel": channel, "user": user})
        return

    if event_type == "message" and channel_type == "im":
        await _handle_riva_dm(event)
        return

    if event_type == "app_mention":
        await _handle_riva_app_mention(event)
        return

    logger.info(
        "riva_event_unhandled",
        extra={"event_type": event_type, "channel_type": channel_type},
    )


async def _handle_riva_dm(event: Dict[str, Any]) -> None:
    channel = event.get("channel")
    user = event.get("user")
    text = (event.get("text") or "").strip()

    decision = decide_intent(text, bot="RIVA")
    logger.info(
        "riva_dm_decision",
        extra={
            "intent": decision.intent.value,
            "confidence": decision.confidence,
            "channel": channel,
            "user": user,
            "notes": decision.notes,
            "text": text,
        },
    )

    if decision.intent == Intent.GREETING:
        _post_riva_message(channel, RIVA_GREETING_MESSAGE)
        return

    if decision.intent == Intent.HELP:
        _post_riva_message(channel, RIVA_HELP_MESSAGE)
        return

    if decision.intent == Intent.SMALL_TALK:
        _post_riva_message(channel, RIVA_SMALL_TALK_MESSAGE)
        return

    if decision.intent == Intent.UNKNOWN:
        _post_riva_message(channel, RIVA_UNSURE_MESSAGE)
        return

    if decision.intent not in _RIVA_PIPELINE_INTENTS:
        _post_riva_message(channel, RIVA_UNSURE_MESSAGE)
        return

    await _send_ack(channel, user)
    try:
        await to_thread.run_sync(_run_riva_pipeline, text, channel, user)
    except Exception:  # pragma: no cover - guarded by tests
        logger.exception(
            "riva_dm_pipeline_crashed",
            extra={"channel": channel, "user": user},
        )
        _notify_pipeline_failure(channel)


async def _handle_riva_app_mention(event: Dict[str, Any]) -> None:
    channel = event.get("channel")
    user = event.get("user")
    text = (event.get("text") or "").strip()

    cleaned_text = _strip_bot_mention(text)
    await _send_ack(channel, user)
    await to_thread.run_sync(_run_riva_pipeline, cleaned_text, channel, user)


async def _send_ack(channel: Optional[str], user: Optional[str]) -> None:
    if not channel or not _riva_web_client:
        return
    try:
        await to_thread.run_sync(
            partial(
                _riva_web_client.chat_postMessage,
                channel=channel,
                text="Got it, I'm on it. I'll reply here once I've processed your request.",
            )
        )
    except SlackApiError as exc:  # pragma: no cover - network errors
        logger.error(
            "riva_ack_failed",
            extra={"channel": channel, "user": user, "error": exc.response.get("error")},
        )


def _post_riva_message(channel: Optional[str], text: str) -> None:
    if channel and riva_slack_client:
        riva_slack_client.post_message(text, channel=channel)


def _run_riva_pipeline(text: str, channel: Optional[str], user: Optional[str]) -> None:
    try:
        response = riva_bot.handle_command(text, channel)
        logger.info(
            "riva_pipeline_complete",
            extra={"user": user, "channel": channel, "response_preview": (response or "")[:80]},
        )
    except Exception as exc:  # pragma: no cover - protective logging
        logger.exception(
            "riva_pipeline_failed",
            extra={"user": user, "channel": channel, "error": str(exc)},
        )
        if channel:
            riva_slack_client.post_message(
                PIPELINE_ERROR_TEXT,
                channel=channel,
            )


def _strip_bot_mention(text: str) -> str:
    if not BOT_USER_ID_RIVA:
        return text
    mention = f"<@{BOT_USER_ID_RIVA}>"
    return text.replace(mention, "").strip()


def _notify_pipeline_failure(channel: Optional[str]) -> None:
    if channel and riva_slack_client:
        riva_slack_client.post_message(PIPELINE_ERROR_TEXT, channel=channel)
