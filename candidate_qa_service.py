from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Literal, Optional, Sequence, Tuple


Stage = Literal["L1", "L2"]


@dataclass
class CandidateQAResult:
    """Structured response describing how a work query should be handled."""

    kind: Literal["candidate_status", "batch_status", "batch_run", "not_found"]
    stage: Stage
    message: Optional[str] = None
    batch_action: Optional[Stage] = None
    candidate_name: Optional[str] = None
    role_name: Optional[str] = None


class CandidateQAService:
    """Lightweight router that interprets work-style Slack text and fetches data."""

    def __init__(
        self,
        *,
        stage: Stage,
    candidate_summary_provider: Callable[[str, Optional[str]], Optional[str]],
        batch_summary_provider: Callable[[], str],
    ) -> None:
        self.stage = stage
        self._candidate_summary_provider = candidate_summary_provider
        self._batch_summary_provider = batch_summary_provider

        # Precompile regexes for speed
        self._split_pattern = re.compile(r"\s*[-\u2013]\s*")
        self._status_pattern = re.compile(
            r"(?:status|summary|outcome|result|decision|evaluate|review)\s+"
            r"(?P<candidate>[A-Za-z][A-Za-z\s]+?)\s*(?:for|-)\s*(?P<role>[A-Za-z0-9][A-Za-z0-9\s]+)",
            re.IGNORECASE,
        )
        self._fallback_pattern = re.compile(
            r"(?P<candidate>[A-Za-z][A-Za-z\s]+?)\s+for\s+(?P<role>[A-Za-z0-9][A-Za-z0-9\s]+)",
            re.IGNORECASE,
        )
        self._candidate_only_pattern = re.compile(
            r"(?:status of|status for|status on|how is|where is|update on|status)\s+(?P<candidate>[A-Za-z][A-Za-z\s]+)",
            re.IGNORECASE,
        )
        self._trailing_noise_words = {
            "doing",
            "going",
            "looking",
            "progress",
            "coming",
            "performing",
            "perform",
            "faring",
        }

    def answer_query(self, text: Optional[str]) -> Optional[CandidateQAResult]:
        if not text:
            return None

        normalized = text.strip().lower()
        if not normalized:
            return None

        if self._looks_like_batch_run(normalized):
            return CandidateQAResult(kind="batch_run", stage=self.stage, batch_action=self.stage)

        if self._looks_like_batch_status(normalized):
            summary = self._batch_summary_provider()
            if summary:
                return CandidateQAResult(kind="batch_status", stage=self.stage, message=summary)
            return CandidateQAResult(
                kind="not_found",
                stage=self.stage,
                message="No completed runs found for this pipeline.",
            )

        parsed = self._extract_candidate_role(text)
        if parsed:
            candidate, role = parsed
            summary = self._candidate_summary_provider(candidate, role)
            if summary:
                return CandidateQAResult(
                    kind="candidate_status",
                    stage=self.stage,
                    message=summary,
                    candidate_name=candidate,
                    role_name=role,
                )
            return CandidateQAResult(
                kind="not_found",
                stage=self.stage,
                message=(
                    f"No record found for {candidate}." if not role else f"No record found for {candidate} – {role}."
                ),
                candidate_name=candidate,
                role_name=role,
            )

        return None

    # ------------------------------------------------------------------
    # Heuristics
    # ------------------------------------------------------------------
    def _looks_like_batch_run(self, normalized: str) -> bool:
        run_keywords = ("run", "start", "trigger", "kick off", "kickoff")
        batch_keywords = ("batch", "pipeline")
        if any(word in normalized for word in run_keywords) and any(
            word in normalized for word in batch_keywords
        ):
            return True
        if f"run {self.stage.lower()}" in normalized:
            return True
        return False

    def _looks_like_batch_status(self, normalized: str) -> bool:
        status_keywords = ("latest", "last", "recent", "outcome", "results", "summary", "metrics")
        if any(word in normalized for word in status_keywords) and (
            "batch" in normalized or "pipeline" in normalized or "run" in normalized
        ):
            return True
        return False

    def _extract_candidate_role(self, text: str) -> Optional[tuple[str, Optional[str]]]:
        # First try explicit dash notation: "Candidate - Role"
        if "-" in text or "\u2013" in text:
            parts = self._split_pattern.split(text, maxsplit=1)
            if len(parts) == 2:
                candidate = self._strip_trailing_noise(parts[0].strip())
                role = parts[1].strip()
                if candidate and role:
                    return candidate, role

        # Structured phrases like "status of Priya Shah for Product Manager"
        match = self._status_pattern.search(text)
        if match:
            candidate = self._strip_trailing_noise(match.group("candidate").strip())
            role = match.group("role").strip()
            if candidate and role:
                return candidate, role

        # Generic fallback "evaluate Priya Shah for Product Manager"
        match = self._fallback_pattern.search(text)
        if match:
            candidate = self._strip_trailing_noise(match.group("candidate").strip())
            role = match.group("role").strip()
            if candidate and role:
                return candidate, role

        match = self._candidate_only_pattern.search(text)
        if match:
            candidate = self._strip_trailing_noise(match.group("candidate").strip())
            if candidate:
                return candidate, None
        return None

    def _strip_trailing_noise(self, candidate: str) -> str:
        if not candidate:
            return candidate

        tokens = candidate.split()
        while tokens:
            cleaned = tokens[-1].strip("?.!,").lower()
            if cleaned in self._trailing_noise_words:
                tokens.pop()
                continue
            break

        return " ".join(tokens).strip()


