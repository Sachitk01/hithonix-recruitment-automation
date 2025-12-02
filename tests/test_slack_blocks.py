
import pytest
from types import SimpleNamespace
from unittest.mock import Mock
from slack_blocks import (
    build_batch_summary_blocks,
    build_status_header,
    build_summary_stats,
    build_candidate_groups,
    build_candidate_row,
    build_footer,
)


def test_build_status_header_l1():
    """Test L1 header block."""
    summary = Mock()
    summary.total_seen = 10
    
    blocks = build_status_header(summary, "L1")
    
    assert len(blocks) == 1
    assert blocks[0]["type"] == "header"
    assert "🟢" in blocks[0]["text"]["text"]
    assert "Riva L1" in blocks[0]["text"]["text"]
    assert "10 candidates" in blocks[0]["text"]["text"]


def test_build_status_header_l2():
    """Test L2 header block."""
    summary = Mock()
    summary.total_seen = 5
    
    blocks = build_status_header(summary, "L2")
    
    assert len(blocks) == 1
    assert blocks[0]["type"] == "header"
    assert "🟣" in blocks[0]["text"]["text"]
    assert "Arjun L2" in blocks[0]["text"]["text"]


def test_build_summary_stats_l1():
    """Test L1 summary stats."""
    summary = Mock()
    summary.evaluated = 3
    summary.moved_to_l2 = 3
    summary.rejected_at_l1 = 0
    summary.needs_manual_review = 0
    summary.data_incomplete = 2
    summary.errors = [SimpleNamespace() for _ in range(5)]
    
    blocks = build_summary_stats(summary, "L1")
    
    assert len(blocks) == 1
    assert blocks[0]["type"] == "section"
    assert "fields" in blocks[0]
    # Check for evaluated and moved fields
    fields_text = " ".join([f["text"] for f in blocks[0]["fields"]])
    assert "Evaluated" in fields_text
    assert "Moved to L2" in fields_text
    assert "Hold (Data Incomplete)" in fields_text
    assert "Errors" in fields_text


def test_build_summary_stats_l2():
    """Test L2 summary stats."""
    summary = Mock()
    summary.evaluated = 5
    summary.hires = 3
    summary.rejects = 2
    summary.needs_manual_review = 1
    summary.data_incomplete = 0
    summary.errors = 0
    
    blocks = build_summary_stats(summary, "L2")
    
    assert len(blocks) == 1
    fields_text = " ".join([f["text"] for f in blocks[0]["fields"]])
    assert "Advanced to Final" in fields_text
    assert "Rejected at L2" in fields_text
    assert "Hold (Exec Review)" in fields_text


def test_build_candidate_row():
    """Test individual candidate row."""
    candidate = Mock()
    candidate.candidate_name = "John Doe"
    candidate.role = "IT Support"
    candidate.folder_link = "https://drive.google.com/123"
    candidate.feedback_link = "https://docs.google.com/456"
    candidate.dashboard_link = None
    candidate.reason = None
    candidate.hold_reason = None
    
    blocks = build_candidate_row(candidate, "move_to_l2")
    
    assert len(blocks) >= 1
    assert blocks[0]["type"] == "section"
    text = blocks[0]["text"]["text"]
    assert "*John Doe*" in text
    assert "IT Support" in text
    assert "https://drive.google.com/123" in text


def test_build_candidate_row_with_hold_reason():
    """Test candidate row with hold reason."""
    candidate = Mock()
    candidate.candidate_name = "Jane Smith"
    candidate.role = "IT Admin"
    candidate.folder_link = None
    candidate.feedback_link = None
    candidate.dashboard_link = None
    candidate.reason = "missing non-critical info (missing_resume_or_jd)"
    candidate.hold_reason = "missing_noncritical_info"
    
    blocks = build_candidate_row(candidate, "hold")
    
    assert len(blocks) == 2  # Main block + context block for reason
    assert blocks[0]["type"] == "section"
    assert blocks[1]["type"] == "context"
    assert "Reason:" in blocks[1]["elements"][0]["text"]


def test_rejected_candidate_row_shows_risk_flags():
    candidate = Mock()
    candidate.candidate_name = "Aria"
    candidate.role = "IT Support"
    candidate.folder_link = None
    candidate.feedback_link = None
    candidate.dashboard_link = None
    candidate.risk_flags = ["low_experience", "salary_mismatch", "culture_gap", "location_mismatch"]

    blocks = build_candidate_row(candidate, "reject")

    assert len(blocks) == 2  # section + risk context
    risk_block = blocks[1]
    assert risk_block["type"] == "context"
    assert "Reasons:" in risk_block["elements"][0]["text"]
    assert "low_experience" in risk_block["elements"][0]["text"]
    assert "…" in risk_block["elements"][0]["text"]


