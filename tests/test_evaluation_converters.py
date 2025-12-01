from evaluation_converters import (
    candidate_event_decision_from_l2,
    convert_arjun_result,
    convert_riva_result,
    l2_alignment_from_scores,
)
from riva_l1.riva_l1_models import RivaL1Result
from arjun_l2.arjun_l2_models import ArjunL2Result


def test_convert_riva_result_normalizes_scores():
    raw = RivaL1Result(
        match_summary="Great fit",
        strengths=["Leadership", "Execution"],
        concerns=["Limited domain depth"],
        behavioral_signals="Strong",
        communication_signals="Clear",
        red_flags=["Salary misalignment"],
        compensation_alignment="Aligned",
        joining_feasibility="High",
        fit_score=80,
        final_decision="MOVE_TO_L2",
    )

    evaluation = convert_riva_result(
        candidate_id="folder123",
        role="Product Manager",
        pipeline_decision="SEND_TO_L2",
        result=raw,
    )

    assert evaluation.recommendation == "pass"
    assert evaluation.scores["overall_fit"] == 4.0
    assert evaluation.confidence == 0.8
    assert "salary" in evaluation.risk_flags[0].lower()


def test_convert_arjun_result_alignment_and_decision():
    raw = ArjunL2Result(
        leadership_assessment="Excellent",
        technical_capability="Advanced",
        communication_depth="High",
        culture_alignment="High",
        career_potential="Strong",
        strengths=["Strategy"],
        concerns=["Execution depth"],
        risk_flags=["Needs mentorship"],
        final_score=90,
        final_recommendation="HIRE",
        l2_summary="Ready to hire",
        rationale="Demonstrated strong product thinking",
    )

    evaluation = convert_arjun_result(
        candidate_id="folder456",
        role="Engineering Manager",
        pipeline_decision="HIRE",
        result=raw,
        alignment_with_l1="unknown",
    )

    assert evaluation.recommendation == "strong_yes"
    assert evaluation.scores["final"] == 4.5
    assert evaluation.confidence == 0.9

    alignment = l2_alignment_from_scores(4.0, evaluation.scores["final"])
    assert alignment == "high"


def test_candidate_event_decision_from_l2():
    assert candidate_event_decision_from_l2("lean_yes") == "pass"
    assert candidate_event_decision_from_l2("no") == "reject"
    assert candidate_event_decision_from_l2("unknown") == "hold"