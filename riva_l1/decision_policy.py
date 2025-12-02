"""Centralized policy definitions for Riva L1 decisions.

The policy is intentionally declarative so the decision engine, Slack surfaces,
and documentation can share a single set of thresholds and guidance.
"""

from __future__ import annotations

from typing import Dict, List

MOVE_TO_L2_MIN_SCORE = 0.7
"""Minimum normalized fit score (0-1) to automatically move candidates to L2."""

REJECT_MAX_SCORE = 0.4
"""Maximum normalized fit score (0-1) where candidates are rejected outright."""

DATA_INCOMPLETE_RISK_CODES = {"data_incomplete", "missing_non_critical_info"}
"""Risk codes that force a hold so recruiters can upload the missing artifacts."""

HARD_BLOCK_FLAGS = {"hard_block", "mandatory_criteria_failed"}
"""Risk flags that immediately reject a candidate regardless of score."""

L1_POLICY: Dict[str, Dict[str, object]] = {
    "move_to_l2": {
        "fit_score_min": MOVE_TO_L2_MIN_SCORE,
        "fit_score_max": 1.0,
        "risk_flag_examples": ["clean_profile", "strong_alignment"],
        "recommended_actions": "Share highlights with the hiring manager and route to L2 immediately.",
    },
    "hold_manual_review": {
        "fit_score_min": REJECT_MAX_SCORE,
        "fit_score_max": MOVE_TO_L2_MIN_SCORE,
        "risk_flag_examples": ["low_confidence_signal", "borderline_experience", "alignment_questions"],
        "recommended_actions": "Human reviewer should skim the transcript/resume, clarify open questions, and rerun once resolved.",
    },
    "hold_data_incomplete": {
        "fit_score_min": 0.0,
        "fit_score_max": MOVE_TO_L2_MIN_SCORE,
        "risk_flag_examples": ["missing_non_critical_doc", "missing_transcript"],
        "recommended_actions": "Upload the missing JD/resume/transcript. Rerun the candidate after Normalizer rebuilds artifacts.",
    },
    "reject_at_l1": {
        "fit_score_min": 0.0,
        "fit_score_max": REJECT_MAX_SCORE,
        "risk_flag_examples": ["hard_block", "salary_mismatch", "experience_gap"],
        "recommended_actions": "Notify the recruiter of the rejection with the top risk flags for transparency.",
    },
}
