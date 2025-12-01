
import pytest
from riva_l1.decision_engine import decide_l1_outcome

def test_l1_decision_move_to_l2():
    # High fit score -> Move to L2
    evaluation = {
        "fit_score": 80,
        "red_flags": [],
        "concerns": []
    }
    assert decide_l1_outcome(evaluation) == "MOVE_TO_L2"

def test_l1_decision_reject_low_score():
    # Low fit score -> Reject
    evaluation = {
        "fit_score": 30,
        "red_flags": [],
        "concerns": []
    }
    assert decide_l1_outcome(evaluation) == "REJECT_AT_L1"

def test_l1_decision_hold_manual_review():
    # Mid fit score -> Hold
    evaluation = {
        "fit_score": 60,
        "red_flags": [],
        "concerns": []
    }
    assert decide_l1_outcome(evaluation) == "HOLD_MANUAL_REVIEW"

def test_l1_decision_hold_data_incomplete():
    # Missing info in concerns
    evaluation = {
        "fit_score": 90,
        "red_flags": [],
        "concerns": ["missing transcript"]
    }
    assert decide_l1_outcome(evaluation) == "HOLD_DATA_INCOMPLETE"

def test_l1_decision_hard_block():
    # Hard block in red flags
    evaluation = {
        "fit_score": 90,
        "red_flags": ["hard block detected"],
        "concerns": []
    }
    assert decide_l1_outcome(evaluation) == "REJECT_AT_L1"

    # Hard block in concerns
    evaluation_concerns = {
        "fit_score": 90,
        "red_flags": [],
        "concerns": ["mandatory criteria failed"]
    }
    assert decide_l1_outcome(evaluation_concerns) == "REJECT_AT_L1"