def test_hold_manual_review_row_shows_risk_flags():
    candidate = Mock()
    candidate.candidate_name = "Maya"
    candidate.role = "IT Support"
    candidate.folder_link = None
    candidate.feedback_link = None
    candidate.dashboard_link = None
    candidate.reason = "manual review required"
    candidate.hold_reason = "manual_review_required"
    candidate.risk_flags = ["missing_non_critical_doc", "borderline_experience"]

    blocks = build_candidate_row(candidate, "hold")

    assert len(blocks) == 3  # section + reason + risk flags
    risk_block = blocks[-1]
    assert risk_block["type"] == "context"
    assert "borderline_experience" in risk_block["elements"][0]["text"]


def test_build_batch_summary_blocks_l1():
    """Test complete L1 batch summary."""
    summary = Mock()
    summary.total_seen = 10
    summary.evaluated = 3
    summary.moved_to_l2 = 3
    summary.rejected_at_l1 = 0
    summary.needs_manual_review = 0
    summary.data_incomplete = 2
    summary.errors = [SimpleNamespace() for _ in range(5)]
    
    # Create mock candidates
    candidate1 = Mock()
    candidate1.candidate_name = "Manish"
    candidate1.role = "IT Support"
    candidate1.decision = "move_to_l2"
    candidate1.folder_link = None
    candidate1.feedback_link = None
    candidate1.dashboard_link = None
    candidate1.reason = None
    candidate1.hold_reason = None
    
    candidate2 = Mock()
    candidate2.candidate_name = "Nithesh Shetty"
    candidate2.role = "IT Support"
    candidate2.decision = "hold"
    candidate2.folder_link = None
    candidate2.feedback_link = None
    candidate2.dashboard_link = None
    candidate2.reason = "missing non-critical info"
    candidate2.hold_reason = "missing_noncritical_info"
    
    summary.candidates = [candidate1, candidate2]
    
    blocks = build_batch_summary_blocks(summary, "L1")
    
    # Should have header, divider, stats, divider, candidate groups, footer
    assert len(blocks) > 5
    assert blocks[0]["type"] == "header"
    assert any(b["type"] == "divider" for b in blocks)
    # Check footer exists
    assert blocks[-1]["type"] == "context"
    assert "Hithonix" in blocks[-1]["elements"][0]["text"]


def test_build_candidate_groups_truncation():
    """Test that candidate groups are truncated at 15."""
    candidates = []
    for i in range(20):
        c = Mock()
        c.candidate_name = f"Candidate {i}"
        c.role = "IT Support"
        c.decision = "move_to_l2"
        c.folder_link = None
        c.feedback_link = None
        c.dashboard_link = None
        c.reason = None
        c.hold_reason = None
        candidates.append(c)
    
    blocks = build_candidate_groups(candidates, "L1")
    
    # Should have group header + (15 candidate blocks * ~1-2 blocks each) + "...and X more" context + divider
    # Count section blocks for candidates (each is 1 block)
    section_blocks = [b for b in blocks if b["type"] == "section"]
    # First section is group header, then max 15 candidates
    assert len(section_blocks) <= 16  # 1 header + 15 candidates
    
    # Check for "...and X more" message
    context_blocks = [b for b in blocks if b["type"] == "context"]
    more_text = " ".join([b["elements"][0]["text"] for b in context_blocks])
    assert "and 5 more" in more_text


def test_empty_batch():
    """Test batch with no candidates."""
    summary = Mock()
    summary.total_seen = 0
    summary.evaluated = 0
    summary.moved_to_l2 = 0
    summary.rejected_at_l1 = 0
    summary.needs_manual_review = 0
    summary.data_incomplete = 0
    summary.errors = []
    summary.candidates = []
    
    blocks = build_batch_summary_blocks(summary, "L1")
    
    # Should still have header, stats, footer
    assert len(blocks) > 0
    assert blocks[0]["type"] == "header"


def test_error_details_section_included_for_l1_summary():
    summary = Mock()
    summary.total_seen = 3
    summary.evaluated = 1
    summary.moved_to_l2 = 0
    summary.rejected_at_l1 = 0
    summary.needs_manual_review = 0
    summary.data_incomplete = 0
    summary.candidates = []
    summary.errors = [
        SimpleNamespace(
            candidate_name=f"Candidate {i}",
            role="IT Support",
            folder_id=f"folder{i}",
            error_code="drive_access_denied",
            error_message="Service account missing access",
        )
        for i in range(4)
    ]

    blocks = build_batch_summary_blocks(summary, "L1")

    error_sections = [
        block
        for block in blocks
        if block.get("type") == "section"
        and isinstance(block.get("text"), dict)
        and "Errors detected" in block["text"].get("text", "")
    ]

    assert error_sections, "Expected errors section to be rendered"
    text = error_sections[0]["text"]["text"]
    assert "Candidate 0" in text
    assert "Candidate 2" in text
    assert "more errors" in text  # indicates truncation message
