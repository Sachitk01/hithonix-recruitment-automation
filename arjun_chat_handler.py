"""
Conversational chat handler for Arjun Slack bot.
Provides ChatGPT-style conversational responses using OpenAI LLM.
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

from openai import OpenAI

from ai_prompts import get_arjun_system_prompt
from candidate_service import CandidateSnapshot, get_candidate_service
from chat_intents import WorkIntentType, classify_work_intent
from chat_parsers import (
    build_role_lookup,
    try_extract_candidate_and_role_from_text,
    try_extract_role_from_text,
)
from chat_profiles import build_profile_text
from folder_map import L2_FOLDERS
from summary_store import SummaryStore

logger = logging.getLogger(__name__)

ARJUN_SYSTEM_PROMPT = get_arjun_system_prompt()

ARJUN_STATUS_SYSTEM_PROMPT = (
    "You are Arjun, responsible for L2 evaluations and leadership readiness. "
    "You must stick to the official record provided."
)

ARJUN_AGGREGATE_SYSTEM_PROMPT = (
    "You are Arjun. Present the exact candidate list provided, do not add names, "
    "and add a short overall summary for Slack."
)

ARJUN_PROCESS_SYSTEM_PROMPT = (
    "You are Arjun, explaining your own scope based solely on the provided profile."
)

ARJUN_PROFILE = {
    "mission": "Arjun runs L2 evaluation and leadership readiness checks based on candidates shortlisted by Riva.",
    "scope": "Evaluates deeper functional expertise, leadership alignment, and final readiness. Provides recommendations but does not issue offers.",
    "signals": [
        "Leadership communication",
        "Technical or domain depth",
        "Decision-making and maturity",
        "Alignment with Hithonix culture",
    ],
    "outputs": ["Hire", "Reject", "Hold (needs recruiter decision)"]
}

ROLE_LOOKUP = build_role_lookup(L2_FOLDERS.keys())
COMMAND_PREFIXES = (
    "evaluate",
    "please evaluate",
    "can you evaluate",
    "summary",
    "status",
    "status of",
    "status for",
    "what is the status of",
    "what's the status of",
    "whats the status of",
    "give me the status of",
    "give me status of",
    "show",
    "check",
    "review",
)


class ArjunChatHandler:
    """Handles conversational chat mode for Arjun using an LLM."""

    def __init__(self, openai_api_key: Optional[str] = None) -> None:
        self.api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        self.model = os.getenv("ARJUN_CHAT_MODEL", os.getenv("RIVA_CHAT_MODEL", "gpt-4o-mini"))

    def handle_chat(
        self,
        *,
        user_message: str,
        slack_user_id: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> str:
        if not self.client:
            return "I'm not configured to chat yet. Please ask again later or use summary/hires/review."

        try:
            intent = classify_work_intent(user_message)

            if intent == WorkIntentType.CANDIDATE_QUERY:
                return self._handle_candidate_query(user_message, slack_user_id, channel_id)

            if intent == WorkIntentType.AGGREGATE_QUERY:
                return self._handle_aggregate_query(user_message, slack_user_id, channel_id)

            if intent == WorkIntentType.PROCESS_QUERY:
                return self._handle_process_query(user_message, slack_user_id, channel_id)

            return self._handle_general_chat(user_message, slack_user_id, channel_id)

        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "arjun_chat_error",
                extra={"error": str(exc), "user_id": slack_user_id},
                exc_info=True,
            )
            return "I hit an error while responding. Please try a structured command like summary or hires."

    def _safe_fetch_snapshot(
        self,
        candidate_name: str,
        role_name: Optional[str],
        *,
        allow_fuzzy: bool = False,
    ) -> Optional[CandidateSnapshot]:
        try:
            service = get_candidate_service()
            return service.get_latest_candidate_snapshot(
                candidate_name,
                role_name,
                allow_fuzzy=allow_fuzzy,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "arjun_snapshot_lookup_failed",
                extra={"candidate": candidate_name, "role": role_name, "error": str(exc)},
                exc_info=True,
            )
            return None

    def _lookup_snapshot_with_fallback(
        self,
        candidate_name: str,
        role_name: Optional[str],
    ) -> Tuple[Optional[CandidateSnapshot], Optional[str]]:
        try:
            service = get_candidate_service()
            direct = service.get_candidate_record(candidate_name, role_name or "")
            if direct:
                return direct, direct.candidate_name
            return service.get_candidate_record_fuzzy(candidate_name, role_name)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "arjun_snapshot_lookup_failed",
                extra={"candidate": candidate_name, "role": role_name, "error": str(exc)},
                exc_info=True,
            )
            return None, None

    def _build_context(self, user_message: str) -> str:
        context_parts: List[str] = []

        try:
            summary = SummaryStore.get_l2_summary()
            if summary:
                context_parts.append(
                    "Last L2 Batch Run:\n"
                    f"- Candidates seen: {summary.total_seen}\n"
                    f"- Evaluated: {summary.evaluated}\n"
                    f"- Hires: {summary.hires}\n"
                    f"- Rejects: {summary.rejects}\n"
                    f"- Holds: {summary.hold_decisions}\n"
                    f"- Errors: {summary.errors}"
                )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to load L2 summary: %s", exc)

        lowered = user_message.lower()
        mentioned_roles = [role for role in L2_FOLDERS if role.lower() in lowered]
        if mentioned_roles:
            context_parts.append("Mentioned roles: " + ", ".join(mentioned_roles))

        return "\n\n".join(context_parts)

    def _handle_candidate_query(
        self,
        user_message: str,
        slack_user_id: Optional[str],
        channel_id: Optional[str],
    ) -> str:
        candidate_name, role_name = try_extract_candidate_and_role_from_text(
            user_message,
            ROLE_LOOKUP,
            COMMAND_PREFIXES,
        )
        if not candidate_name:
            return (
                "I couldn't parse a candidate from that message. "
                "Please try 'evaluate <Candidate Name> - <Role>'."
            )

        snapshot, matched_name = self._lookup_snapshot_with_fallback(candidate_name, role_name)
        if snapshot:
            return self._respond_with_candidate_snapshot(snapshot, slack_user_id, channel_id)

        candidate_label = matched_name or candidate_name or "this candidate"
        role_label = role_name or "the requested role"
        return f"I don't see any L2 or final evaluation yet for {candidate_label} — {role_label}."

    def _respond_with_candidate_snapshot(
        self,
        snapshot: CandidateSnapshot,
        slack_user_id: Optional[str],
        channel_id: Optional[str],
    ) -> str:
        def safe(value: Optional[str], fallback: str = "Not provided") -> str:
            return value if value else fallback

        if snapshot.final_decision:
            stage_line = "Current stage: Final decision recorded"
            status_line = f"Final decision: {safe(snapshot.final_decision)}"
        else:
            stage_line = f"Current stage: {safe(snapshot.current_stage)}"
            fallback = snapshot.l2_outcome or snapshot.ai_status or None
            status_line = f"L2 outcome: {safe(fallback, 'Not specified')}"

        status_summary = (
            f"Candidate: {snapshot.candidate_name} — {safe(snapshot.role)}\n"
            f"{stage_line}\n"
            f"{status_line}\n"
            f"L1 outcome: {safe(snapshot.l1_outcome, 'N/A')}\n"
            f"Next action: {safe(snapshot.next_action)}\n"
            f"Last updated: {snapshot.updated_at.isoformat()} ({snapshot.source})"
        )

        logger.info(
            "arjun_chat_candidate_mode",
            extra={
                "user_id": slack_user_id,
                "channel_id": channel_id,
                "candidate": snapshot.candidate_name,
                "role": snapshot.role,
            },
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": ARJUN_STATUS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Here is the candidate record:\n"
                        f"{status_summary}\n\n"
                        "Explain this for the recruiter."
                    ),
                },
            ],
            max_tokens=400,
            temperature=0.2,
        )

        return response.choices[0].message.content.strip()

    def _handle_aggregate_query(
        self,
        user_message: str,
        slack_user_id: Optional[str],
        channel_id: Optional[str],
    ) -> str:
        status_key = normalize_l2_status_keyword(user_message)
        role_filter = try_extract_role_from_text(user_message, ROLE_LOOKUP)
        candidates = self._collect_snapshot_candidates(status_key, role_filter)

        if not candidates:
            role_clause = f" for {role_filter}" if role_filter else ""
            if status_key:
                return f"I don't see any L2 candidates with status '{status_key}'{role_clause}."
            return "I don't have recent L2 candidates recorded right now."

        summary_lines = self._format_snapshot_lines(candidates)
        request_context = (
            f"Status filter: {status_key or 'all'}\n"
            f"Role filter: {role_filter or 'All roles'}\n"
            f"Total candidates: {len(candidates)}\n\n"
            f"{summary_lines}"
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": ARJUN_AGGREGATE_SYSTEM_PROMPT},
                {"role": "user", "content": request_context},
            ],
            max_tokens=400,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()

    def _handle_process_query(
        self,
        user_message: str,
        slack_user_id: Optional[str],
        channel_id: Optional[str],
    ) -> str:
        profile_text = build_profile_text(ARJUN_PROFILE)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": ARJUN_PROCESS_SYSTEM_PROMPT},
                {"role": "user", "content": profile_text},
            ],
            max_tokens=400,
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()

    def _handle_general_chat(
        self,
        user_message: str,
        slack_user_id: Optional[str],
        channel_id: Optional[str],
    ) -> str:
        context = self._build_context(user_message)

        messages: List[Dict[str, str]] = [{"role": "system", "content": ARJUN_SYSTEM_PROMPT}]
        if context:
            messages.append({"role": "system", "content": f"Current context:\n{context}"})
        messages.append({"role": "user", "content": user_message})

        logger.info(
            "arjun_chat_request",
            extra={
                "user_id": slack_user_id,
                "channel_id": channel_id,
                "message_length": len(user_message),
            },
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )

        answer = response.choices[0].message.content.strip()
        logger.info(
            "arjun_chat_response",
            extra={
                "user_id": slack_user_id,
                "response_length": len(answer),
                "model": self.model,
            },
        )
        return answer

    def _collect_snapshot_candidates(
        self,
        status_key: Optional[str],
        role_filter: Optional[str],
    ) -> List[CandidateSnapshot]:
        service = get_candidate_service()
        try:
            snapshots = service.get_all_candidate_snapshots(role_filter)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "arjun_aggregate_snapshot_fetch_failed",
                extra={"role_filter": role_filter, "error": str(exc)},
            )
            return []

        results: List[CandidateSnapshot] = []
        for snapshot in snapshots:
            if snapshot.current_stage.upper() not in {"L2", "FINAL"}:
                continue
            if status_key and not matches_l2_snapshot_status(snapshot, status_key):
                continue
            results.append(snapshot)

        results.sort(key=lambda snap: snap.updated_at, reverse=True)
        return results

    @staticmethod
    def _format_snapshot_lines(candidates: List[CandidateSnapshot]) -> str:
        lines: List[str] = []
        for snapshot in candidates[:15]:
            decision = snapshot.l2_outcome or snapshot.ai_status or "Unknown"
            lines.append(
                f"- {snapshot.candidate_name} — {snapshot.role} "
                f"(Stage: {snapshot.current_stage}, Decision: {decision})"
            )
        if len(candidates) > 15:
            lines.append(f"…and {len(candidates) - 15} more candidates.")
        return "\n".join(lines)


_chat_handler: Optional[ArjunChatHandler] = None


def get_chat_handler() -> ArjunChatHandler:
    global _chat_handler
    if _chat_handler is None:
        _chat_handler = ArjunChatHandler()
    return _chat_handler


def normalize_l2_status_keyword(text: str) -> Optional[str]:
    if not text:
        return None

    lowered = text.lower()
    hire_keywords = ["hire", "hired", "final selection", "final selected"]
    shortlist_keywords = ["shortlist", "shortlisted", "ready for leadership"]
    hold_keywords = ["hold", "on hold", "manual review", "needs recruiter"]
    reject_keywords = ["reject", "rejected", "decline", "declined"]

    if any(keyword in lowered for keyword in hire_keywords + shortlist_keywords):
        return "shortlist"
    if any(keyword in lowered for keyword in hold_keywords):
        return "hold"
    if any(keyword in lowered for keyword in reject_keywords):
        return "reject"
    return None


def matches_l2_snapshot_status(snapshot: CandidateSnapshot, status_key: str) -> bool:
    stage = (snapshot.current_stage or "").lower()
    final_decision = (snapshot.final_decision or "").lower()
    l2_outcome = (snapshot.l2_outcome or "").lower()
    ai_status = (snapshot.ai_status or "").lower()

    shortlist_keywords = ["shortlist", "hire", "final selected", "final hire"]
    reject_keywords = ["reject", "decline"]

    if status_key == "shortlist":
        if final_decision:
            return any(keyword in final_decision for keyword in shortlist_keywords)
        return stage == "l2" and (
            any(keyword in l2_outcome for keyword in shortlist_keywords)
            or any(keyword in ai_status for keyword in shortlist_keywords)
        )

    if status_key == "hold":
        if final_decision:
            return False
        return stage == "hold" or "hold" in ai_status

    if status_key == "reject":
        if final_decision:
            return any(keyword in final_decision for keyword in reject_keywords)
        return any(keyword in l2_outcome for keyword in reject_keywords) or any(
            keyword in ai_status for keyword in reject_keywords
        )

    return True
