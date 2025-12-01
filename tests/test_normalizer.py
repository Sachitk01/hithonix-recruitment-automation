"""Tests for the Normalizer CandidateArtifacts workflow."""

from __future__ import annotations

from typing import Dict, List
from unittest.mock import MagicMock

import pytest

import normalizer as normalizer_module
from drive_service import DriveManager
from normalizer import Normalizer, PRIMARY_ARTIFACT_KEYS


def _make_file(file_id: str, name: str, mime: str = "application/pdf") -> Dict:
    return {"id": file_id, "name": name, "mimeType": mime}


@pytest.fixture
def mock_drive_manager() -> DriveManager:
    drive = MagicMock(spec=DriveManager)
    drive.list_folder_like.return_value = []
    drive.list_files.return_value = []
    return drive


class TestClassifier:
    @pytest.mark.parametrize(
        "filename, expected",
        [
            ("John_Doe_Resume.pdf", "resume"),
            ("jane-smith-cv.docx", "resume"),
            ("IT_Support_JD.pdf", "jd"),
            ("role_responsibilities.docx", "jd"),
            ("L1_Interview_Transcript.pdf", "transcript"),
            ("discussion_notes.txt", "transcript"),
            ("Interviewer_Feedback.docx", "feedback"),
            ("candidate_evaluation.pdf", "feedback"),
        ],
    )
    def test_known_patterns(self, filename: str, expected: str):
        assert Normalizer.classify_file_static(filename, None, None) == expected

    def test_video_files_are_detected(self):
        assert Normalizer.classify_file_static("interview_recording.mp4", "video/mp4", None) == "video"
        assert Normalizer.classify_file_static("presentation.mov", None, None) == "video"

    def test_unknown_files_return_none(self):
        assert Normalizer.classify_file_static("notes.txt", None, None) is None
        assert Normalizer.classify_file_static("backup.xlsx", None, None) is None


class TestNormalization:
    def test_candidate_artifacts_written_to_drive(self, mock_drive_manager):
        files = [
            _make_file("resume", "John_Doe_Resume.pdf"),
            _make_file("jd", "IT_Support_JD.pdf"),
            _make_file("transcript", "L1_Interview_Transcript.pdf"),
            _make_file(
                "feedback",
                "Interviewer_Feedback.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            _make_file("video", "interview_recording.mp4", "video/mp4"),
            _make_file("extra1", "cover_letter.pdf"),
        ]
        mock_drive_manager.list_files.return_value = files

        normalizer = Normalizer(mock_drive_manager)
        report = normalizer.normalize_candidate_folder(
            "folder_123",
            "John Doe",
            role_name="IT Support",
        )

        assert report["candidate_name"] == "John Doe"
        assert report["role_name"] == "IT Support"
        assert report["resume"]["id"] == "resume"
        assert report["jd"]["canonical_name"] == "JD_IT_Support.pdf"
        assert report["l1_transcript"]["name"] == "L1_Interview_Transcript.pdf"
        assert report["l1_feedback"]["id"] == "feedback"
        assert report["l1_video"]["id"] == "video"
        assert report["artifact_version"] == "candidate_artifacts_v2"

        extras_names = {entry["name"] for entry in report["extras"]}
        assert extras_names == {"cover_letter.pdf"}

        for key in PRIMARY_ARTIFACT_KEYS:
            assert isinstance(report["artifacts_summary"][key], bool)
        assert report["artifacts_summary"]["resume"] is True

        mock_drive_manager.write_json_file.assert_called_once()
        folder_id, filename, payload = mock_drive_manager.write_json_file.call_args[0]
        assert folder_id == "folder_123"
        assert filename == Normalizer.REPORT_NAME
        assert payload["candidate_name"] == "John Doe"

    def test_missing_artifacts_toggle_summary_flags(self, mock_drive_manager):
        files = [
            _make_file("resume", "Resume.pdf"),
            _make_file("video", "mock_video.mp4", "video/mp4"),
        ]
        mock_drive_manager.list_files.return_value = files

        normalizer = Normalizer(mock_drive_manager)
        report = normalizer.normalize_candidate_folder("folder_123", "Jane Doe", role_name="HR Support")

        assert report["resume"]["name"] == "Resume.pdf"
        assert report["jd"] is None
        assert report["l1_transcript"] is None
        assert report["artifacts_summary"]["jd"] is False
        assert report["artifacts_summary"]["l1_transcript"] is False
        assert report["l1_video"]["id"] == "video"
        assert report["extras"] == []

    def test_duplicate_artifacts_become_extras(self, mock_drive_manager):
        files = [
            _make_file("resume_a", "Resume_v1.pdf"),
            _make_file("resume_b", "Resume_v2.pdf"),
            _make_file("jd", "JD_IT_Support.pdf"),
            _make_file("transcript", "Transcript.pdf"),
        ]
        mock_drive_manager.list_files.return_value = files

        normalizer = Normalizer(mock_drive_manager)
        report = normalizer.normalize_candidate_folder("folder_123", "Alice", role_name="IT Support")

        assert report["resume"]["id"] == "resume_a"
        extras_ids = {entry["id"] for entry in report["extras"]}
        assert "resume_b" in extras_ids
        assert len(report["extras"]) == 1

    def test_run_processes_each_role_folder(self, mock_drive_manager, monkeypatch):
        monkeypatch.setattr(
            normalizer_module,
            "L1_FOLDERS",
            {"IT Support": "role_it", "HR Support": "role_hr"},
        )

        def list_folder_like_side_effect(folder_id: str, correlation_id: str | None = None) -> List[Dict]:
            return [{"id": f"{folder_id}_cand", "name": "Candidate"}]

        def list_files_side_effect(folder_id: str, correlation_id: str | None = None) -> List[Dict]:
            if folder_id.endswith("_cand"):
                return [
                    _make_file("resume", "Resume.pdf"),
                    _make_file("jd", "JD_IT_Support.pdf"),
                    _make_file("transcript", "Transcript.pdf"),
                ]
            return []

        mock_drive_manager.list_folder_like.side_effect = list_folder_like_side_effect
        mock_drive_manager.list_files.side_effect = list_files_side_effect

        normalizer = Normalizer(mock_drive_manager)
        reports = normalizer.run()

        assert len(reports) == 2
        assert mock_drive_manager.write_json_file.call_count == 2

    def test_run_handles_empty_roles_gracefully(self, mock_drive_manager, monkeypatch):
        monkeypatch.setattr(normalizer_module, "L1_FOLDERS", {"IT Support": "role_it"})
        mock_drive_manager.list_folder_like.return_value = []

        normalizer = Normalizer(mock_drive_manager)
        reports = normalizer.run()

        assert reports == []
        mock_drive_manager.write_json_file.assert_not_called()

