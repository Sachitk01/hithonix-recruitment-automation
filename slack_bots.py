from __future__ import annotations

import json
import re
import uuid
from typing import Callable, Dict, Iterable, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from slack_service import SlackClient

from drive_service import DriveManager
from folder_map import (
    L1_FOLDERS,
    L2_FOLDERS,
    PROFILES_FINAL_SELECTED_FOLDERS,
    PROFILES_L1_REJECTED_FOLDERS,
    PROFILES_L2_REJECTED_FOLDERS,
)
from summary_store import SummaryStore


CommandResult = str
DriveFactory = Callable[[], DriveManager]
WORKING_PLACEHOLDER_TEXT = "Processing your request… fetching the latest evaluation data from the system."


def looks_like_long_running_intent(text: Optional[str]) -> bool:
    if not text:
        return False
    lowered = text.lower()
    keywords = [
        "evaluate",
        "review",
        "run l1",
        "run l2",
        "list all",
        "show all candidates",
        "who all moved",
        "pipeline",
    ]
    return any(keyword in lowered for keyword in keywords)


class BaseSlackBot:
    mention_pattern = re.compile(r"^<@[^>]+>\\s*")

    def __init__(
        self,
        name: str,
        drive_factory: Optional[DriveFactory] = None,
        slack_client: Optional["SlackClient"] = None,
    ):
        self.name = name
        self._drive_factory = drive_factory
        self._slack_client = slack_client

    # --------------------------------------------------
    def _clean_text(self, text: Optional[str]) -> str:
        if not text:
            return ""
        cleaned = text.strip()
        cleaned = self.mention_pattern.sub("", cleaned)
        cleaned = cleaned.replace(" – ", " - ")
        return cleaned

    def _get_drive(self) -> DriveManager:
        if self._drive_factory:
            return self._drive_factory()
        return DriveManager(correlation_id=f"{self.name}-slack-{uuid.uuid4()}")

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\\s+", " ", value.strip().lower())

    @staticmethod
    def _truncate(value: Optional[str], limit: int = 280) -> str:
        if not value:
            return "N/A"
        value = value.strip()
        if len(value) <= limit:
            return value
        return value[: limit - 3].rstrip() + "..."

    @staticmethod
    def _format_list(items: Optional[Iterable[str]]) -> str:
        if not items:
            return "None"
        joined = ", ".join(i.strip() for i in items if i and i.strip())
        return joined or "None"

    def _dispatch_response(self, response: str, channel_id: Optional[str]) -> str:
        if channel_id and self._slack_client:
            self._slack_client.post_message(response, channel_id)
        return response

    # --------------------------------------------------
    def _resolve_role(self, role_map: Dict[str, str], role_input: str) -> Tuple[Optional[str], Optional[str]]:
        target = self._normalize(role_input)
        for role_name, folder_id in role_map.items():
            if self._normalize(role_name) == target:
                return role_name, folder_id
        return None, None

    def _find_candidate_folder(
        self,
        drive: DriveManager,
        candidate_name: str,
        role_input: str,
        folder_maps: List[Dict[str, str]],
    ) -> Tuple[Optional[str], Optional[str], Optional[List[Dict]]]:
        """Return (resolved_role_name, folder_id, file_listing) for candidate."""
        normalized_candidate = self._normalize(candidate_name)

        for role_map in folder_maps:
            resolved_role, parent_id = self._resolve_role(role_map, role_input)
            if not parent_id:
                continue
            candidates = drive.list_folder_like(parent_id)
            for candidate in candidates:
                candidate_label = candidate.get("name", "")
                if self._normalize(candidate_label) == normalized_candidate:
                    folder_id = drive.get_real_folder_id(candidate)
                    files = drive.list_files(folder_id)
                    return resolved_role or role_input, folder_id, files
        return None, None, None

    def _load_json_from_listing(
        self,
        drive: DriveManager,
        folder_id: str,
        filename: str,
        files: Optional[List[Dict]] = None,
    ) -> Optional[Dict]:
        listing = files or drive.list_files(folder_id)
        for file_obj in listing:
            if file_obj.get("name") == filename:
                payload = drive.download_file_bytes(file_obj["id"])
                try:
                    return json.loads(payload.decode("utf-8"))
                except json.JSONDecodeError:
                    return None
        return None

    # --------------------------------------------------
    @staticmethod
    def _parse_candidate_role(action_text: str) -> Tuple[Optional[str], Optional[str]]:
        if not action_text:
            return None, None
        parts = [part.strip() for part in action_text.split("-", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return None, None
        return parts[0], parts[1]


class RivaSlackBot(BaseSlackBot):
    L1_RESULT = "l1_result.json"
    L1_STATUS = "l1_status.json"

    def __init__(
        self,
        drive_factory: Optional[DriveFactory] = None,
        slack_client: Optional["SlackClient"] = None,
    ):
        super().__init__("riva", drive_factory, slack_client)
        self._search_roots = [
            L1_FOLDERS,
            L2_FOLDERS,
            PROFILES_FINAL_SELECTED_FOLDERS,
            PROFILES_L1_REJECTED_FOLDERS,
        ]

    # --------------------------------------------------
    def handle_command(self, raw_text: Optional[str], channel_id: Optional[str] = None) -> CommandResult:
        """
        Route incoming messages to either structured commands or conversational chat.
        
        Args:
            raw_text: Raw text from Slack
            channel_id: Slack channel ID
            
        Returns:
            Response text
        """
        text = self._clean_text(raw_text)
        lowered = text.lower()

        # Structured command routing
        if lowered.startswith("summary"):
            payload = text[len("summary"):].strip()
            return self._dispatch_response(self._handle_summary(payload), channel_id)

        if lowered.startswith("ready-for-l2"):
            role_text = text[len("ready-for-l2"):].strip()
            return self._dispatch_response(self._handle_ready_for_l2(role_text), channel_id)

        if lowered.startswith("hires"):
            role_text = text[len("hires"):].strip()
            return self._dispatch_response(self._handle_hires(role_text), channel_id)

        if lowered.startswith("last-run-summary"):
            return self._dispatch_response(self._handle_last_run_summary(), channel_id)

        # Manual review trigger
        if lowered.startswith("review "):
            return self._dispatch_response(self._handle_manual_review(text), channel_id)

        # Only show help on explicit request
        if lowered in ("help", "commands"):
            return self._dispatch_response(self._help_text(), channel_id)

        # Fall back to conversational chat mode
        return self._handle_chat(text, channel_id)
    
    def _handle_manual_review(self, text: str) -> CommandResult:
        """
        Handle manual L1 review trigger.
        
        Args:
            text: Command text
            
        Returns:
            Review result message
        """
        from manual_review_triggers import handle_riva_manual_review
        return handle_riva_manual_review(text)
    
    def _handle_chat(self, user_message: str, channel_id: Optional[str] = None) -> CommandResult:
        """
        Handle conversational chat mode using LLM.
        
        Args:
            user_message: User's message
            channel_id: Slack channel ID
            
        Returns:
            Conversational response
        """
        placeholder_ts: Optional[str] = None
        used_placeholder = False

        try:
            from riva_chat_handler import get_chat_handler

            chat_handler = get_chat_handler()
            if channel_id and self._slack_client and looks_like_long_running_intent(user_message):
                placeholder_ts = self._slack_client.post_message_get_ts(
                    WORKING_PLACEHOLDER_TEXT,
                    channel=channel_id,
                )
                used_placeholder = bool(placeholder_ts)

            response = chat_handler.handle_chat(
                user_message=user_message,
                channel_id=channel_id
            )

            if used_placeholder and placeholder_ts and self._slack_client:
                updated = self._slack_client.update_message(
                    channel=channel_id,
                    ts=placeholder_ts,
                    text=response,
                )
                if updated:
                    return response

            return self._dispatch_response(response, channel_id)

        except Exception as e:
            error_text = "I encountered an error. Here are the commands I support:\n" + self._help_text()
            if used_placeholder and placeholder_ts and self._slack_client and channel_id:
                self._slack_client.update_message(
                    channel=channel_id,
                    ts=placeholder_ts,
                    text=error_text,
                )
                return error_text
            return self._dispatch_response(error_text, channel_id)

    # --------------------------------------------------
    def _handle_summary(self, payload: str) -> CommandResult:
        candidate, role = self._parse_candidate_role(payload)
        if not candidate or not role:
            return "Usage: @Riva summary <Candidate Name> - <Role Name>"

        drive = self._get_drive()
        resolved_role, folder_id, files = self._find_candidate_folder(
            drive, candidate, role, self._search_roots
        )
        if not folder_id:
            return f"No candidate named {candidate} found for role {role}."

        result = self._load_json_from_listing(drive, folder_id, self.L1_RESULT, files)
        status_payload = self._load_json_from_listing(drive, folder_id, self.L1_STATUS, files)

        status = status_payload.get("status") if status_payload else None
        score = result.get("overall_score") if result else None
        strengths = self._format_list(result.get("strengths")) if result else "None"
        risks = self._format_list(result.get("risks")) if result else "None"
        recommendation = result.get("recommendation") if result else None

        status_display = status or recommendation or "UNKNOWN"
        next_step = self._map_l1_next_step(status_display)
        score_display = score if score is not None else "N/A"

        return (
            f"Candidate: {candidate} – {resolved_role or role}\n"
            f"L1 Status: {status_display}\n"
            f"Score: {score_display}\n"
            f"Strengths: {strengths}\n"
            f"Risks: {risks}\n"
            f"Next Step: {next_step}"
        )

    def _handle_ready_for_l2(self, role_text: str) -> CommandResult:
        if not role_text:
            return "Usage: @Riva ready-for-l2 <Role Name>"
        drive = self._get_drive()
        resolved_role, folder_id = self._resolve_role(L2_FOLDERS, role_text)
        if not folder_id:
            return f"Unknown role '{role_text}'."

        candidates = drive.list_folder_like(folder_id)
        ready_lines: List[str] = []
        for candidate in candidates:
            folder_id_candidate = drive.get_real_folder_id(candidate)
            files = drive.list_files(folder_id_candidate)
            result = self._load_json_from_listing(
                drive, folder_id_candidate, self.L1_RESULT, files
            )
            if result and result.get("recommendation") == "SEND_TO_L2":
                score = result.get("overall_score")
                score_text = score if score is not None else "N/A"
                ready_lines.append(f"{candidate['name']} – Score: {score_text}")

        if not ready_lines:
            return f"No candidates currently ready for L2 in {resolved_role or role_text}."

        top_lines = "\n".join(f"• {line}" for line in ready_lines[:10])
        return f"Ready for L2 – {resolved_role or role_text}:\n{top_lines}"

    def _handle_hires(self, role_text: str) -> CommandResult:
        """Alias for ready-for-l2 to support unified command vocabulary."""
        return self._handle_ready_for_l2(role_text)

    def _handle_last_run_summary(self) -> CommandResult:
        summary = SummaryStore.get_l1_summary()
        if not summary:
            return "No Riva L1 runs have completed yet."

        return (
            "Last Riva L1 run:\n"
            f"Candidates seen: {summary.total_seen}\n"
            f"Evaluated: {summary.evaluated}\n"
            f"Sent to L2: {summary.moved_to_l2}\n"
            f"Rejected at L1: {summary.rejected_at_l1}\n"
            f"Hold: {summary.hold_decisions} (manual-review: {summary.needs_manual_review}, backup: {summary.hold_backup_pool}, missing transcript: {summary.hold_missing_transcript}, data incomplete: {summary.hold_data_incomplete}, low confidence: {summary.hold_low_confidence}, ambiguous: {summary.hold_ambiguous}, JD mismatch: {summary.hold_jd_mismatch})\n"
            f"On hold (missing L1 transcript): {summary.on_hold_missing_transcript}\n"
            f"Data incomplete: {summary.data_incomplete}\n"
            f"Errors: {summary.errors}"
        )

    @staticmethod
    def _map_l1_next_step(status: str) -> str:
        mapping = {
            "ON_HOLD_MISSING_L1_TRANSCRIPT": "On hold – missing L1 transcript",
            "DATA_INCOMPLETE_L1": "On hold – data incomplete",
            "HOLD": "On hold – recruiter review",
            "SEND_TO_L2": "Ready for L2",
            "REJECT_AT_L1": "Rejected at L1",
        }
        return mapping.get(status, "Awaiting recruiter action")

    @staticmethod
    def _help_text() -> str:
        return (
            "Supported commands:\n"
            "• @Riva summary <Candidate> - <Role>\n"
            "• @Riva ready-for-l2 <Role> (or `hires <Role>` alias)\n"
            "• @Riva last-run-summary\n"
            "• @Riva review <Candidate> - <Role> (trigger manual L1 review)\n"
            "\nOr just ask me anything in natural language!"
        )


class ArjunSlackBot(BaseSlackBot):
    L2_RESULT = "l2_result.json"
    L2_STATUS = "l2_status.json"

    def __init__(
        self,
        drive_factory: Optional[DriveFactory] = None,
        slack_client: Optional["SlackClient"] = None,
    ):
        super().__init__("arjun", drive_factory, slack_client)
        self._search_roots = [
            L2_FOLDERS,
            PROFILES_FINAL_SELECTED_FOLDERS,
            PROFILES_L2_REJECTED_FOLDERS,
        ]

    # --------------------------------------------------
    def handle_command(self, raw_text: Optional[str], channel_id: Optional[str] = None) -> CommandResult:
        text = self._clean_text(raw_text)
        lowered = text.lower()

        if lowered.startswith("summary"):
            payload = text[len("summary"):].strip()
            return self._dispatch_response(self._handle_summary(payload), channel_id)

        if lowered.startswith("hires"):
            role_text = text[len("hires"):].strip()
            return self._dispatch_response(self._handle_hires(role_text), channel_id)

        if lowered.startswith("last-run-summary"):
            return self._dispatch_response(self._handle_last_run_summary(), channel_id)

        # Manual review trigger
        if lowered.startswith("review "):
            return self._dispatch_response(self._handle_manual_review(text), channel_id)

        # Only show help on explicit request
        if lowered in ("help", "commands"):
            return self._dispatch_response(self._help_text(), channel_id)

        # Fall back to conversational chat mode for everything else
        return self._handle_chat(text, channel_id)
    
    def _handle_manual_review(self, text: str) -> CommandResult:
        """
        Handle manual L2 review trigger.
        
        Args:
            text: Command text
            
        Returns:
            Review result message
        """
        from manual_review_triggers import handle_arjun_manual_review
        return handle_arjun_manual_review(text)

    # --------------------------------------------------
    def _handle_summary(self, payload: str) -> CommandResult:
        candidate, role = self._parse_candidate_role(payload)
        if not candidate or not role:
            return "Usage: @Arjun summary <Candidate Name> - <Role Name>"

        drive = self._get_drive()
        resolved_role, folder_id, files = self._find_candidate_folder(
            drive, candidate, role, self._search_roots
        )
        if not folder_id:
            return f"No candidate named {candidate} found for role {role}."

        result = self._load_json_from_listing(drive, folder_id, self.L2_RESULT, files)
        status_payload = self._load_json_from_listing(drive, folder_id, self.L2_STATUS, files)

        if not result:
            return f"No L2 evaluation found for {candidate} – {resolved_role or role}."

        status = status_payload.get("status") if status_payload else result.get("final_recommendation")
        comparison = result.get("l1_l2_comparison", "N/A")
        risks = self._format_list(result.get("risk_flags"))
        next_step = self._map_l2_next_step(status)

        return (
            f"Candidate: {candidate} – {resolved_role or role}\n"
            f"Final Recommendation: {status}\n"
            f"L2 Summary: {self._truncate(result.get('l2_summary'))}\n"
            f"L1 vs L2: {comparison}\n"
            f"Risks: {risks}\n"
            f"Next Step: {next_step}"
        )

    def _handle_hires(self, role_text: str) -> CommandResult:
        if not role_text:
            return "Usage: @Arjun hires <Role Name>"
        drive = self._get_drive()
        resolved_role, shortlist_parent = self._resolve_role(
            PROFILES_FINAL_SELECTED_FOLDERS, role_text
        )
        if not shortlist_parent:
            return f"Unknown role '{role_text}'."

        pending_role, pending_parent = self._resolve_role(L2_FOLDERS, role_text)

        hire_lines: List[str] = []
        seen = set()

        for parent_id in filter(None, [shortlist_parent, pending_parent]):
            candidates = drive.list_folder_like(parent_id)
            for candidate in candidates:
                folder_id_candidate = drive.get_real_folder_id(candidate)
                files = drive.list_files(folder_id_candidate)
                result = self._load_json_from_listing(
                    drive, folder_id_candidate, self.L2_RESULT, files
                )
                if result and result.get("final_recommendation") == "HIRE":
                    comparison = result.get("l1_l2_comparison", "N/A")
                    score = result.get("final_score")
                    score_text = score if score is not None else "N/A"
                    key = self._normalize(candidate["name"])
                    if key in seen:
                        continue
                    seen.add(key)
                    hire_lines.append(
                        f"{candidate['name']} – Score: {score_text} (L1 vs L2: {comparison})"
                    )

        role_label = resolved_role or pending_role or role_text

        if not hire_lines:
            return f"No hires recorded for {role_label}."

        top_lines = "\n".join(f"• {line}" for line in hire_lines[:10])
        return f"Final Selected – {role_label}:\n{top_lines}"

    def _handle_last_run_summary(self) -> CommandResult:
        summary = SummaryStore.get_l2_summary()
        if not summary:
            return "No Arjun L2 runs have completed yet."

        return (
            "Last Arjun L2 run:\n"
            f"Candidates seen: {summary.total_seen}\n"
            f"Evaluated: {summary.evaluated}\n"
            f"Hires: {summary.hires}\n"
            f"Rejects: {summary.rejects}\n"
            f"On hold (missing L2 transcript): {summary.on_hold_missing_l2_transcript}\n"
            f"Data incomplete: {summary.data_incomplete}\n"
            f"Hold: {summary.hold_decisions} (manual-review: {summary.needs_manual_review}, backup: {summary.hold_backup_pool})\n"
            f"Errors: {summary.errors}"
        )

    def _handle_chat(self, user_message: str, channel_id: Optional[str] = None) -> CommandResult:
        """Handle conversational chat mode for Arjun via LLM."""
        placeholder_ts: Optional[str] = None
        used_placeholder = False
        error_fallback = "I ran into an error responding. Try summary, hires, last-run-summary, or review."

        try:
            from arjun_chat_handler import get_chat_handler

            chat_handler = get_chat_handler()
            if channel_id and self._slack_client and looks_like_long_running_intent(user_message):
                placeholder_ts = self._slack_client.post_message_get_ts(
                    WORKING_PLACEHOLDER_TEXT,
                    channel=channel_id,
                )
                used_placeholder = bool(placeholder_ts)

            response = chat_handler.handle_chat(
                user_message=user_message,
                channel_id=channel_id,
            )

            if used_placeholder and placeholder_ts and self._slack_client:
                updated = self._slack_client.update_message(
                    channel=channel_id,
                    ts=placeholder_ts,
                    text=response,
                )
                if updated:
                    return response

            return self._dispatch_response(response, channel_id)
        except Exception:
            if used_placeholder and placeholder_ts and self._slack_client and channel_id:
                self._slack_client.update_message(
                    channel=channel_id,
                    ts=placeholder_ts,
                    text=error_fallback,
                )
                return error_fallback
            return self._dispatch_response(error_fallback, channel_id)

    @staticmethod
    def _map_l2_next_step(status: Optional[str]) -> str:
        mapping = {
            "HIRE": "Move to Final Selected",
            "REJECT": "Reject",
            "HOLD": "Await recruiter decision",
            "ON_HOLD_MISSING_L2_TRANSCRIPT": "On hold – missing L2 transcript",
            "DATA_INCOMPLETE_L2": "On hold – data incomplete",
        }
        return mapping.get(status, "Awaiting recruiter action")

    @staticmethod
    def _help_text() -> str:
        return (
            "Supported commands:\n"
            "• @Arjun summary <Candidate> - <Role>\n"
            "• @Arjun hires <Role>\n"
            "• @Arjun last-run-summary\n"
            "• @Arjun review <Candidate> - <Role> (trigger manual L2 review)"
        )
