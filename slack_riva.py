
"""
Slack router for Riva (L1 AI recruiter).
Handles both direct messages and channel mentions.
"""

import os
import logging
from typing import Optional

from fastapi import APIRouter, Request

from slack_bots import RivaSlackBot, WORKING_PLACEHOLDER_TEXT
from slack_service import SlackClient

logger = logging.getLogger(__name__)
router = APIRouter()

BOT_USER_ID_RIVA = os.getenv("BOT_USER_ID_RIVA", "").strip() or os.getenv("SLACK_RIVA_BOT_USER_ID", "").strip()

# Initialize Riva bot and client
riva_slack_client = SlackClient(
    name="riva",
    bot_token=os.getenv("SLACK_RIVA_BOT_TOKEN"),
    default_channel=os.getenv("SLACK_RIVA_DEFAULT_CHANNEL_ID"),
    signing_secret=os.getenv("SLACK_RIVA_SIGNING_SECRET"),
)

riva_bot = RivaSlackBot(slack_client=riva_slack_client)


async def handle_riva_summary(routing_text: str) -> str:
    return riva_bot.handle_command(routing_text)


async def handle_riva_hires(routing_text: str) -> str:
    return riva_bot.handle_command(routing_text)


async def handle_riva_last_run_summary(routing_text: str) -> str:
    return riva_bot.handle_command(routing_text)


async def handle_riva_manual_review(routing_text: str, slack_user_id: Optional[str] = None) -> str:
    logger.info(
        "riva_manual_review_routed",
        extra={"user_id": slack_user_id, "text_length": len(routing_text)},
    )
    return riva_bot.handle_command(routing_text)


async def handle_riva_chat(
    raw_user_text: str,
    slack_user_id: Optional[str] = None,
    channel_id: Optional[str] = None,
) -> str:
    logger.info(
        "riva_chat_routed",
        extra={"user_id": slack_user_id, "channel_id": channel_id, "text_length": len(raw_user_text)},
    )
    return riva_bot.handle_command(raw_user_text)


def build_supported_commands_help_text_for_riva() -> str:
    """Return help text for Riva commands."""
    return (
        "Supported commands:\n"
        "• summary <Candidate> - <Role>\n"
        "• ready-for-l2 <Role>\n"
        "• last-run-summary\n"
        "• review <Candidate> - <Role> (trigger manual L1 review)\n"
        "\nOr just ask me anything in natural language!"
    )


@router.post("/slack/riva")
async def slack_riva_events(request: Request):
    """
    Unified Slack event handler for Riva.
    Supports both DMs and channel mentions.
    """
    payload = await request.json()
    print("🔥 RIVA HANDLER REACHED")
    print(payload)

    if payload.get("type") == "url_verification":
        return {"challenge": payload["challenge"]}

    event = payload.get("event", {}) or {}
    headers = request.headers

    if "X-Slack-Retry-Num" in headers:
        print("⚠️ Slack retry ignored")
        return {"ok": True}

    if event.get("bot_id"):
        print("⚠️ Ignored: Slack bot message")
        return {"ok": True}

    user = event.get("user")
    if user and BOT_USER_ID_RIVA and user == BOT_USER_ID_RIVA:
        print("⚠️ Ignored: message from bot user")
        return {"ok": True}

    channel = event.get("channel", "") or ""
    text = event.get("text", "") or ""
    thread_ts = event.get("thread_ts") or event.get("ts")

    print("CHANNEL:", channel)
    print("TEXT:", text)
    print("USER:", user)

    if not channel or not text:
        print("⚠️ Missing channel or text; returning early")
        return {"ok": True}

    is_dm = channel.startswith("D")

    if is_dm:
        cleaned_text = text.strip()
        print("💬 DM MODE:", cleaned_text)
    else:
        if not BOT_USER_ID_RIVA:
            print("⚠️ BOT_USER_ID_RIVA not configured; returning")
            return {"ok": True}

        mention = f"<@{BOT_USER_ID_RIVA}>"
        if mention not in text:
            print("⚠️ Ignored: no mention in channel")
            return {"ok": True}

        cleaned_text = text.replace(mention, "").strip()
        print("📢 CHANNEL MODE:", cleaned_text)

    if not cleaned_text:
        print("⚠️ Nothing to route after cleaning; returning")
        return {"ok": True}

    routing_text = cleaned_text
    lowercase = routing_text.lower()

    if channel:
        riva_slack_client.post_message_get_ts(
            WORKING_PLACEHOLDER_TEXT,
            channel=channel,
            thread_ts=thread_ts,
        )

    try:
        if lowercase.startswith("summary"):
            reply = await handle_riva_summary(routing_text)
        elif lowercase.startswith("hires"):
            reply = await handle_riva_hires(routing_text)
        elif lowercase.startswith("last-run-summary"):
            reply = await handle_riva_last_run_summary(routing_text)
        elif lowercase.startswith("review "):
            reply = await handle_riva_manual_review(routing_text, user)
        elif lowercase in ("help", "commands"):
            reply = build_supported_commands_help_text_for_riva()
        else:
            print("🤖 ENTERING RIVA CHAT MODE")
            reply = await handle_riva_chat(
                raw_user_text=routing_text,
                slack_user_id=user,
                channel_id=channel,
            )

        if not reply:
            print("⚠️ No reply generated; returning ok")
            return {"ok": True}

        riva_slack_client.post_message(
            reply,
            channel=channel,
            thread_ts=thread_ts,
        )
        print("📨 Riva reply sent as new threaded message!")
    except Exception as exc:
        logger.error("Error in Riva handler", exc_info=True, extra={"error": str(exc)})
        print(f"❌ Error: {exc}")
        fallback = (
            "I encountered an error. Here are the commands I support:\n"
            + build_supported_commands_help_text_for_riva()
        )
        riva_slack_client.post_message(fallback, channel=channel, thread_ts=thread_ts)

    return {"ok": True}