def format_l1_candidate_answer(
    *,
    candidate_name: str,
    role_name: Optional[str],
    decision_label: Optional[str],
    fit_score: Optional[float],
    risk_flags: Optional[Sequence[str]] = None,
    additional_sections: Optional[List[Tuple[str, Optional[str]]]] = None,
) -> str:
    """Compose a consistent L1 candidate answer for Slack/QA flows."""

    lines: List[str] = []
    role_display = role_name or "Unknown role"
    lines.append(f"{candidate_name} — {role_display}")

    if decision_label:
        lines.append(f"L1 Decision: {decision_label}")

    if fit_score is not None:
        lines.append(f"Fit score: {fit_score}")

    risk_text = _format_risk_flag_line(risk_flags)
    if risk_text:
        lines.append(risk_text)

    for section_label, value in additional_sections or []:
        if value:
            lines.append(f"{section_label}: {value}")

    return "\n".join(lines)


def format_l2_candidate_answer(
    *,
    candidate_name: str,
    role_name: Optional[str],
    decision_label: Optional[str],
    l2_summary: Optional[str],
    l1_l2_alignment: Optional[str],
    risk_flags: Optional[Sequence[str]] = None,
    additional_sections: Optional[List[Tuple[str, Optional[str]]]] = None,
) -> str:
    """Compose a consistent L2 candidate answer for Slack/QA flows."""

    lines: List[str] = []
    role_display = role_name or "Unknown role"
    lines.append(f"{candidate_name} — {role_display}")

    if decision_label:
        lines.append(f"L2 Decision: {decision_label}")

    if l2_summary:
        lines.append(f"L2 Summary: {l2_summary}")

    if l1_l2_alignment:
        lines.append(f"L1 vs L2: {l1_l2_alignment}")

    risk_text = _format_risk_flag_line(risk_flags)
    if risk_text:
        lines.append(risk_text)

    for section_label, value in additional_sections or []:
        if value:
            lines.append(f"{section_label}: {value}")

    return "\n".join(lines)


def _format_risk_flag_line(risk_flags: Optional[Sequence[str]]) -> Optional[str]:
    if not risk_flags:
        return None
    cleaned = [flag.strip() for flag in risk_flags if flag and flag.strip()]
    if not cleaned:
        return None
    return f"Risk flags: {', '.join(cleaned)}"