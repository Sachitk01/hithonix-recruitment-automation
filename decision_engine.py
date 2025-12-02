"""Shared intent classification helpers for Slack bots."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

_INTENT_CLASSIFIER_MODEL = os.getenv("INTENT_CLASSIFIER_MODEL", "gpt-4o-mini")


class Intent(str, Enum):
    GREETING = "GREETING"
    HELP = "HELP"
    L1_EVAL_SINGLE = "L1_EVAL_SINGLE"
    L1_EVAL_BATCH_STATUS = "L1_EVAL_BATCH_STATUS"
    L2_EVAL_SINGLE = "L2_EVAL_SINGLE"
    L2_COMPARE = "L2_COMPARE"
    PIPELINE_STATUS = "PIPELINE_STATUS"
    DEBUG = "DEBUG"
    SMALL_TALK = "SMALL_TALK"
    WORK_QUERY = "WORK_QUERY"
    UNKNOWN = "UNKNOWN"


@dataclass
class Decision:
    intent: Intent
    target_bot: str
    confidence: float
    notes: str = ""


def _normalize_bot(bot: str) -> str:
    if not bot:
        return "RIVA"
    return bot.strip().upper() or "RIVA"


def _matches_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def simple_rule_engine(text: Optional[str], bot: str) -> Optional[Decision]:
    if not text:
        return None

    normalized = text.strip().lower()
    if not normalized:
        return None

    target_bot = _normalize_bot(bot)

    greeting_triggers = (
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "hi riva",
        "hi arjun",
        "hey riva",
        "hey arjun",
    )
    if normalized in greeting_triggers or normalized.startswith("hi ") or normalized.startswith("hello "):
        return Decision(Intent.GREETING, target_bot, 1.0, "rule:greeting")

    if "help" in normalized or "what can you do" in normalized:
        return Decision(Intent.HELP, target_bot, 0.9, "rule:help")

    if target_bot == "RIVA":
        if _matches_any(normalized, ("evaluate", "resume", "jd", "summary", "status", "candidate")):
            return Decision(Intent.L1_EVAL_SINGLE, target_bot, 0.75, "rule:l1_eval")
        if _matches_any(normalized, ("batch", "run l1", "daily run")):
            return Decision(Intent.L1_EVAL_BATCH_STATUS, target_bot, 0.7, "rule:l1_batch")

    if target_bot == "ARJUN":
        if _matches_any(normalized, ("deep dive", "l2", "second opinion", "shortlist")):
            return Decision(Intent.L2_EVAL_SINGLE, target_bot, 0.75, "rule:l2_eval")
        if _matches_any(normalized, ("compare", "comparison", "versus", "vs ", "stack rank")):
            return Decision(Intent.L2_COMPARE, target_bot, 0.72, "rule:l2_compare")

    work_query_keywords = (
        "candidate",
        "role",
        "status",
        "outcome",
        "result",
        "ready",
        "review",
        "batch",
        "pipeline",
        "summary",
        "hire",
        "decision",
        "run l2",
        "run l1",
        "latest",
    )
    if _matches_any(normalized, work_query_keywords):
        return Decision(Intent.WORK_QUERY, target_bot, 0.65, "rule:work_query")

    if _matches_any(normalized, ("thanks", "thank you", "great", "awesome")):
        return Decision(Intent.SMALL_TALK, target_bot, 0.6, "rule:smalltalk")

    return None


def decide_intent(text: Optional[str], bot: str, llm_client: Optional[object] = None) -> Decision:
    target_bot = _normalize_bot(bot)
    decision = simple_rule_engine(text, target_bot)
    if decision:
        return decision

    if llm_client is None:
        return Decision(Intent.UNKNOWN, target_bot, 0.0, "fallback")

    message_text = f"""
You are routing messages for the Hithonix recruitment bots.

Message: "{text or ''}"
Bot: {target_bot}

Decide which intent best describes the user's request.
Valid intents:
- GREETING
- HELP
- L1_EVAL_SINGLE
- L1_EVAL_BATCH_STATUS
- L2_EVAL_SINGLE
- L2_COMPARE
- PIPELINE_STATUS
- DEBUG
- SMALL_TALK
- WORK_QUERY
- UNKNOWN

Respond ONLY as JSON with fields: intent, confidence (0-1), notes.
"""

    try:
        response = llm_client.chat.completions.create(  # type: ignore[attr-defined]
            model=_INTENT_CLASSIFIER_MODEL,
            messages=[
                {"role": "system", "content": "You classify recruitment bot intents."},
                {"role": "user", "content": message_text.strip()},
            ],
            temperature=0,
            max_tokens=200,
        )
        raw_content = response.choices[0].message.content.strip()
        payload = json.loads(raw_content)
        intent_value = payload.get("intent", "UNKNOWN")
        confidence = float(payload.get("confidence", 0))
        notes = payload.get("notes", "") or ""
        try:
            mapped_intent = Intent(intent_value)
        except ValueError:
            mapped_intent = Intent.UNKNOWN
        return Decision(mapped_intent, target_bot, confidence, notes)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning(
            "intent_decision_llm_failed",
            extra={"bot": target_bot, "error": str(exc)},
        )
        return Decision(Intent.UNKNOWN, target_bot, 0.0, "fallback")