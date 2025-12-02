
"""Conversational chat handler for Riva Slack bot."""

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from ai_prompts import get_riva_system_prompt
from candidate_service import CandidateSnapshot, get_candidate_service
from chat_intents import WorkIntentType, classify_work_intent
from chat_parsers import (
    build_role_lookup,
    try_extract_candidate_and_role_from_text,
    try_extract_role_from_text,
)
from chat_profiles import build_profile_text
from folder_map import L1_FOLDERS, L2_FOLDERS
from summary_store import SummaryStore

logger = logging.getLogger(__name__)

RIVA_SYSTEM_PROMPT = get_riva_system_prompt()

RIVA_STATUS_SYSTEM_PROMPT = (
    "You are Riva, an L1 AI recruiter. You are given the true candidate record "
    "from the recruitment system. You MUST NOT change any facts or statuses. "
    "Only rephrase them clearly for Slack. Do not say the candidate is On Hold, "
    "Rejected, or Moved to L2 unless it is explicitly present in the record text."
)

RIVA_AGGREGATE_SYSTEM_PROMPT = (
    "You are Riva. You are given the TRUE list of candidates from the system. "
    "Do not add or remove names. Just format clearly for Slack and optionally add a one-line summary."
)

RIVA_PROCESS_SYSTEM_PROMPT = (
    "You are Riva, explaining your official responsibilities based ONLY on the provided profile. "
    "Do not invent capabilities beyond that scope."
)

RIVA_PROFILE = {
    "mission": "Riva runs L1 screening for HR Support, IT Support, and IT Admin roles using transcripts and structured submissions.",
    "scope": "Transcript-based L1 evaluation only; no final hiring decisions or offer approvals.",
    "signals": [
        "JD alignment",
        "communication clarity",
        "relevant HR/IT experience",
        "basic HR/IT concepts",
    ],
    "outputs": ["Move to L2", "Reject", "On Hold (manual review)"]
}

ROLE_LOOKUP = build_role_lookup(L1_FOLDERS.keys())
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


