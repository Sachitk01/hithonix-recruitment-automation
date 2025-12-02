import json
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from drive_service import DriveManager
from normalizer import Normalizer
from riva_l1.riva_l1_batch import RivaL1BatchProcessor
from riva_l1.riva_l1_models import RivaL1Result

# TODO: Replace live Google Sheets calls with a stubbed service to avoid hitting external APIs during unit tests.


def _make_normalization_report(include_resume=True, include_jd=True, include_transcript=True):
    report = {
        "resume": {"id": "resume_file", "name": "resume.pdf"} if include_resume else None,
        "jd": {"id": "jd_file", "name": "JD_IT_Support.pdf"} if include_jd else None,
        "l1_transcript": {"id": "transcript_file", "name": "L1_transcript.txt"}
        if include_transcript
        else None,
    }
    return report


def _make_riva_result(decision: str, score: Optional[int] = None) -> RivaL1Result:
    if score is None:
        default_scores = {
            "MOVE_TO_L2": 85,
            "REJECT": 30,
            "HOLD": 55,
        }
        score = default_scores.get(decision, 80)

    return RivaL1Result(
        match_summary="summary",
        strengths=["strength"],
        concerns=["concern"],
        behavioral_signals="behavior",
        communication_signals="communication",
        red_flags=["flag"],
        compensation_alignment="HIGH",
        joining_feasibility="HIGH",
        fit_score=score,
        final_decision=decision,
    )


def _build_drive_with_reports(candidate_ids, report_map):
    drive = MagicMock(spec=DriveManager)
    drive.get_real_folder_id.side_effect = lambda item: item["id"]
    drive.move_folder = MagicMock()

    def list_folder_like_side_effect(folder_id, correlation_id=None):
        return [
            {"id": cid, "name": cid.replace("_", " "), "mimeType": "application/vnd.google-apps.folder"}
            for cid in candidate_ids
        ]

    drive.list_folder_like.side_effect = list_folder_like_side_effect

    def list_files_side_effect(folder_id, correlation_id=None):
        return [{"id": f"{folder_id}_report", "name": Normalizer.REPORT_NAME}]

    drive.list_files.side_effect = list_files_side_effect

    def download_bytes_side_effect(file_id):
        payload = report_map[file_id]
        return json.dumps(payload).encode("utf-8")

    drive.download_file_bytes.side_effect = download_bytes_side_effect

    written_files = []

    def write_json_file(parent_id, filename, data):
        written_files.append((parent_id, filename, data))

    drive.write_json_file.side_effect = write_json_file
    return drive, written_files


@pytest.fixture
def mock_file_resolver():
    resolver = MagicMock()
    bundle = MagicMock()
    bundle.resume_text = "Resume"
    bundle.jd_text = "JD"
    bundle.transcript_text = "\n".join(["Transcript line"] * 120)
    bundle.feedback_text = "Feedback"
    resolver.load.return_value = bundle
    return resolver


@pytest.fixture
def mock_normalizer():
    normalizer = MagicMock()
    normalizer.run.return_value = []
    return normalizer


@pytest.fixture(autouse=True)
def patch_output_and_store():
    with patch("riva_l1.riva_l1_batch.RivaOutputWriter") as mock_writer, patch(
        "riva_l1.riva_l1_batch.DecisionStore"
    ) as mock_store, patch("riva_l1.riva_l1_batch.upsert_role_sheet_row") as mock_upsert:
        mock_writer.generate_riva_report = MagicMock()
        mock_writer.generate_l2_questionnaire = MagicMock()
        yield


def test_routing_and_l1_result_generation(mock_file_resolver, mock_normalizer):
    candidate_ids = ["Cand_L2", "Cand_REJECT", "Cand_HOLD"]
    reports = {
        f"{cid}_report": _make_normalization_report()
        for cid in candidate_ids
    }
    drive, written_files = _build_drive_with_reports(candidate_ids, reports)

    with patch("riva_l1.riva_l1_batch.L1_FOLDERS", {"IT Support": "role_folder"}), patch(
        "riva_l1.riva_l1_batch.get_l2_folder", return_value="l2_parent"
    ), patch(
        "riva_l1.riva_l1_batch.get_reject_folder", return_value="reject_parent"
    ), patch("riva_l1.riva_l1_batch.RivaL1Service") as mock_service:
        service_instance = mock_service.return_value
        service_instance.evaluate.side_effect = [
            _make_riva_result("MOVE_TO_L2"),
            _make_riva_result("REJECT"),
            _make_riva_result("HOLD"),
        ]

        processor = RivaL1BatchProcessor(
            drive=drive,
            normalizer=mock_normalizer,
            file_resolver=mock_file_resolver,
        )
        summary = processor.run()

    assert summary.total_seen == 3
    assert summary.evaluated == 3
    assert summary.moved_to_l2 == 1
    assert summary.rejected_at_l1 == 1
    assert summary.hold_decisions == 1
    assert summary.on_hold_missing_transcript == 0
    assert summary.data_incomplete == 0

    move_calls = [call.args for call in drive.move_folder.call_args_list]
    assert ("Cand_L2", "l2_parent") in move_calls
    assert ("Cand_REJECT", "reject_parent") in move_calls

    l1_result_payloads = [data for _, filename, data in written_files if filename == "l1_result.json"]
    assert len(l1_result_payloads) == 3
    for payload in l1_result_payloads:
        assert {
            "overall_score",
            "strengths",
            "risks",
            "recommendation",
            "rationale",
        }.issubset(payload.keys())
        assert "structured_evaluation" in payload


