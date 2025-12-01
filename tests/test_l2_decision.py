
import pytest
from arjun_l2.decision_engine import decide_l2_outcome

def test_l2_decision_advance_to_final():
    # Strong candidate
    evaluation = {
        "final_score": 90,
        "communication_depth": "Excellent communication skills",
        "leadership_assessment": "Strong leadership potential",
        "final_recommendation": "HIRE",
        "risk_flags": [],
        "concerns": []
    }
    assert decide_l2_outcome(evaluation) == "ADVANCE_TO_FINAL"

def test_l2_decision_reject_low_score():
    # Low score
    evaluation = {
        "final_score": 40,
        "communication_depth": "Poor communication",
        "final_recommendation": "REJECT",
        "risk_flags": [],
        "concerns": []
    }
    assert decide_l2_outcome(evaluation) == "REJECT_AT_L2"

def test_l2_decision_reject_hard_block():
    # Hard block
    evaluation = {
        "final_score": 90,
        "communication_depth": "Excellent",
        "final_recommendation": "HIRE",
        "risk_flags": ["integrity issue"],
        "concerns": []
    }
    assert decide_l2_outcome(evaluation) == "REJECT_AT_L2"

def test_l2_decision_hold_exec_review():
    # Mid-band score, decent communication
    evaluation = {
        "final_score": 75,
        "communication_depth": "Good communication",
        "final_recommendation": "HOLD",
        "risk_flags": [],
        "concerns": []
    }
    assert decide_l2_outcome(evaluation) == "HOLD_EXEC_REVIEW"

def test_l2_decision_hold_data_incomplete():
    # Missing info
    evaluation = {
        "final_score": 85,
        "communication_depth": "Good",
        "final_recommendation": "HIRE",
        "risk_flags": [],
        "concerns": ["missing transcript"]
    }
    assert decide_l2_outcome(evaluation) == "HOLD_DATA_INCOMPLETE"

def test_l2_decision_reject_borderline_communication():
    # High score but weak communication -> Strict Reject
    evaluation = {
        "final_score": 85,
        "communication_depth": "Weak communication",
        "final_recommendation": "HIRE",
        "risk_flags": [],
        "concerns": []
    }
    # Communication score will be < 0.5 due to "Weak" keyword
    assert decide_l2_outcome(evaluation) == "REJECT_AT_L2"