class RivaChatHandler:
    """Handles conversational chat mode for Riva using LLM."""
    
    def __init__(self, openai_api_key: Optional[str] = None):
        self.api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.client = OpenAI(api_key=self.api_key) if self.api_key else None
        self.model = os.getenv("RIVA_CHAT_MODEL", "gpt-4o-mini")
    
    def handle_chat(
        self,
        user_message: str,
        user_id: Optional[str] = None,
        channel_id: Optional[str] = None
    ) -> str:
        """
        Handle a conversational message to Riva.
        
        Args:
            user_message: The user's message to Riva
            user_id: Slack user ID
            channel_id: Slack channel ID
            
        Returns:
            Conversational response from Riva
        """
        if not self.client:
            return "I'm sorry, I'm not configured to chat right now. Please contact your admin."

        try:
            intent = classify_work_intent(user_message)

            if intent == WorkIntentType.CANDIDATE_QUERY:
                return self._handle_candidate_query(user_message, user_id, channel_id)

            if intent == WorkIntentType.AGGREGATE_QUERY:
                return self._handle_aggregate_query(user_message, user_id, channel_id)

            if intent == WorkIntentType.PROCESS_QUERY:
                return self._handle_process_query(user_message, user_id, channel_id)

            return self._handle_general_chat(user_message, user_id, channel_id)

        except Exception as e:
            logger.error(
                "riva_chat_error",
                extra={"error": str(e), "user_id": user_id},
                exc_info=True
            )
            return "I encountered an error processing your message. Please try again or use a structured command."

    def _safe_fetch_snapshot(
        self,
        candidate_name: str,
        role_name: Optional[str],
        *,
        allow_fuzzy: bool = False,
    ) -> Optional[CandidateSnapshot]:
        """Wrapper that shields drive/service failures."""
        try:
            service = get_candidate_service()
            return service.get_latest_candidate_snapshot(
                candidate_name,
                role_name,
                allow_fuzzy=allow_fuzzy,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "candidate_snapshot_lookup_failed",
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
                "candidate_snapshot_lookup_failed",
                extra={"candidate": candidate_name, "role": role_name, "error": str(exc)},
                exc_info=True,
            )
            return None, None

    def _handle_candidate_query(
        self,
        user_message: str,
        user_id: Optional[str],
        channel_id: Optional[str],
    ) -> str:
        candidate_name, role_name = try_extract_candidate_and_role_from_text(
            user_message,
            ROLE_LOOKUP,
            COMMAND_PREFIXES,
        )
        if not candidate_name or not role_name:
            return (
                "I couldn't parse a candidate and role from that message. "
                "Please try 'evaluate <Candidate Name> - <Role>'."
            )

        snapshot, matched_name = self._lookup_snapshot_with_fallback(candidate_name, role_name)
        if snapshot:
            return self._respond_with_candidate_snapshot(snapshot, user_id, channel_id)

        target_name = matched_name or candidate_name or "this candidate"
        return self._candidate_not_found_message(target_name, role_name)

    def _handle_aggregate_query(
        self,
        user_message: str,
        user_id: Optional[str],
        channel_id: Optional[str],
    ) -> str:
        status_key = normalize_l1_status_keyword(user_message)
        role_filter = try_extract_role_from_text(user_message, ROLE_LOOKUP)
        candidates = self._collect_snapshot_candidates(status_key, role_filter)

        if not candidates:
            audience = f" for {role_filter}" if role_filter else ""
            if status_key:
                return f"I don't see any candidates with status '{status_key}'{audience}."
            return "I don't have any recent L1 candidates recorded right now."

        summary_lines = self._format_candidate_lines(candidates)
        request_context = (
            f"Status filter: {status_key or 'all'}\n"
            f"Role filter: {role_filter or 'All roles'}\n"
            f"Total candidates: {len(candidates)}\n\n"
            f"{summary_lines}"
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": RIVA_AGGREGATE_SYSTEM_PROMPT},
                {"role": "user", "content": request_context},
            ],
            max_tokens=400,
            temperature=0.3,
        )

        return response.choices[0].message.content.strip()

    def _handle_process_query(
        self,
        user_message: str,
        user_id: Optional[str],
        channel_id: Optional[str],
    ) -> str:
        profile_text = build_profile_text(RIVA_PROFILE)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": RIVA_PROCESS_SYSTEM_PROMPT},
                {"role": "user", "content": profile_text},
            ],
            max_tokens=400,
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()

    def _handle_general_chat(
        self,
        user_message: str,
        user_id: Optional[str],
        channel_id: Optional[str],
    ) -> str:
        context = self._build_context(user_message)

        messages = [
            {"role": "system", "content": RIVA_SYSTEM_PROMPT},
        ]

        if context:
            messages.append({"role": "system", "content": f"Current context:\n{context}"})

        messages.append({"role": "user", "content": user_message})

        logger.info(
            "riva_chat_request",
            extra={
                "user_id": user_id,
                "channel_id": channel_id,
                "message_length": len(user_message),
            }
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=500,
            temperature=0.7,
        )

        answer = response.choices[0].message.content.strip()

        logger.info(
            "riva_chat_response",
            extra={
                "user_id": user_id,
                "response_length": len(answer),
                "model": self.model,
            }
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
                "aggregate_snapshot_fetch_failed",
                extra={"role_filter": role_filter, "error": str(exc)},
            )
            return []

        results: List[CandidateSnapshot] = []
        for snapshot in snapshots:
            if status_key and not matches_snapshot_status(snapshot, status_key):
                continue
            results.append(snapshot)

        results.sort(key=lambda snap: snap.updated_at, reverse=True)
        return results

    @staticmethod
    def _format_candidate_lines(candidates: List[CandidateSnapshot]) -> str:
        lines: List[str] = []
        for snapshot in candidates[:15]:
            next_action = snapshot.next_action or "Not specified"
            lines.append(
                f"- {snapshot.candidate_name} — {snapshot.role} "
                f"(Stage: {snapshot.current_stage}, Next action: {next_action})"
            )
        if len(candidates) > 15:
            lines.append(f"…and {len(candidates) - 15} more candidates.")
        return "\n".join(lines)

    def _respond_with_candidate_snapshot(
        self,
        snapshot: CandidateSnapshot,
        user_id: Optional[str],
        channel_id: Optional[str],
    ) -> str:
        def safe(value: Optional[str], fallback: str = "Not provided") -> str:
            return value if value else fallback

        if snapshot.final_decision:
            stage_line = "Current stage: Final decision recorded"
            status_line = f"Decision: {safe(snapshot.final_decision)}"
        else:
            stage_line = f"Current stage: {safe(snapshot.current_stage)}"
            status_line = f"AI status: {safe(snapshot.ai_status)}"

        status_summary = (
            f"Candidate: {snapshot.candidate_name} — {safe(snapshot.role)}\n"
            f"{stage_line}\n"
            f"{status_line}\n"
            f"L1 outcome: {safe(snapshot.l1_outcome, 'N/A')}\n"
            f"L2 outcome: {safe(snapshot.l2_outcome, 'N/A')}\n"
            f"Next action: {safe(snapshot.next_action)}\n"
            f"Last updated: {snapshot.updated_at.isoformat()} ({snapshot.source})"
        )

        messages = [
            {"role": "system", "content": RIVA_STATUS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Here is the candidate record:\n"
                    f"{status_summary}\n\n"
                    "Explain this to the recruiter."
                ),
            },
        ]

        logger.info(
            "riva_chat_candidate_mode",
            extra={
                "user_id": user_id,
                "channel_id": channel_id,
                "candidate": snapshot.candidate_name,
                "role": snapshot.role,
                "stage": snapshot.current_stage,
                "source": snapshot.source,
            },
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=400,
            temperature=0.2,
        )

        return response.choices[0].message.content.strip()

    def _candidate_not_found_message(self, candidate_name: str, role_name: Optional[str]) -> str:
        logger.info(
            "riva_chat_candidate_missing",
            extra={"candidate": candidate_name, "role": role_name},
        )
        role_label = role_name or "the requested role"
        return (
            f"I don't have any evaluation data yet for {candidate_name} — {role_label}. "
            "Please check the dashboard or run a new evaluation."
        )
    
    def _build_context(self, user_message: str) -> str:
        """
        Build context for the LLM from backend data.
        
        Args:
            user_message: User's message to analyze
            
        Returns:
            Formatted context string
        """
        context_parts = []
        
        # Extract potential candidate names and roles
        normalized_msg = user_message.lower()
        
        # Check for role mentions
        mentioned_roles = []
        for role in L1_FOLDERS.keys():
            if role.lower() in normalized_msg:
                mentioned_roles.append(role)
        
        # Get last batch summary
        try:
            summary = SummaryStore.get_l1_summary()
            if summary:
                context_parts.append(
                    f"Last L1 Batch Run:\n"
                    f"- Total Seen: {summary.total_seen}\n"
                    f"- Evaluated: {summary.evaluated}\n"
                    f"- Moved to L2: {summary.moved_to_l2}\n"
                    f"- Rejected: {summary.rejected_at_l1}\n"
                    f"- On Hold: {summary.hold_decisions}\n"
                    f"- Errors: {summary.errors}"
                )
                
                # Add candidate details if available
                if hasattr(summary, 'candidates') and summary.candidates:
                    candidate_summary = []
                    for candidate in summary.candidates[:10]:  # Limit to 10
                        name = getattr(candidate, 'candidate_name', 'Unknown')
                        role = getattr(candidate, 'role', 'Unknown')
                        decision = getattr(candidate, 'decision', 'Unknown')
                        reason = getattr(candidate, 'reason', None)
                        
                        cand_info = f"- {name} ({role}): {decision}"
                        if reason and decision.lower() == 'hold':
                            cand_info += f" - {reason}"
                        candidate_summary.append(cand_info)
                    
                    if candidate_summary:
                        context_parts.append(
                            "Recent Candidates:\n" + "\n".join(candidate_summary)
                        )
        except Exception as e:
            logger.warning(f"Failed to load batch summary: {e}")
        
        # Add role information if mentioned
        if mentioned_roles:
            context_parts.append(f"Mentioned roles: {', '.join(mentioned_roles)}")
        
        return "\n\n".join(context_parts) if context_parts else ""
    
    def _extract_candidate_names(self, message: str) -> List[str]:
        """
        Extract potential candidate names from message.
        Simple heuristic: look for capitalized words.
        
        Args:
            message: User message
            
        Returns:
            List of potential candidate names
        """
        words = message.split()
        candidates = []
        
        for i, word in enumerate(words):
            # Look for capitalized words that might be names
            if word and word[0].isupper() and len(word) > 2:
                # Check if it's not a common word
                if word.lower() not in ['riva', 'arjun', 'hithonix', 'slack', 'the', 'a', 'an']:
                    candidates.append(word)
        
        return candidates