def test_missing_transcript_puts_candidate_on_hold(mock_file_resolver, mock_normalizer):
    candidate_ids = ["Cand_Missing_Transcript"]
    reports = {
        "Cand_Missing_Transcript_report": _make_normalization_report(include_transcript=False)
    }
    drive, written_files = _build_drive_with_reports(candidate_ids, reports)

    with patch("riva_l1.riva_l1_batch.L1_FOLDERS", {"IT Support": "role_folder"}), patch(
        "riva_l1.riva_l1_batch.RivaL1Service"
    ):
        processor = RivaL1BatchProcessor(
            drive=drive,
            normalizer=mock_normalizer,
            file_resolver=mock_file_resolver,
        )
        summary = processor.run()

    assert summary.total_seen == 1
    assert summary.evaluated == 0
    assert summary.on_hold_missing_transcript == 1
    assert summary.data_incomplete == 0
    mock_file_resolver.load.assert_not_called()

    status_payloads = [data for _, filename, data in written_files if filename == RivaL1BatchProcessor.STATUS_FILENAME]
    assert status_payloads and status_payloads[0]["status"] == RivaL1BatchProcessor.STATUS_ON_HOLD_MISSING_L1_TRANSCRIPT


def test_missing_resume_or_jd_marks_data_incomplete(mock_file_resolver, mock_normalizer):
    candidate_ids = ["Cand_Data_Incomplete"]
    reports = {
        "Cand_Data_Incomplete_report": _make_normalization_report(include_resume=False)
    }
    drive, written_files = _build_drive_with_reports(candidate_ids, reports)

    with patch("riva_l1.riva_l1_batch.L1_FOLDERS", {"IT Support": "role_folder"}), patch(
        "riva_l1.riva_l1_batch.RivaL1Service"
    ):
        processor = RivaL1BatchProcessor(
            drive=drive,
            normalizer=mock_normalizer,
            file_resolver=mock_file_resolver,
        )
        summary = processor.run()

    assert summary.total_seen == 1
    assert summary.evaluated == 0
    assert summary.data_incomplete == 1
    assert summary.on_hold_missing_transcript == 0

    status_payloads = [data for _, filename, data in written_files if filename == RivaL1BatchProcessor.STATUS_FILENAME]
    assert status_payloads and status_payloads[0]["status"] == RivaL1BatchProcessor.STATUS_DATA_INCOMPLETE


def test_processing_error_creates_structured_batch_error(mock_file_resolver, mock_normalizer):
    candidate_ids = ["Cand_Fail"]
    reports = {
        "Cand_Fail_report": _make_normalization_report()
    }
    drive, _ = _build_drive_with_reports(candidate_ids, reports)

    # Force file resolver to raise
    mock_file_resolver.load.side_effect = RuntimeError("Drive offline")

    with patch("riva_l1.riva_l1_batch.L1_FOLDERS", {"IT Support": "role_folder"}), patch(
        "riva_l1.riva_l1_batch.RivaL1Service"
    ) as mock_service:
        service_instance = mock_service.return_value
        service_instance.evaluate.return_value = _make_riva_result("MOVE_TO_L2")

        processor = RivaL1BatchProcessor(
            drive=drive,
            normalizer=mock_normalizer,
            file_resolver=mock_file_resolver,
        )
        summary = processor.run()

    assert len(summary.errors) == 1
    error_entry = summary.errors[0]
    assert error_entry.candidate_name == "Cand Fail"
    assert error_entry.role == "IT Support"
    assert error_entry.error_code == "candidate_processing_failed"
    assert error_entry.technical_detail == "Drive offline"

