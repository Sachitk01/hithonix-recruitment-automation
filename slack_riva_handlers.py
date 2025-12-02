"""Async helpers for handling Slack Riva events."""

from __future__ import annotations

import logging
import os
from functools import partial
from typing import Any, Dict, Optional

from anyio import to_thread
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

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
