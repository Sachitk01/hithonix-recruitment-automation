import json

import pytest

import slack_bots
from riva_l1.riva_l1_models import L1BatchError, L1BatchSummary
from slack_bots import ArjunSlackBot, RivaSlackBot
from summary_store import SummaryStore


class StubDrive:
    def __init__(self, folder_children, file_listing, file_payloads):
        self.folder_children = folder_children
        self.file_listing = file_listing
        self.file_payloads = file_payloads

    def list_folder_like(self, folder_id, correlation_id=None):
        return self.folder_children.get(folder_id, [])

    @staticmethod
    def get_real_folder_id(item):
        return item["id"]

    def list_files(self, folder_id, correlation_id=None):
        return self.file_listing.get(folder_id, [])

    def download_file_bytes(self, file_id):
        return self.file_payloads[file_id]


@pytest.fixture(autouse=True)
def reset_summary_store():
    SummaryStore.reset()
    yield
    SummaryStore.reset()


@pytest.fixture(autouse=True)
def override_folder_maps(monkeypatch):
    monkeypatch.setattr(slack_bots, "L1_FOLDERS", {"IT Support": "l1_it"})
    monkeypatch.setattr(slack_bots, "L2_FOLDERS", {"IT Support": "l2_it"})
    monkeypatch.setattr(slack_bots, "PROFILES_FINAL_SELECTED_FOLDERS", {"IT Support": "profiles_final_it"})
    monkeypatch.setattr(slack_bots, "PROFILES_L1_REJECTED_FOLDERS", {"IT Support": "profiles_l1_reject_it"})
    monkeypatch.setattr(slack_bots, "PROFILES_L2_REJECTED_FOLDERS", {"IT Support": "profiles_l2_reject_it"})


def _build_drive_for_candidate(result_payload, status_payload=None):
    files = [
        {"id": "cand_result", "name": "l1_result.json"},
    ]
    payloads = {"cand_result": json.dumps(result_payload).encode("utf-8")}
    if status_payload is not None:
        files.append({"id": "cand_status", "name": "l1_status.json"})
        payloads["cand_status"] = json.dumps(status_payload).encode("utf-8")

    return StubDrive(
        folder_children={"l1_it": [{"id": "cand_folder", "name": "Jane Doe"}]},
        file_listing={"cand_folder": files},
        file_payloads=payloads,
    )


def test_riva_summary_command_returns_formatted_response():
    drive = _build_drive_for_candidate(
        {
            "overall_score": 82,
            "strengths": ["Communication"],
            "risks": ["Experience gap"],
            "pipeline_recommendation": "SEND_TO_L2",
            "final_decision": "SEND_TO_L2",
        },
        {"status": "SEND_TO_L2"},
    )

    bot = RivaSlackBot(drive_factory=lambda: drive)
    response = bot.handle_command("summary Jane Doe - IT Support")

    assert "Jane Doe — IT Support" in response
    assert "L1 Decision: Move to L2" in response
    assert "Fit score: 82" in response
    assert "Risk flags: Experience gap" in response
    assert "Next step: Ready for L2" in response


def test_riva_summary_omits_risk_line_when_not_present():
    drive = _build_drive_for_candidate(
        {
            "overall_score": 70,
            "strengths": ["Domain knowledge"],
            "risks": [],
            "pipeline_recommendation": "HOLD",
            "final_decision": "HOLD",
            "rationale": "Needs more clarity on roadmap",
        },
        {"status": "HOLD"},
    )

    bot = RivaSlackBot(drive_factory=lambda: drive)
    response = bot.handle_command("summary Jane Doe - IT Support")

    assert "L1 Decision: Hold (Manual Review)" in response
    assert "Risk flags" not in response


