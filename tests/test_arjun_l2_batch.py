import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from arjun_l2.arjun_l2_batch import ArjunL2BatchProcessor
from arjun_l2.arjun_l2_models import ArjunL2Result
from drive_service import DriveManager
from normalizer import Normalizer


def _report_entry(file_id: str, name: str) -> dict:
    return {"id": file_id, "name": name, "mimeType": "text/plain"}


def _build_report(include_resume=True, include_jd=True, include_transcript=True):
    report = {
        "resume": _report_entry("resume_file", "Resume.txt") if include_resume else None,
        "jd": _report_entry("jd_file", "JD_IT_Support.pdf") if include_jd else None,
        "l2_transcript": _report_entry("l2_file", "L2_Transcript.txt")
        if include_transcript
        else None,
    }
    report["jd_canonical_name"] = "JD_IT_Support.pdf"
    return report


def _drive_with_candidate(report: dict, extra_files=None):
    drive = MagicMock(spec=DriveManager)
    drive.get_real_folder_id.side_effect = lambda item: item["id"]
    drive.list_folder_like.return_value = [
        {
            "id": "cand1",
            "name": "Candidate One",
            "mimeType": "application/vnd.google-apps.folder",
        }
    ]

    files = [
        {"id": "cand1_report", "name": Normalizer.REPORT_NAME},
        {"id": "cand1_l1_result", "name": "l1_result.json"},
    ]
    
    # Add L2 transcript file if present in report
    if report.get("l2_transcript"):
        files.append({"id": "l2_file", "name": "L2_Transcript.txt"})
    
    files.extend(extra_files or [])

    drive.list_files.side_effect = lambda *_args, **_kwargs: files

    payloads = {
        "cand1_report": json.dumps(report).encode("utf-8"),
        "cand1_l1_result": json.dumps({"overall_score": 70}).encode("utf-8"),
        "resume_file": b"Resume text",
        "jd_file": b"JD text",
        "l2_file": b"Transcript text",
    }

    drive.download_file_bytes.side_effect = lambda file_id: payloads[file_id]

    written = []

    def _write(parent_id, filename, data):
        written.append((parent_id, filename, data))

    drive.write_json_file.side_effect = _write
    drive.move_folder = MagicMock()
    return drive, written


@pytest.fixture
def mock_arjun_result():
    return ArjunL2Result(
        leadership_assessment="Leader",
        technical_capability="Advanced",
        communication_depth="Deep",
        culture_alignment="High",
        career_potential="Strong",
        strengths=["Strength"],
        concerns=["Concern"],
        risk_flags=["Risk"],
        final_score=90,
        final_recommendation="HIRE",
        l2_summary="Great fit",
        rationale="Aligned with needs",
    )


def _run_processor(drive, mock_result, l2_folders=None, shortlist_id="final_folder", reject_id="reject_folder"):
    arjun_service = MagicMock()
    arjun_service.evaluate.return_value = mock_result
    processor = ArjunL2BatchProcessor(
        drive=drive,
        sheet=MagicMock(),
        arjun=arjun_service,
    )
    with patch("arjun_l2.arjun_l2_batch.L2_FOLDERS", l2_folders or {"IT Support": "role_folder"}), patch(
        "arjun_l2.arjun_l2_batch.get_shortlist_folder", return_value=shortlist_id
    ), patch("arjun_l2.arjun_l2_batch.get_l2_reject_folder", return_value=reject_id):
        summary = processor.run()
    return processor, summary


def test_l2_routing_and_result_generation(mock_arjun_result):
    report = _build_report()
    drive, written = _drive_with_candidate(report)
    processor, summary = _run_processor(drive, mock_arjun_result)

    assert summary.total_seen == 1
    assert summary.evaluated == 1
    assert summary.hires == 1
    assert summary.rejects == 0
    assert summary.needs_manual_review == 0
    assert summary.on_hold_missing_l2_transcript == 0
    assert summary.data_incomplete == 0
    assert summary.candidates[0].risk_flags == ["Risk"]

    drive.move_folder.assert_called_once_with("cand1", "final_folder")
    result_payloads = [data for _, filename, data in written if filename == "l2_result.json"]
    assert result_payloads
    payload = result_payloads[0]
    assert payload["final_recommendation"] == "HIRE"
    assert payload["l1_l2_comparison"] == "IMPROVED"
    assert payload["l2_summary"] == "Great fit"


def test_missing_l2_transcript_sets_hold(mock_arjun_result):
    report = _build_report(include_transcript=False)
    drive, written = _drive_with_candidate(report)
    processor, summary = _run_processor(drive, mock_arjun_result)

    assert summary.total_seen == 1
    assert summary.evaluated == 0
    assert summary.on_hold_missing_l2_transcript == 1
    assert not drive.move_folder.called
    assert summary.candidates[0].risk_flags == ["missing_l2_transcript"]
    status_entries = [data for _, filename, data in written if filename == processor.STATUS_FILENAME]
    assert status_entries[0]["status"] == processor.STATUS_ON_HOLD_MISSING_L2_TRANSCRIPT


def test_missing_resume_marks_data_incomplete(mock_arjun_result):
    report = _build_report(include_resume=False)
    drive, written = _drive_with_candidate(report)
    processor, summary = _run_processor(drive, mock_arjun_result)

    assert summary.total_seen == 1
    assert summary.data_incomplete == 1
    assert summary.candidates[0].risk_flags == ["data_incomplete"]
    status_entries = [data for _, filename, data in written if filename == processor.STATUS_FILENAME]
    assert status_entries[0]["status"] == processor.STATUS_DATA_INCOMPLETE


def test_reject_routes_to_profiles_l2_rejected():
    mock_result = ArjunL2Result(
        leadership_assessment="",
        technical_capability="",
        communication_depth="",
        culture_alignment="",
        career_potential="",
        strengths=[],
        concerns=[],
        risk_flags=["Risk"],
        final_score=60,
        final_recommendation="REJECT",
        l2_summary="",
        rationale="",
    )
    report = _build_report()
    drive, written = _drive_with_candidate(report)
    processor, summary = _run_processor(
        drive,
        mock_result,
        shortlist_id="final_folder",
        reject_id="l2_reject_folder",
    )

    assert summary.rejects == 1
    drive.move_folder.assert_called_once_with("cand1", "l2_reject_folder")
    payload = [data for _, filename, data in written if filename == "l2_result.json"][0]
    assert payload["final_recommendation"] == "REJECT"
    assert payload["l1_l2_comparison"] == "REGRESSED"


def test_hold_leaves_candidate_in_place(mock_arjun_result):
    hold_result = mock_arjun_result.model_copy(update={"final_recommendation": "HOLD"})
    report = _build_report()
    drive, written = _drive_with_candidate(report)
    processor, summary = _run_processor(drive, hold_result)

    assert summary.needs_manual_review == 1
    drive.move_folder.assert_not_called()
    status_entries = [data for _, filename, data in written if filename == processor.STATUS_FILENAME]
    assert status_entries[0]["status"] == processor.STATUS_EVALUATION_HOLD