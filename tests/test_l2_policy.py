from arjun_l2.decision_engine import decide_l2_outcome
from arjun_l2.decision_policy import (
    ADVANCE_MIN_SCORE,
    EXEC_HOLD_MIN_SCORE,
    REJECT_MAX_SCORE,
)


def _make_eval(score: float, recommendation: str = "HIRE", communication: str = "Strong communicator"):
    return {
        "final_score": int(score * 100),
        "communication_depth": communication,
        "leadership_assessment": "Strong leadership",
        "final_recommendation": recommendation,
        "risk_flags": [],
        "concerns": [],
    }


def test_l2_policy_advance_threshold_matches_constant():
    evaluation = _make_eval(ADVANCE_MIN_SCORE, recommendation="HIRE")
    assert decide_l2_outcome(evaluation) == "ADVANCE_TO_FINAL"


def test_l2_policy_reject_threshold_matches_constant():
    evaluation = _make_eval(REJECT_MAX_SCORE, recommendation="REJECT", communication="Weak communication")
    assert decide_l2_outcome(evaluation) == "REJECT_AT_L2"


def test_l2_policy_hold_band_matches_constants():
    evaluation = _make_eval(EXEC_HOLD_MIN_SCORE, recommendation="HOLD", communication="Good communication skills")
    assert decide_l2_outcome(evaluation) == "HOLD_EXEC_REVIEW"
