"""Async helpers for handling Slack Arjun events."""

from __future__ import annotations

import logging
import os
from functools import partial
from typing import Any, Dict, Optional

from anyio import to_thread
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from decision_engine import Intent, decide_intent
from slack_bots import ArjunSlackBot
from slack_service import SlackClient

logger = logging.getLogger(__name__)
PIPELINE_ERROR_TEXT = "I hit a snag while processing that request. Please try again in a moment."

BOT_USER_ID_ARJUN = (
    os.getenv("BOT_USER_ID_ARJUN", "").strip()
    or os.getenv("SLACK_ARJUN_BOT_USER_ID", "").strip()
)

_arjun_bot_token = os.getenv("SLACK_ARJUN_BOT_TOKEN")
_arjun_web_client: Optional[WebClient] = (
    WebClient(token=_arjun_bot_token) if _arjun_bot_token else None
)

arjun_slack_client = SlackClient(
    name="arjun",
    bot_token=_arjun_bot_token,
    default_channel=os.getenv("SLACK_ARJUN_DEFAULT_CHANNEL_ID"),
    signing_secret=os.getenv("SLACK_ARJUN_SIGNING_SECRET"),
)

arjun_bot = ArjunSlackBot(slack_client=arjun_slack_client)

ARJUN_GREETING_MESSAGE = (
    "Hello! I’m Arjun, your L2 hiring evaluator. I can run deep dives, compare finalists, and "
    "recommend who to prioritize. What would you like me to analyze?"
)

ARJUN_HELP_MESSAGE = (
    "I’m Arjun – your L2 evaluation assistant. I can:\n"
    "1) Do a deep L2 evaluation for a candidate + role\n"
    "2) Compare multiple candidates and share trade-offs\n"
    "3) Explain previous L2 decisions or priorities\n"
    "4) Suggest interview focus areas\n"
    "5) Rank candidates from a shortlist\n"
    "Try: “Do an L2 evaluation of John Doe for Senior Backend” or “Compare John vs Jane for Sales Manager.”"
)

ARJUN_UNSURE_MESSAGE = (
    "I’m not sure what you need yet. Try one of these:\n"
    "• “Do an L2 evaluation of Priya Shah for Product Manager”\n"
    "• “Compare John vs Jane for Sales Director”\n"
    "• “What were the latest L2 outcomes?”"
)

ARJUN_SMALL_TALK_MESSAGE = (
    "Thanks! When you’re ready, ask me to evaluate or compare L2 candidates — for example, "
    "“Deep dive on Aisha for Solutions Architect.”"
)

_ARJUN_PIPELINE_INTENTS = {
    Intent.L2_EVAL_SINGLE,
    Intent.L2_COMPARE,
    Intent.PIPELINE_STATUS,
    Intent.DEBUG,
}


async def handle_arjun_event(event: Dict[str, Any]) -> None:
    event_type = event.get("type")
    subtype = event.get("subtype")
    channel_type = event.get("channel_type")
    channel = event.get("channel")
    user = event.get("user")

    logger.info(
        "arjun_event_received",
        extra={
            "event_type": event_type,
            "subtype": subtype,
            "channel": channel,
            "channel_type": channel_type,
            "user": user,
        },
    )

    if subtype == "bot_message":
        logger.info("arjun_ignore_bot_message", extra={"channel": channel, "user": user})
        return

    if event_type == "message" and channel_type == "im":
        await _handle_arjun_dm(event)
        return

    if event_type == "app_mention":
        await _handle_arjun_app_mention(event)
        return

    logger.info(
        "arjun_event_unhandled",
        extra={"event_type": event_type, "channel_type": channel_type},
    )


async def _handle_arjun_dm(event: Dict[str, Any]) -> None:
    channel = event.get("channel")
    user = event.get("user")
    text = (event.get("text") or "").strip()

    decision = decide_intent(text, bot="ARJUN")
    logger.info(
        "arjun_dm_decision",
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
        _post_arjun_message(channel, ARJUN_GREETING_MESSAGE)
        return

    if decision.intent == Intent.HELP:
        _post_arjun_message(channel, ARJUN_HELP_MESSAGE)
        return

    if decision.intent == Intent.SMALL_TALK:
        _post_arjun_message(channel, ARJUN_SMALL_TALK_MESSAGE)
        return

    if decision.intent == Intent.UNKNOWN:
        _post_arjun_message(channel, ARJUN_UNSURE_MESSAGE)
        return

    if decision.intent not in _ARJUN_PIPELINE_INTENTS:
        _post_arjun_message(channel, ARJUN_UNSURE_MESSAGE)
        return

    await _send_ack(channel, user)
    try:
        await to_thread.run_sync(_run_arjun_pipeline, text, channel, user)
    except Exception:  # pragma: no cover - guarded by tests
        logger.exception(
            "arjun_dm_pipeline_crashed",
            extra={"channel": channel, "user": user},
        )
        _notify_pipeline_failure(channel)


async def _handle_arjun_app_mention(event: Dict[str, Any]) -> None:
    channel = event.get("channel")
    user = event.get("user")
    text = (event.get("text") or "").strip()

    cleaned_text = _strip_bot_mention(text)
    await _send_ack(channel, user)
    await to_thread.run_sync(_run_arjun_pipeline, cleaned_text, channel, user)


async def _send_ack(channel: Optional[str], user: Optional[str]) -> None:
    if not channel or not _arjun_web_client:
        return
    try:
        await to_thread.run_sync(
            partial(
                _arjun_web_client.chat_postMessage,
                channel=channel,
                text="Got it, I'm on it. I'll reply here once I've processed your request.",
            )
        )
    except SlackApiError as exc:  # pragma: no cover - network errors
        logger.error(
            "arjun_ack_failed",
            extra={"channel": channel, "user": user, "error": exc.response.get("error")},
        )


def _post_arjun_message(channel: Optional[str], text: str) -> None:
    if channel and arjun_slack_client:
        arjun_slack_client.post_message(text, channel=channel)


def _run_arjun_pipeline(text: str, channel: Optional[str], user: Optional[str]) -> None:
    try:
        response = arjun_bot.handle_command(text, channel)
        logger.info(
            "arjun_pipeline_complete",
            extra={"user": user, "channel": channel, "response_preview": (response or "")[:80]},
        )
    except Exception as exc:  # pragma: no cover - protective logging
        logger.exception(
            "arjun_pipeline_failed",
            extra={"user": user, "channel": channel, "error": str(exc)},
        )
        if channel:
            arjun_slack_client.post_message(
                PIPELINE_ERROR_TEXT,
                channel=channel,
            )


def _strip_bot_mention(text: str) -> str:
    if not BOT_USER_ID_ARJUN:
        return text
    mention = f"<@{BOT_USER_ID_ARJUN}>"
    return text.replace(mention, "").strip()


def _notify_pipeline_failure(channel: Optional[str]) -> None:
    if channel and arjun_slack_client:
        arjun_slack_client.post_message(PIPELINE_ERROR_TEXT, channel=channel)