# Global instance
_chat_handler: Optional[RivaChatHandler] = None


def get_chat_handler() -> RivaChatHandler:
    """Get global chat handler instance."""
    global _chat_handler
    if _chat_handler is None:
        _chat_handler = RivaChatHandler()
    return _chat_handler


def normalize_l1_status_keyword(text: str) -> Optional[str]:
    if not text:
        return None

    lowered = text.lower()
    ready_keywords = [
        "ready for l2",
        "move to l2",
        "moved to l2",
        "send to l2",
        "shortlist",
        "shortlisted",
        "hire",
        "final selected",
    ]
    hold_keywords = ["hold", "on hold", "manual review", "data incomplete"]
    reject_keywords = ["reject", "rejected", "decline", "declined"]

    if any(keyword in lowered for keyword in ready_keywords):
        return "ready_for_l2"
    if any(keyword in lowered for keyword in hold_keywords):
        return "hold"
    if any(keyword in lowered for keyword in reject_keywords):
        return "reject"
    return None


def matches_snapshot_status(snapshot: CandidateSnapshot, status_key: str) -> bool:
    stage = (snapshot.current_stage or "").lower()
    final_decision = (snapshot.final_decision or "").lower()
    ai_status = (snapshot.ai_status or "").lower()
    l1_outcome = (snapshot.l1_outcome or "").lower()

    if status_key == "ready_for_l2":
        if final_decision:
            return False
        ready_keywords = [
            "move to l2",
            "send to l2",
            "shortlist",
            "ready for l2",
        ]
        return stage == "l2" or any(keyword in ai_status for keyword in ready_keywords)

    if status_key == "hold":
        if final_decision:
            return False
        if stage == "hold":
            return True
        return "hold" in ai_status or "hold" in l1_outcome

    if status_key == "reject":
        reject_keywords = ["reject", "decline", "not selected"]
        if final_decision:
            return any(keyword in final_decision for keyword in reject_keywords)
        status_matches = any(keyword in ai_status for keyword in reject_keywords)
        outcome_matches = any(keyword in l1_outcome for keyword in reject_keywords)
        return status_matches or outcome_matches

    return True