def test_riva_last_run_summary_reports_cached_values():
    summary = L1BatchSummary(
        total_seen=5,
        evaluated=4,
        moved_to_l2=2,
        rejected_at_l1=1,
        hold_decisions=2,
        needs_manual_review=2,
        hold_missing_transcript=1,
        hold_data_incomplete=1,
        hold_low_confidence=0,
        hold_ambiguous=0,
        hold_jd_mismatch=0,
        on_hold_missing_transcript=1,
        data_incomplete=1,
        errors=[],
    )
    SummaryStore.set_l1_summary(summary)

    bot = RivaSlackBot(drive_factory=lambda: StubDrive({}, {}, {}))
    response = bot.handle_command("last-run-summary")

    assert "Candidates seen: 5" in response
    assert "Sent to L2: 2" in response
    assert "Hold: 2 (manual-review: 2, backup: 0, missing transcript: 1" in response


def test_riva_last_run_summary_includes_error_details():
    summary = L1BatchSummary(
        total_seen=3,
        evaluated=1,
        moved_to_l2=0,
        rejected_at_l1=0,
        hold_decisions=0,
        needs_manual_review=0,
        hold_missing_transcript=0,
        hold_data_incomplete=0,
        errors=[
            L1BatchError(
                candidate_name="Alice",
                role="IT Support",
                folder_id="folder123",
                error_code="drive_access_denied",
                error_message="Drive permissions revoked",
            ),
            L1BatchError(
                candidate_name="Bob",
                role="IT Support",
                error_code="llm_evaluation_failed",
                error_message="OpenAI timeout",
            ),
            L1BatchError(
                candidate_name="Cara",
                role="IT Support",
                error_code="missing_critical_doc",
                error_message="Transcript missing after upload",
            ),
            L1BatchError(
                candidate_name="Dee",
                role="IT Support",
                error_code="network_issue",
                error_message="Network outage",
            ),
        ],
    )
    SummaryStore.set_l1_summary(summary)

    bot = RivaSlackBot(drive_factory=lambda: StubDrive({}, {}, {}))
    response = bot.handle_command("last-run-summary")

    assert "Errors:" in response
    assert "Alice — IT Support" in response
    assert "drive_access_denied" in response
    assert "Bob" in response
    assert "more errors" in response  # indicates truncation notice


def test_arjun_summary_command_returns_formatted_response(monkeypatch):
    monkeypatch.setattr(slack_bots, "L2_FOLDERS", {"IT Support": "l2_it"})
    drive = StubDrive(
        folder_children={"l2_it": [{"id": "cand2", "name": "Jane Doe"}]},
        file_listing={
            "cand2": [
                {"id": "cand2_result", "name": "l2_result.json"},
                {"id": "cand2_status", "name": "l2_status.json"},
            ]
        },
        file_payloads={
            "cand2_result": json.dumps(
                {
                    "final_recommendation": "HIRE",
                    "l2_summary": "Strong on infra.",
                    "l1_l2_comparison": "IMPROVED",
                    "risk_flags": ["None"],
                }
            ).encode("utf-8"),
            "cand2_status": json.dumps({"status": "HIRE"}).encode("utf-8"),
        },
    )

    bot = ArjunSlackBot(drive_factory=lambda: drive)
    response = bot.handle_command("summary Jane Doe - IT Support")

    assert "Jane Doe — IT Support" in response
    assert "L2 Decision: Move to Final Selected" in response
    assert "L2 Summary: Strong on infra." in response
    assert "L1 vs L2: IMPROVED" in response
    assert "Risk flags: None" in response
    assert "Next step: Move to Final Selected" in response


def test_arjun_hires_command_lists_candidates():
    drive = StubDrive(
        folder_children={
            "profiles_final_it": [{"id": "cand3", "name": "Alex"}],
        },
        file_listing={
            "cand3": [
                {"id": "cand3_result", "name": "l2_result.json"},
            ]
        },
        file_payloads={
            "cand3_result": json.dumps(
                {
                    "final_recommendation": "HIRE",
                    "l1_l2_comparison": "CONSISTENT",
                    "final_score": 90,
                }
            ).encode("utf-8"),
        },
    )

    bot = ArjunSlackBot(drive_factory=lambda: drive)
    response = bot.handle_command("hires IT Support")

    assert "Final Selected" in response
    assert "Alex" in response
    assert "Score: 90" in response
