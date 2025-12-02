from riva_l1.decision_engine import decide_l1_outcome
from riva_l1.decision_policy import MOVE_TO_L2_MIN_SCORE, REJECT_MAX_SCORE


def _make_eval(fit_score: float, extra: dict | None = None):
    payload = {
        "fit_score": fit_score,
        "red_flags": [],
        "concerns": [],
    }
    if extra:
        payload.update(extra)
    return payload


def test_move_threshold_matches_policy():
    evaluation = _make_eval(int(MOVE_TO_L2_MIN_SCORE * 100))
    assert decide_l1_outcome(evaluation) == "MOVE_TO_L2"


def test_reject_threshold_matches_policy():
    evaluation = _make_eval(int(REJECT_MAX_SCORE * 100))
    assert decide_l1_outcome(evaluation) == "REJECT_AT_L1"
