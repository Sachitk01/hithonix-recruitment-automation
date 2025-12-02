"""Utility helpers to convert raw model outputs into standardized evaluations."""

from __future__ import annotations

from typing import Optional

from arjun_l2.arjun_l2_models import ArjunL2Result
from evaluation_models import L1Evaluation, L2Evaluation
from riva_l1.riva_l1_models import RivaL1Result


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _normalize_score(score: Optional[float], max_score: float = 100.0) -> float:
    if score is None:
        return 0.0
    return round(_clamp(float(score), 0.0, max_score) / (max_score / 5.0), 2)


def _normalize_confidence(score: Optional[float], max_score: float = 100.0) -> float:
    if score is None:
        return 0.0
    return round(_clamp(float(score), 0.0, max_score) / max_score, 2)


def map_l1_pipeline_decision(decision: str) -> str:
    mapping = {
        "SEND_TO_L2": "pass",
        "REJECT_AT_L1": "reject",
        "HOLD": "hold",
    }
    return mapping.get(decision, "hold")


def map_l2_pipeline_decision(decision: str) -> str:
    mapping = {
        "HIRE": "strong_yes",
        "SHORTLIST": "yes",
        "MOVE_TO_L2": "lean_yes",
        "REJECT": "no",
        "HOLD": "lean_no",
    }
    return mapping.get(decision, "lean_no")


def l2_alignment_from_scores(l1_score: Optional[float], l2_score: Optional[float]) -> str:
    if l1_score is None or l2_score is None:
        return "unknown"
    delta = abs(l2_score - l1_score)
    if delta <= 0.5:
        return "high"
    if delta <= 1.0:
        return "medium"
    return "low"


def convert_riva_result(
    candidate_id: str,
    role: str,
    pipeline_decision: str,
    result: RivaL1Result,
    feedback_link: Optional[str] = None,
    report_link: Optional[str] = None,
) -> L1Evaluation:
    recommendation = map_l1_pipeline_decision(pipeline_decision)
    normalized_score = _normalize_score(result.fit_score)
    confidence = _normalize_confidence(result.fit_score)
    source_flags = (result.risk_flags or []) + (result.red_flags or []) + (result.concerns or [])
    risk_flags = list(dict.fromkeys(source_flags))
    return L1Evaluation(
        candidate_id=candidate_id,
        role=role,
        scores={"overall_fit": normalized_score},
        strengths=result.strengths or [],
        weaknesses=result.concerns or [],
        risk_flags=risk_flags,
        recommendation=recommendation,
        confidence=confidence,
        feedback_link=feedback_link,
        report_link=report_link,
    )


def convert_arjun_result(
    candidate_id: str,
    role: str,
    pipeline_decision: str,
    result: ArjunL2Result,
    alignment_with_l1: str = "unknown",
    feedback_link: Optional[str] = None,
    report_link: Optional[str] = None,
) -> L2Evaluation:
    recommendation = map_l2_pipeline_decision(pipeline_decision)
    normalized_score = _normalize_score(result.final_score)
    confidence = _normalize_confidence(result.final_score)
    return L2Evaluation(
        candidate_id=candidate_id,
        role=role,
        scores={"final": normalized_score},
        strengths=result.strengths or [],
        weaknesses=result.concerns or [],
        risk_flags=result.risk_flags or [],
        recommendation=recommendation,
        confidence=confidence,
        alignment_with_l1=alignment_with_l1,
        feedback_link=feedback_link,
        report_link=report_link,
    )


def candidate_event_decision_from_l2(recommendation: str) -> str:
    positive = {"strong_yes", "yes", "lean_yes"}
    negative = {"lean_no", "no"}
    recommendation = recommendation.lower()
    if recommendation in positive:
        return "pass"
    if recommendation in negative:
        return "reject"
    return "hold"