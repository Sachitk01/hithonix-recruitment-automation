"""Centralized policy definitions for Arjun L2 decisions.

Keeping the thresholds in one module ensures the decision engine, Slack
surfaces, documentation, and tests all share the same values.
"""

from __future__ import annotations

from typing import Dict, List

ADVANCE_MIN_SCORE = 0.80
"""Minimum normalized final score (0-1) required to advance a candidate."""

ADVANCE_MIN_COMMUNICATION = 0.70
"""Minimum normalized communication proxy required for automatic advancement."""

ADVANCE_MIN_LEADERSHIP = 0.75
"""Minimum normalized leadership readiness (when present) for advancement."""

REJECT_MAX_SCORE = 0.50
"""Maximum normalized score where a candidate is rejected outright."""

REJECT_MAX_COMMUNICATION = 0.50
"""Communication floor below which the candidate is rejected regardless of score."""

EXEC_HOLD_MIN_SCORE = 0.65
EXEC_HOLD_MAX_SCORE = 0.80
"""Score band for executive review holds."""

EXEC_HOLD_MIN_COMMUNICATION = 0.60
"""Minimum communication signal to stay in the exec review band."""

DATA_INCOMPLETE_RISK_CODES = {
    "data_incomplete",
    "missing_info",
    "missing_l2_transcript",
    "missing_noncritical_info",
}
"""Risk or reason codes that should force a data-incomplete hold."""

HARD_BLOCK_FLAGS = {
    "hard_block",
    "integrity_violation",
    "mandatory_criteria_failed",
}
"""Risk flags that immediately reject the candidate."""

ARJUN_L2_POLICY: Dict[str, Dict[str, object]] = {
    "advance_to_final": {
        "score_min": ADVANCE_MIN_SCORE,
        "score_max": 1.0,
        "communication_min": ADVANCE_MIN_COMMUNICATION,
        "leadership_min": ADVANCE_MIN_LEADERSHIP,
        "risk_flag_examples": ["clean_exec_alignment", "ready_for_offer"],
        "recommended_actions": "Move the candidate to Final Selected, loop in exec sponsor, and start offer prep.",
    },
    "hold_exec_review": {
        "score_min": EXEC_HOLD_MIN_SCORE,
        "score_max": EXEC_HOLD_MAX_SCORE,
        "communication_min": EXEC_HOLD_MIN_COMMUNICATION,
        "risk_flag_examples": ["needs_exec_review", "scope_alignment_question"],
        "recommended_actions": "Have an executive reviewer skim the transcript/notes to confirm fit before finalizing.",
    },
    "hold_data_incomplete": {
        "score_min": 0.0,
        "score_max": 1.0,
        "risk_flag_examples": ["missing_l2_transcript", "data_incomplete"],
        "recommended_actions": "Collect the missing transcript or context, rerun normalization, then re-evaluate.",
    },
    "reject_at_l2": {
        "score_min": 0.0,
        "score_max": REJECT_MAX_SCORE,
        "risk_flag_examples": ["hard_block", "integrity_violation", "weak_exec_presence"],
        "recommended_actions": "Share the top risk flags with the recruiter for transparent closure.",
    },
}
