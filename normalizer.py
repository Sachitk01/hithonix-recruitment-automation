import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from drive_service import DriveManager
from folder_map import L1_FOLDERS


logger = logging.getLogger(__name__)


PRIMARY_ARTIFACT_KEYS = [
    "resume",
    "jd",
    "l1_transcript",
    "l1_feedback",
    "l1_video",
]

SECONDARY_ARTIFACT_KEYS = [
    "l2_transcript",
    "l2_feedback",
    "l2_video",
]


class Normalizer:
    """Classifies raw candidate folders and writes normalization reports."""

    REPORT_NAME = "normalization_report.json"

    # -------------------------
    # PATTERNS FOR CLASSIFICATION
    # -------------------------

    RESUME_PATTERNS = ["resume", "cv", "curriculum", "biodata", "profile"]
    JD_PATTERNS = ["jd", "job description", "job-description", "role", "responsibilities"]
    TRANSCRIPT_STRONG_PATTERNS = [
        "first round interview invite",
        "interview invite",
        "interview summary",
        "meet transcript",
        "google meet",
        "interview transcript",
        "interview notes",
        "first round interview",
    ]
    TRANSCRIPT_WEAK_PATTERNS = [
        "interview",
        "meet",
        "meeting",
        "discussion",
        "conversation",
        "transcript",
    ]
    FEEDBACK_PATTERNS = [
        "feedback",
        "interviewer",
        "review",
        "observation",
        "evaluation",
    ]

    ALLOWED_TRANSCRIPT_EXTENSIONS = ["pdf", "docx", "txt"]
    ALLOWED_TRANSCRIPT_MIME_PREFIXES = (
        "application/vnd.google-apps.document",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "application/pdf",
    )

    VIDEO_EXTENSIONS = {"mp4", "mov", "wmv", "webm", "m4a"}
    VIDEO_MIME_PREFIXES = ("video/", "audio/")

    # -------------------------
    # INIT
    # -------------------------

    def __init__(self, drive: DriveManager):
        self.drive = drive

    # -------------------------
    # HELPER MATCH FUNCTIONS
    # -------------------------

    @staticmethod
    def _match(filename: str, patterns):
        name = filename.lower().replace("_", " ")
        return any(p in name for p in patterns)

    @staticmethod
    def _get_extension(name: str) -> str:
        if "." not in name:
            return ""
        return name.lower().split(".")[-1]

    # -------------------------
    # CLASSIFICATION LOGIC
    # -------------------------

    @classmethod
    def classify_file_static(
        cls,
        filename: str,
        mime_type: Optional[str] = None,
        content_hint: Optional[str] = None,
    ) -> Optional[str]:
        lower = filename.lower()
        ext = cls._get_extension(filename)
        mime = (mime_type or "").lower()

        if ext in cls.VIDEO_EXTENSIONS or any(mime.startswith(prefix) for prefix in cls.VIDEO_MIME_PREFIXES):
            return "video"

        if cls._match(lower, cls.RESUME_PATTERNS):
            return "resume"

        if cls._match(lower, cls.JD_PATTERNS):
            return "jd"

        if cls._match(lower, cls.FEEDBACK_PATTERNS):
            return "feedback"

        allowed_transcript = ext in cls.ALLOWED_TRANSCRIPT_EXTENSIONS or any(
            mime.startswith(prefix) for prefix in cls.ALLOWED_TRANSCRIPT_MIME_PREFIXES
        )

        if allowed_transcript and cls._match(lower, cls.TRANSCRIPT_STRONG_PATTERNS):
            return "transcript"

        if allowed_transcript and cls._match(lower, cls.TRANSCRIPT_WEAK_PATTERNS):
            return "transcript"

        if content_hint:
            hint = content_hint.lower()
            if "resume" in hint:
                return "resume"
            if "job description" in hint or "jd" in hint:
                return "jd"

        return None

    def classify_file(
        self,
        filename: str,
        mime_type: Optional[str] = None,
        content_hint: Optional[str] = None,
    ) -> Optional[str]:
        return self.classify_file_static(filename, mime_type, content_hint)

    # -------------------------
    # NORMALIZATION HELPERS
    # -------------------------

    @staticmethod
    def _canonical_jd_name(role_name: str) -> str:
        safe_role = role_name.replace(" ", "_")
        return f"JD_{safe_role}.pdf"

    @staticmethod
    def _entry(file_obj: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": file_obj["id"],
            "name": file_obj["name"],
            "mimeType": file_obj.get("mimeType"),
        }

    @classmethod
    def _is_l2_transcript(cls, filename: str, mime_type: Optional[str] = None) -> bool:
        """
        Check if a file is an L2 transcript based on flexible naming patterns.
        Accepts any file whose name contains:
          - "l2 interview transcript"
          - "l2 transcript"
          - "l2_transcript"
        (case-insensitive)
        Accept any extension: .docx, Google Doc, .txt, .pdf
        Reject audio/video files.
        """
        name_lower = filename.lower().replace("_", " ")
        mime = (mime_type or "").lower()
        ext = cls._get_extension(filename)

        # Reject video/audio files
        if ext in cls.VIDEO_EXTENSIONS or any(mime.startswith(prefix) for prefix in cls.VIDEO_MIME_PREFIXES):
            return False

        # Check for L2 transcript patterns
        l2_patterns = [
            "l2 interview transcript",
            "l2 transcript",
        ]
        
        return any(pattern in name_lower for pattern in l2_patterns)

    def _slot_for_entry(self, entry: Dict[str, Any], role_name: str) -> Optional[str]:
        name = entry["name"].lower()
        safe_role = role_name.replace(" ", "_").lower()

        exact_map = {
            "resume.pdf": "resume",
            f"jd_{safe_role}.pdf": "jd",
            "l1_transcript.txt": "l1_transcript",
            "l2_transcript.txt": "l2_transcript",
            "l1_feedback.docx": "l1_feedback",
            "l2_feedback.docx": "l2_feedback",
            "l1_video.mp4": "l1_video",
            "l2_video.mp4": "l2_video",
        }
        if name in exact_map:
            return exact_map[name]

        # Check for L2 transcript using the flexible pattern
        if self._is_l2_transcript(entry["name"], entry.get("mimeType")):
            return "l2_transcript"

        classification = self.classify_file(entry["name"], entry.get("mimeType"))
        if classification == "resume":
            return "resume"
        if classification == "jd":
            return "jd"
        if classification == "transcript":
            return "l2_transcript" if "l2" in name else "l1_transcript"
        if classification == "feedback":
            return "l2_feedback" if "l2" in name else "l1_feedback"
        if classification == "video":
            return "l2_video" if "l2" in name else "l1_video"
        return None

    def _classify_files(self, files: List[Dict[str, Any]], role_name: str) -> Dict[str, Any]:
        buckets: Dict[str, Any] = {
            "resume": None,
            "jd": None,
            "l1_transcript": None,
            "l1_feedback": None,
            "l1_video": None,
            "l2_transcript": None,
            "l2_feedback": None,
            "l2_video": None,
            "extras": [],
        }

        for file_obj in files:
            entry = self._entry(file_obj)
            slot = self._slot_for_entry(entry, role_name)
            if slot:
                if buckets.get(slot) is None:
                    buckets[slot] = entry
                else:
                    buckets["extras"].append(entry)
            else:
                buckets["extras"].append(entry)

        return buckets

    def _build_report(
        self,
        folder_id: str,
        folder_name: str,
        role_name: str,
        buckets: Dict[str, Any],
    ) -> Dict[str, Any]:
        canonical_jd_name = self._canonical_jd_name(role_name)
        report: Dict[str, Any] = {
            "candidate_folder_id": folder_id,
            "candidate_name": folder_name,
            "role_name": role_name,
            "normalized_at": datetime.now(timezone.utc).isoformat(),
            "jd_canonical_name": canonical_jd_name,
            "artifact_version": "candidate_artifacts_v2",
        }

        for key in PRIMARY_ARTIFACT_KEYS + SECONDARY_ARTIFACT_KEYS:
            report[key] = buckets.get(key)

        extras_list = list(buckets.get("extras", []))
        report["extras"] = extras_list
        report["artifacts_summary"] = {
            key: bool(report[key]) for key in PRIMARY_ARTIFACT_KEYS
        }

        if report["jd"]:
            report["jd"]["canonical_name"] = canonical_jd_name

        return report

    def _persist_report(self, folder_id: str, report: Dict[str, Any], correlation_id: Optional[str]):
        corr = correlation_id or "no-correlation-id"
        try:
            self.drive.write_json_file(folder_id, self.REPORT_NAME, report)
            logger.info(
                "normalization_report_written",
                extra={"correlation_id": corr, "folder_id": folder_id},
            )
        except Exception as exc:
            logger.warning(
                "normalization_report_failed",
                extra={
                    "correlation_id": corr,
                    "folder_id": folder_id,
                    "error": str(exc),
                },
                exc_info=True,
            )

    # -------------------------
    # NORMALIZATION OF A SINGLE CANDIDATE FOLDER
    # -------------------------

    def normalize_candidate_folder(
        self,
        folder_id: str,
        folder_name: str,
        role_name: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_role = role_name or "Unassigned Role"
        corr = correlation_id or "no-correlation-id"
        logger.info(
            "normalizing_candidate",
            extra={
                "correlation_id": corr,
                "candidate_folder_id": folder_id,
                "candidate_name": folder_name,
                "role_name": resolved_role,
            },
        )

        files = self.drive.list_files(folder_id, correlation_id=correlation_id)
        buckets = self._classify_files(files, resolved_role)
        report = self._build_report(folder_id, folder_name, resolved_role, buckets)

        jd_entry = report.get("jd")
        if jd_entry:
            canonical_name = report["jd_canonical_name"]
            if jd_entry.get("name") != canonical_name:
                try:
                    self.drive.rename_file(jd_entry["id"], canonical_name)
                    jd_entry["name"] = canonical_name
                    logger.info(
                        "jd_renamed",
                        extra={
                            "correlation_id": corr,
                            "candidate_folder_id": folder_id,
                            "jd_file_id": jd_entry["id"],
                            "canonical_name": canonical_name,
                        },
                    )
                except Exception as exc:
                    logger.warning(
                        "jd_rename_failed",
                        extra={
                            "correlation_id": corr,
                            "candidate_folder_id": folder_id,
                            "jd_file_id": jd_entry["id"],
                            "error": str(exc),
                        },
                        exc_info=True,
                    )

        self._persist_report(folder_id, report, correlation_id)
        return report

    # -------------------------
    # RUN NORMALIZER FOR ALL L1 ROLE FOLDERS
    # -------------------------

    def run(self, correlation_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Batch runner across all L1 Pending Review role folders."""
        reports: List[Dict[str, Any]] = []

        for role_name, folder_id in L1_FOLDERS.items():
            role_corr = f"{correlation_id}::normalize::{role_name}" if correlation_id else None
            candidate_folders = self.drive.list_folder_like(
                folder_id, correlation_id=role_corr
            )

            for candidate in candidate_folders:
                candidate_id = self.drive.get_real_folder_id(candidate)
                candidate_corr = f"{role_corr}::{candidate['name']}" if role_corr else None
                reports.append(
                    self.normalize_candidate_folder(
                        candidate_id,
                        candidate["name"],
                        role_name,
                        correlation_id=candidate_corr,
                    )
                )

        return reports
