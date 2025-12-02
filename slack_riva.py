
"""FastAPI router for secure Riva Slack commands and events."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from decision_engine import decide_intent
from slack_bots import WORKING_PLACEHOLDER_TEXT
from slack_riva_handlers import handle_riva_event, riva_bot, riva_slack_client
from slack_security import verify_slack_request

logger = logging.getLogger(__name__)
router = APIRouter()

BOT_USER_ID_RIVA = (
    os.getenv("BOT_USER_ID_RIVA", "").strip()
    or os.getenv("SLACK_RIVA_BOT_USER_ID", "").strip()
)
SLACK_RIVA_SIGNING_SECRET = os.getenv("SLACK_RIVA_SIGNING_SECRET")


@router.post("/slack-riva/events")
async def slack_riva_events(request: Request) -> JSONResponse:
    """Slack Event Subscriptions endpoint for the Riva bot."""
    body = await request.body()
    try:
        payload: Dict[str, Any] = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error("riva_event_invalid_json", extra={"error": str(exc)})
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    payload_type = payload.get("type")

    if payload_type == "url_verification":
        logger.info("riva_event_url_verification_received")
        logger.info("riva_event_url_verification_signature_skipped")
        return JSONResponse({"challenge": payload.get("challenge")})

    verify_slack_request(request, body, SLACK_RIVA_SIGNING_SECRET)

    headers = request.headers
    if headers.get("X-Slack-Retry-Num"):
        logger.info(
            "riva_event_retry_dropped",
            extra={
                "retry_num": headers.get("X-Slack-Retry-Num"),
                "reason": headers.get("X-Slack-Retry-Reason"),
            },
        )
        return JSONResponse({"ok": True})

    event = payload.get("event") or {}
    if event.get("bot_id"):
        logger.debug("riva_event_ignored_bot", extra={"bot_id": event.get("bot_id")})
        return JSONResponse({"ok": True})

    user = event.get("user")
    if user and BOT_USER_ID_RIVA and user == BOT_USER_ID_RIVA:
        logger.debug("riva_event_self_message", extra={"user": user})
        return JSONResponse({"ok": True})

    if payload_type == "event_callback":
        logger.info(
            "riva_event_callback_received",
            extra={
                "event_type": event.get("type"),
                "channel": event.get("channel"),
                "user": user,
            },
        )

    asyncio.create_task(_dispatch_riva_event(event))
    return JSONResponse({"ok": True})


@router.post("/slack/riva")
async def slack_riva_command(request: Request) -> JSONResponse:
    """Slash command entry-point for /riva and related helpers."""
    body = await request.body()
    verify_slack_request(request, body, SLACK_RIVA_SIGNING_SECRET)

    form = _parse_slack_form(body)
    command = form.get("command")
    text = form.get("text", "")
    channel_id = form.get("channel_id")
    user_id = form.get("user_id")

    if not command or not channel_id or not user_id:
        raise HTTPException(status_code=400, detail="Missing Slack command fields")

    logger.info(
        "riva_command_received",
        extra={"command": command, "channel_id": channel_id, "user_id": user_id},
    )

    response = await _route_slash_command(command, text, channel_id)
    return JSONResponse(response)


def _parse_slack_form(body: bytes) -> Dict[str, str]:
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - invalid payloads
        raise HTTPException(status_code=400, detail="Invalid Slack payload encoding") from exc

    parsed = parse_qs(decoded, keep_blank_values=True)
    return {key: values[0] for key, values in parsed.items() if values}


async def _route_slash_command(command: str, text: str, channel_id: str) -> Dict[str, str]:
    normalized_command = command.strip().lower()

    if normalized_command in {"/riva", "/riva-test"}:
        asyncio.create_task(_execute_riva_command(text, channel_id))
        return {"response_type": "ephemeral", "text": WORKING_PLACEHOLDER_TEXT}

    if normalized_command == "/riva-help":
        help_text = await asyncio.to_thread(riva_bot.handle_command, "help", None)
        return {"response_type": "ephemeral", "text": help_text}

    logger.warning("riva_command_unknown", extra={"command": command})
    raise HTTPException(status_code=400, detail="Unknown Slack command")


async def _execute_riva_command(text: str, channel_id: str) -> None:
    try:
        decision = decide_intent(text, bot="RIVA")
        await asyncio.to_thread(riva_bot.handle_command, text, channel_id, decision.intent)
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("riva_command_execution_failed")
        if riva_slack_client:
            riva_slack_client.post_message(
                "⚠️ I hit an error while processing that request. Please try again shortly.",
                channel=channel_id,
            )


async def _dispatch_riva_event(event: Dict[str, Any]) -> None:
    try:
        await handle_riva_event(event)
    except Exception:  # pragma: no cover - defensive logging
        logger.exception(
            "riva_event_handler_failed",
            extra={"event_type": event.get("type"), "channel": event.get("channel")},
        )
