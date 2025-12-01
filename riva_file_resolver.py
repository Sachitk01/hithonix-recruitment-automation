# riva_file_resolver.py

import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from drive_service import DriveManager
from normalizer import Normalizer
from pdf_reader import extract_pdf_text
from docx_reader import extract_docx_text


logger = logging.getLogger(__name__)


@dataclass
class RivaFileBundle:
    resume_text: str
    jd_text: str
    transcript_text: str
    feedback_text: str
    meta: dict


class RivaFileResolver:
    """
    Resolves a candidate folder into text blobs using normalization_report.json as
    the source-of-truth, falling back to raw classification when needed.
    """

    REPORT_NAME = Normalizer.REPORT_NAME

    def __init__(self, drive: DriveManager):
        self.drive = drive

    def load(
        self,
        folder_id: str,
        role_name: str,
        candidate_name: str,
        correlation_id: Optional[str] = None,
    ) -> RivaFileBundle:
        corr = correlation_id or "no-correlation-id"
        files = self.drive.list_files(folder_id, correlation_id=correlation_id)
        report = self._load_report(files, corr)
        used_ids: set[str] = set()

        resume_file = self._resolve_document(
            slot_key="resume",
            classification_targets=["resume"],
            files=files,
            report=report,
            used_ids=used_ids,
        )
        jd_file = self._resolve_jd(role_name, files, report, used_ids)
        transcript_file = self._resolve_document(
            slot_key="l1_transcript",
            classification_targets=["transcript"],
            files=files,
            report=report,
            used_ids=used_ids,
            name_filter=lambda n: "l2" not in n.lower(),
        )
        feedback_file = self._resolve_document(
            slot_key="l1_feedback",
            classification_targets=["feedback"],
            files=files,
            report=report,
            used_ids=used_ids,
            name_filter=lambda n: "l2" not in n.lower(),
        )

        resume_text = self._extract_text(resume_file, corr)
        jd_text = self._extract_text(jd_file, corr)
        transcript_text = self._extract_text(transcript_file, corr)
        feedback_text = self._extract_text(feedback_file, corr)

        meta = report or {}
        meta.setdefault("role_name", role_name)
        meta.setdefault("candidate_name", candidate_name)

        return RivaFileBundle(
            resume_text=resume_text,
            jd_text=jd_text,
            transcript_text=transcript_text,
            feedback_text=feedback_text,
            meta=meta,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_jd_name(role_name: str) -> str:
        safe_role = role_name.replace(" ", "_")
        return f"JD_{safe_role}.pdf"

    def _load_report(self, files: List[Dict[str, Any]], correlation_id: str) -> Dict[str, Any]:
        for file_obj in files:
            if file_obj.get("name") == self.REPORT_NAME:
                try:
                    payload = self.drive.download_file_bytes(file_obj["id"])
                    report = json.loads(payload.decode("utf-8"))
                    logger.info(
                        "normalization_report_loaded",
                        extra={
                            "correlation_id": correlation_id,
                            "report_file_id": file_obj["id"],
                        },
                    )
                    return report
                except Exception as exc:
                    logger.warning(
                        "normalization_report_load_failed",
                        extra={
                            "correlation_id": correlation_id,
                            "report_file_id": file_obj["id"],
                            "error": str(exc),
                        },
                        exc_info=True,
                    )
                    break
        return {}

    @staticmethod
    def _find_by_name(files: List[Dict[str, Any]], filename: str) -> Optional[Dict[str, Any]]:
        for file_obj in files:
            if file_obj.get("name") == filename:
                return file_obj
        return None

    def _resolve_from_report(
        self,
        key: str,
        files: List[Dict[str, Any]],
        report: Dict[str, Any],
        used_ids: set[str],
    ) -> Optional[Dict[str, Any]]:
        if not report:
            return None
        entry = report.get(key)
        if not entry:
            return None

        file_id = entry.get("id")
        name = entry.get("name")
        for file_obj in files:
            if file_id and file_obj["id"] == file_id and file_obj["id"] not in used_ids:
                used_ids.add(file_obj["id"])
                return file_obj
        if name:
            candidate = self._find_by_name(files, name)
            if candidate and candidate["id"] not in used_ids:
                used_ids.add(candidate["id"])
                return candidate
        return None

    def _classify_fallback(
        self,
        classification_targets: List[str],
        files: List[Dict[str, Any]],
        used_ids: set[str],
    name_filter: Optional[Callable[[str], bool]] = None,
    ) -> Optional[Dict[str, Any]]:
        for file_obj in files:
            if file_obj["id"] in used_ids:
                continue
            classification = Normalizer.classify_file_static(
                file_obj["name"], file_obj.get("mimeType")
            )
            if classification in classification_targets:
                if name_filter and not name_filter(file_obj["name"]):
                    continue
                used_ids.add(file_obj["id"])
                return file_obj
        return None

    def _resolve_document(
        self,
        slot_key: str,
        classification_targets: List[str],
        files: List[Dict[str, Any]],
        report: Dict[str, Any],
        used_ids: set[str],
    name_filter: Optional[Callable[[str], bool]] = None,
    ) -> Dict[str, Any]:
        candidate = self._resolve_from_report(slot_key, files, report, used_ids)
        if not candidate:
            candidate = self._classify_fallback(
                classification_targets, files, used_ids, name_filter
            )
        if not candidate:
            raise FileNotFoundError(f"Missing {slot_key} document for candidate folder")
        return candidate

    def _resolve_jd(
        self,
        role_name: str,
        files: List[Dict[str, Any]],
        report: Dict[str, Any],
        used_ids: set[str],
    ) -> Dict[str, Any]:
        canonical_name = self._canonical_jd_name(role_name)
        candidate = self._find_by_name(files, canonical_name)
        if candidate and candidate["id"] not in used_ids:
            used_ids.add(candidate["id"])
            return candidate

        candidate = self._resolve_from_report("jd", files, report, used_ids)
        if candidate:
            return candidate

        candidate = self._classify_fallback(["jd"], files, used_ids)
        if candidate:
            return candidate

        raise FileNotFoundError(
            f"Missing JD document (expected {canonical_name}) for candidate folder"
        )

    def _extract_text(self, file_obj: Dict[str, Any], correlation_id: str) -> str:
        file_id = file_obj["id"]
        name = file_obj.get("name", "").lower()
        mime = (file_obj.get("mimeType") or "").lower()

        if mime == "application/vnd.google-apps.document":
            return self.drive.export_google_doc_to_text(file_id)

        data = self.drive.download_file_bytes(file_id)

        if name.endswith(".pdf") or mime == "application/pdf":
            return extract_pdf_text(data)

        if name.endswith(".docx") or "wordprocessingml.document" in mime:
            return extract_docx_text(data)

        if name.endswith(".txt") or mime.startswith("text/"):
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                return data.decode("utf-8", errors="ignore")

        logger.warning(
            "unknown_document_type",
            extra={
                "correlation_id": correlation_id,
                "file_id": file_id,
                "mime": mime,
                "name": file_obj.get("name"),
            },
        )
        return extract_pdf_text(data)
