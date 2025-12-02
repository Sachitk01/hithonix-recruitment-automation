from candidate_qa_service import (
    CandidateQAService,
    format_l1_candidate_answer,
    format_l2_candidate_answer,
)


def _noop_batch_summary():
    return "Batch summary"


def test_candidate_query_without_role_returns_status_result():
    captured = {}

    def candidate_provider(candidate: str, role):
        captured["candidate"] = candidate
        captured["role"] = role
        if candidate.lower() == "priya shah" and role is None:
            return "Priya passed all L1 checks."
        return None

    service = CandidateQAService(
        stage="L1",
        candidate_summary_provider=candidate_provider,
        batch_summary_provider=_noop_batch_summary,
    )

    result = service.answer_query("Status of Priya Shah")

    assert result is not None
    assert result.kind == "candidate_status"
    assert result.candidate_name == "Priya Shah"
    assert result.role_name is None
    assert "L1" in result.message
    assert captured["role"] is None


def test_candidate_query_without_matching_record_returns_not_found():
    def candidate_provider(candidate: str, role):
        return None

    service = CandidateQAService(
        stage="L2",
        candidate_summary_provider=candidate_provider,
        batch_summary_provider=_noop_batch_summary,
    )

    result = service.answer_query("How is Rahul Menon doing?")

    assert result is not None
    assert result.kind == "not_found"
    assert result.candidate_name == "Rahul Menon"
    assert result.role_name is None
    assert "Rahul Menon" in (result.message or "")


def test_format_l1_candidate_answer_includes_risk_flags():
    text = format_l1_candidate_answer(
        candidate_name="Priya Shah",
        role_name="Product Manager",
        decision_label="Hold (Manual Review)",
        fit_score=55,
        risk_flags=["missing_non_critical_doc", "borderline_experience"],
        additional_sections=[("Next step", "Upload missing docs")],
    )

    assert "Priya Shah — Product Manager" in text
    assert "L1 Decision: Hold (Manual Review)" in text
    assert "Fit score: 55" in text
    assert "Risk flags: missing_non_critical_doc, borderline_experience" in text
    assert "Next step: Upload missing docs" in text


def test_format_l1_candidate_answer_omits_empty_risk_flags():
    text = format_l1_candidate_answer(
        candidate_name="Rahul Menon",
        role_name="Support Engineer",
        decision_label="Move to L2",
        fit_score=82,
        risk_flags=[],
        additional_sections=None,
    )

    assert "Move to L2" in text
    assert "Risk flags" not in text


def test_format_l2_candidate_answer_includes_sections():
    text = format_l2_candidate_answer(
        candidate_name="Priya Shah",
        role_name="Product Manager",
        decision_label="Move to Final Selected",
        l2_summary="Strong exec presence.",
        l1_l2_alignment="IMPROVED",
        risk_flags=["backup_pool_candidate"],
        additional_sections=[("Next step", "Prep offer packet")],
    )

    assert "L2 Decision: Move to Final Selected" in text
    assert "L2 Summary: Strong exec presence." in text
    assert "L1 vs L2: IMPROVED" in text
    assert "Risk flags: backup_pool_candidate" in text
    assert "Next step: Prep offer packet" in text


def test_format_l2_candidate_answer_omits_empty_values():
    text = format_l2_candidate_answer(
        candidate_name="Rahul Menon",
        role_name=None,
        decision_label=None,
        l2_summary=None,
        l1_l2_alignment=None,
        risk_flags=[],
        additional_sections=[("Next step", None)],
    )

    assert "Rahul Menon — Unknown role" in text
    assert "L2 Decision" not in text
    assert "Risk flags" not in text
