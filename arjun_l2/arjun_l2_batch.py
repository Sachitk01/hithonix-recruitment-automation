import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from docx_reader import extract_docx_text
from pdf_reader import extract_pdf_text

from drive_service import DriveManager
from sheet_service import SheetManager, map_role_to_sheet_title, upsert_role_sheet_row
from folder_resolver import get_shortlist_folder, get_l2_reject_folder
from arjun_l2.arjun_l2_service import ArjunL2Service
from arjun_l2.arjun_l2_models import L2BatchSummary, L2CandidateResult
from arjun_l2.l2_file_resolver import find_l2_transcript_file
from arjun_l2.decision_engine import decide_l2_outcome
from folder_map import L2_FOLDERS
from normalizer import Normalizer
from evaluation_models import (
    CandidateEvent as CandidateEventModel,
    CandidateProfile as CandidateProfileModel,
    L2Evaluation,
    RoleProfile as RoleProfileModel,
)
from evaluation_converters import (
    candidate_event_decision_from_l2,
    convert_arjun_result,
    l2_alignment_from_scores,
)
from memory_config import (
    is_memory_enabled,
    should_use_candidate_memory,
    should_use_role_memory,
)
from memory_service import get_memory_service, MemoryService
from debug_storage import get_debug_storage
from final_decision_store import get_final_decision_store

RECRUITER_SHEET_FILE_ID = os.getenv("RECRUITER_SHEET_FILE_ID")


logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class ArjunL2BatchProcessor:
    RESULT_FILENAME = "l2_result.json"
    STATUS_FILENAME = "l2_status.json"
    L1_RESULT_FILENAME = "l1_result.json"
    STATUS_ON_HOLD_MISSING_L2_TRANSCRIPT = "ON_HOLD_MISSING_L2_TRANSCRIPT"
    STATUS_DATA_INCOMPLETE = "DATA_INCOMPLETE_L2"
    STATUS_EVALUATION_HOLD = "HOLD"
    DECISION_SHORTLIST = "shortlist"
    DECISION_REJECT = "reject"
    DECISION_HOLD = "hold"
    HOLD_TYPE_MISSING_L2_TRANSCRIPT = "MISSING_L2_TRANSCRIPT"
    HOLD_TYPE_DATA_INCOMPLETE = "DATA_INCOMPLETE_L2"
    HOLD_TYPE_SKIPPED_NO_L2 = "SKIPPED_NO_L2"
    HOLD_REASON_CODE_MANUAL_REVIEW = "manual_review_required"
    HOLD_REASON_CODE_BACKUP = "backup_for_l2_capacity"
    HOLD_REASON_CODE_MISSING_INFO = "missing_noncritical_info"

    def __init__(
        self,
        correlation_id: Optional[str] = None,
        drive: Optional[DriveManager] = None,
        sheet: Optional[SheetManager] = None,
        arjun: Optional[ArjunL2Service] = None,
        memory_service: Optional[MemoryService] = None,
    ):
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.drive = drive or DriveManager(correlation_id=self.correlation_id)
        self.sheet = sheet or SheetManager()
        self.arjun = arjun or ArjunL2Service()
        self.summary = L2BatchSummary()
        self.recruiter_sheet_id = RECRUITER_SHEET_FILE_ID
        self.memory_enabled = is_memory_enabled()
        self.use_candidate_memory = should_use_candidate_memory()
        self.use_role_memory = should_use_role_memory()
        self.memory = None
        self._final_decision_store = get_final_decision_store()

        if self.memory_enabled:
            try:
                self.memory = memory_service or get_memory_service()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "memory_service_unavailable",
                    extra={
                        "correlation_id": self.correlation_id,
                        "error": str(exc),
                    },
                )
                self.memory_enabled = False
                self.use_candidate_memory = False
                self.use_role_memory = False
        else:
            self.use_candidate_memory = False
            self.use_role_memory = False

        if not self.recruiter_sheet_id:
            logger.info(
                "recruiter_sheet_id_missing_l2",
                extra={"correlation_id": self.correlation_id},
            )
        else:
            logger.info(
                "recruiter_sheet_id_loaded_l2",
                extra={
                    "correlation_id": self.correlation_id,
                    "sheet_id": self.recruiter_sheet_id,
                },
            )

    # ------------------------------------------------------------------
    #  Batch runner
    # ------------------------------------------------------------------
    def run(self) -> L2BatchSummary:
        logger.info(
            "Starting Arjun L2 batch",
            extra={"correlation_id": self.correlation_id},
        )

        for role, role_folder_id in L2_FOLDERS.items():
            role_corr = f"{self.correlation_id}::L2::{role}"
            candidate_folders = self.drive.list_folder_like(
                role_folder_id, correlation_id=role_corr
            )

            for candidate in candidate_folders:
                folder_id = self.drive.get_real_folder_id(candidate)
                folder_name = candidate["name"]
                candidate_corr = f"{role_corr}::{folder_name}"
                self.summary.total_seen += 1

                try:
                    files = self.drive.list_files(folder_id, correlation_id=candidate_corr)
                    report = self._load_normalization_report(files, candidate_corr)

                    if not report:
                        self._mark_data_incomplete(
                            folder_id,
                            folder_name,
                            role,
                            candidate_corr,
                            reason="normalization_report_missing",
                        )
                        continue

                    # Skip if there are no actual L2 input files (resume, JD, transcript)
                    if not self._has_l2_material_in_report(report):
                        logger.info(
                            "Skipping L2 evaluation for candidate %s: no L2 artifacts found",
                            folder_name,
                            extra={
                                "correlation_id": candidate_corr,
                                "candidate_name": folder_name,
                                "role": role,
                            },
                        )
                        self._record_candidate_result(
                            candidate_name=folder_name,
                            role=role,
                            decision=self.DECISION_HOLD,
                            reason="No L2 artifacts found",
                            hold_type=self.HOLD_TYPE_SKIPPED_NO_L2,
                            hold_reason=self.HOLD_REASON_CODE_MISSING_INFO,
                            candidate_folder_id=folder_id,
                        )
                        continue

                    gating_status = self._apply_gating(
                        report,
                        files,
                        folder_id,
                        folder_name,
                        role,
                        candidate_corr,
                    )
                    if gating_status:
                        continue

                    resume_text = self._extract_text_from_entry(
                        report["resume"], candidate_corr
                    )
                    jd_text = self._extract_text_from_entry(report["jd"], candidate_corr)
                    
                    # Use the detected L2 transcript file
                    l2_transcript_file = find_l2_transcript_file(files)
                    transcript_text = self._extract_text_from_entry(
                        l2_transcript_file, candidate_corr
                    )

                    memory_context, last_l1_event, role_profile = self._prepare_memory_context(
                        folder_id,
                        role,
                        folder_name,
                        candidate_corr,
                    )

                    result = self.arjun.evaluate(
                        resume_text=resume_text,
                        jd_text=jd_text,
                        transcript_text=transcript_text,
                        memory_context=memory_context,
                    )

                    recommendation = self._normalize_recommendation(
                        result.final_recommendation
                    )

                    l1_score = self._load_l1_score(files, candidate_corr)
                    comparison = self._compute_l1_l2_comparison(
                        l1_score, result.final_score
                    )

                    evaluation = convert_arjun_result(
                        candidate_id=folder_id,
                        role=role,
                        pipeline_decision=recommendation,
                        result=result,
                        alignment_with_l1="unknown",
                    )

                    baseline_l1_score = None
                    if last_l1_event and last_l1_event.scores:
                        baseline_l1_score = last_l1_event.scores.get("overall_fit")
                    elif l1_score is not None:
                        baseline_l1_score = max(0.0, min(5.0, l1_score / 20))

                    alignment = l2_alignment_from_scores(
                        baseline_l1_score,
                        evaluation.scores.get("final"),
                    )
                    if alignment != evaluation.alignment_with_l1:
                        evaluation = evaluation.model_copy(update={"alignment_with_l1": alignment})

                    self._persist_l2_result(
                        folder_id,
                        evaluation,
                        result,
                        recommendation,
                        comparison,
                        candidate_corr,
                    )

                    self._log_to_sheet(role, folder_name, result, evaluation, recommendation)

                    # Use new strict decision engine
                    l2_outcome = decide_l2_outcome(result.model_dump())
                    
                    decision_reason = result.l2_summary or result.rationale
                    hold_reason_code = None
                    hold_type = None
                    
                    if l2_outcome == "ADVANCE_TO_FINAL":
                        human_decision = self.DECISION_SHORTLIST
                        recommendation = "HIRE" # Map back for compatibility if needed
                    elif l2_outcome == "REJECT_AT_L2":
                        human_decision = self.DECISION_REJECT
                        recommendation = "REJECT"
                    elif l2_outcome == "HOLD_EXEC_REVIEW":
                        human_decision = self.DECISION_HOLD
                        hold_reason_code = self.HOLD_REASON_CODE_MANUAL_REVIEW
                        hold_type = "HOLD_EXEC_REVIEW"
                        recommendation = "HOLD"
                    elif l2_outcome == "HOLD_DATA_INCOMPLETE":
                        human_decision = self.DECISION_HOLD
                        hold_reason_code = self.HOLD_REASON_CODE_MISSING_INFO
                        hold_type = self.HOLD_TYPE_DATA_INCOMPLETE
                        recommendation = "HOLD"
                    else:
                        # Fallback
                        human_decision = self.DECISION_REJECT
                        recommendation = "REJECT"
                    final_next_action = self._final_next_action_for_decision(human_decision)

                    self._record_candidate_result(
                        candidate_name=folder_name,
                        role=role,
                        decision=human_decision,
                        reason=decision_reason,
                        hold_type=hold_type,
                        hold_reason=hold_reason_code,
                        candidate_folder_id=folder_id,
                        feedback_link=evaluation.feedback_link or evaluation.report_link,
                    )
                    self._record_final_decision_if_applicable(
                        candidate_name=folder_name,
                        role=role,
                        decision=human_decision,
                        next_action=final_next_action,
                    )

                    # Log structured evaluation and audit event
                    if self.memory_enabled and self.memory:
                        try:
                            # Create debug payload
                            debug_payload = {
                                "candidate_id": folder_id,
                                "candidate_name": folder_name,
                                "stage": "L2",
                                "prompt": "ARJUN_L2_PROMPT",
                                "raw_response": result.model_dump(),
                                "decision_trace": {
                                    "l2_outcome": l2_outcome,
                                    "recommendation": recommendation,
                                    "decision_reason": decision_reason,
                                },
                            }
                            debug_storage = get_debug_storage()
                            debug_uri = debug_storage.upload_debug_payload(
                                debug_payload,
                                prefix="arjun_l2",
                                run_id=self.correlation_id
                            )
                            
                            # Log evaluation
                            self.memory.log_evaluation({
                                "candidate_id": folder_id,
                                "stage": "L2",
                                "engine": "ARJUN",
                                "scores": evaluation.scores,
                                "risk_flags": result.risk_flags or [],
                                "reason_codes": [],
                                "raw_recommendation": result.final_recommendation,
                                "decision_outcome": l2_outcome,
                                "prompt_version": "v1.0",
                                "decision_logic_version": "v2.0",  # Updated with strict engine
                                "model_version": "gpt-4",
                                "debug_payload_uri": debug_uri,
                            })
                            
                            # Log audit event
                            self.memory.log_audit_event(
                                actor="ARJUN",
                                action="L2_EVALUATION_COMPLETE",
                                from_state="PENDING_L2",
                                to_state=l2_outcome,
                                metadata={
                                    "candidate_id": folder_id,
                                    "candidate_name": folder_name,
                                    "role": role,
                                    "final_score": result.final_score,
                                }
                            )
                        except Exception as log_err:
                            logger.warning(f"Failed to log L2 evaluation/audit: {log_err}", exc_info=True)

                    self._route_candidate(
                        recommendation,
                        folder_id,
                        role,
                        folder_name,
                        candidate_corr,
                    )

                    try:
                        logger.info(
                            "[%s::%s] updating_recruiter_dashboard_row",
                            candidate_corr,
                            folder_name,
                        )
                        self._update_recruiter_dashboard_row(
                            role=role,
                            candidate_name=folder_name,
                            candidate_folder_id=folder_id,
                            evaluation=evaluation,
                            result=result,
                            last_l1_event=last_l1_event,
                        )
                        logger.info(
                            "[%s::%s] recruiter_dashboard_row_updated",
                            candidate_corr,
                            folder_name,
                        )
                    except Exception:
                        logger.warning(
                            "[%s::%s] recruiter_dashboard_update_failed",
                            candidate_corr,
                            folder_name,
                            exc_info=True,
                        )

                    artifacts = {
                        "folder_id": folder_id,
                        "l2_result_path": self.RESULT_FILENAME,
                        "status_path": self.STATUS_FILENAME,
                    }
                    self._persist_memory_state(
                        evaluation=evaluation,
                        candidate_name=folder_name,
                        pipeline_recommendation=recommendation,
                        artifacts=artifacts,
                        role_profile=role_profile,
                        l1_alignment=alignment,
                        resume_text=resume_text,
                        jd_text=jd_text,
                        transcript_text=transcript_text,
                    )

                    self.summary.evaluated += 1

                except Exception as exc:
                    logger.error(
                        "candidate_processing_failed",
                        extra={
                            "correlation_id": candidate_corr,
                            "candidate_name": folder_name,
                            "role": role,
                            "error": str(exc),
                        },
                        exc_info=True,
                    )
                    self.summary.errors += 1

        summary_payload = self.summary.to_logging_dict()
        logger.info(
            "arjun_l2_batch_summary",
            extra={"correlation_id": self.correlation_id, **summary_payload},
        )
        return self.summary

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------
    def _update_recruiter_dashboard_row(
        self,
        role: str,
        candidate_name: str,
        candidate_folder_id: str,
        evaluation: L2Evaluation,
        result,
        last_l1_event: Optional[CandidateEventModel],
    ) -> None:
        if not self.recruiter_sheet_id:
            return

        try:
            sheet_title = map_role_to_sheet_title(role)
            logger.info(
                "recruiter_tab_resolved",
                extra={
                    "correlation_id": self.correlation_id,
                    "candidate_name": candidate_name,
                    "role": role,
                    "sheet_title": sheet_title,
                },
            )
            logger.info(
                "recruiter_dashboard_updating",
                extra={
                    "correlation_id": self.correlation_id,
                    "candidate_name": candidate_name,
                    "role": role,
                },
            )
            recommendation = (evaluation.recommendation or "").lower()
            if recommendation in ("strong_yes", "yes"):
                ai_status = "Shortlist"
                l2_outcome = "Strong Yes" if recommendation == "strong_yes" else "Yes"
                next_action = "Schedule Manager Round"
            elif recommendation == "lean_yes":
                ai_status = "On Hold"
                l2_outcome = "Lean Yes"
                next_action = "Need Human Review"
            elif recommendation == "lean_no":
                ai_status = "Reject"
                l2_outcome = "Lean No"
                next_action = "Reject & Send Email"
            else:
                ai_status = "Reject"
                l2_outcome = "No"
                next_action = "Reject & Send Email"

            conf = evaluation.confidence or 0.0
            if conf >= 0.8:
                overall_confidence = "High"
            elif conf >= 0.5:
                overall_confidence = "Medium"
            else:
                overall_confidence = "Low"

            ai_recommendation_detail = (
                getattr(result, "l2_summary", None)
                or getattr(result, "rationale", None)
                or "L2 evaluation completed."
            )

            key_strengths = evaluation.strengths or []
            key_concerns = evaluation.weaknesses or evaluation.risk_flags or []
            l1_outcome = self._map_l1_outcome(last_l1_event)
            feedback_link = evaluation.feedback_link or evaluation.report_link
            folder_link = f"https://drive.google.com/drive/folders/{candidate_folder_id}"

            upsert_role_sheet_row(
                file_id=self.recruiter_sheet_id,
                role=role,
                candidate_folder_id=candidate_folder_id,
                candidate_name=candidate_name,
                current_stage="L2 Completed",
                ai_status=ai_status,
                ai_recommendation_detail=ai_recommendation_detail,
                overall_confidence=overall_confidence,
                key_strengths=key_strengths,
                key_concerns=key_concerns,
                l1_outcome=l1_outcome,
                l2_outcome=l2_outcome,
                next_action=next_action,
                owner=None,
                feedback_link=feedback_link,
                folder_link=folder_link,
                last_updated=datetime.utcnow(),
            )
            logger.info(
                "recruiter_dashboard_row_updated",
                extra={
                    "correlation_id": self.correlation_id,
                    "candidate_name": candidate_name,
                    "role": role,
                },
            )
        except Exception as exc:  # pragma: no cover - network interaction
            logger.warning(
                "recruiter_dashboard_update_failed",
                extra={
                    "correlation_id": self.correlation_id,
                    "candidate_name": candidate_name,
                    "role": role,
                    "error": str(exc),
                },
                exc_info=True,
            )

    @staticmethod
    def _map_l1_outcome(last_l1_event: Optional[CandidateEventModel]) -> Optional[str]:
        if not last_l1_event or not last_l1_event.decision:
            return None

        decision = last_l1_event.decision.lower()
        if decision == "pass":
            return "Pass"
        if decision == "reject":
            return "Reject"
        if decision == "hold":
            return "Hold"
        return decision.title()

    def _has_l2_material_in_report(self, report: Dict[str, Any]) -> bool:
        """
        Check if the normalization report indicates any actual L2 input files exist.
        We need at least one of: resume, jd, or l2_transcript to proceed with L2 evaluation.
        """
        has_resume = report.get("resume") is not None
        has_jd = report.get("jd") is not None
        has_l2_transcript = report.get("l2_transcript") is not None
        
        # If we have none of the core artifacts, skip
        return has_resume or has_jd or has_l2_transcript

    def _load_normalization_report(
        self, files: List[Dict[str, Any]], correlation_id: str
    ) -> Optional[Dict[str, Any]]:
        for file_obj in files:
            if file_obj.get("name") == Normalizer.REPORT_NAME:
                try:
                    payload = self.drive.download_file_bytes(file_obj["id"])
                    return json.loads(payload.decode("utf-8"))
                except Exception as exc:
                    logger.warning(
                        "l2_report_load_failed",
                        extra={
                            "correlation_id": correlation_id,
                            "report_file_id": file_obj["id"],
                            "error": str(exc),
                        },
                        exc_info=True,
                    )
                    return None
        return None

    def _load_l1_score(
        self, files: List[Dict[str, Any]], correlation_id: str
    ) -> Optional[int]:
        for file_obj in files:
            if file_obj.get("name") == self.L1_RESULT_FILENAME:
                try:
                    payload = self.drive.download_file_bytes(file_obj["id"])
                    data = json.loads(payload.decode("utf-8"))
                    return data.get("overall_score")
                except Exception as exc:
                    logger.warning(
                        "l1_result_load_failed",
                        extra={
                            "correlation_id": correlation_id,
                            "file_id": file_obj["id"],
                            "error": str(exc),
                        },
                        exc_info=True,
                    )
                    return None
        return None

    def _apply_gating(
        self,
        report: Dict[str, Any],
        files: List[Dict[str, Any]],
        folder_id: str,
        folder_name: str,
        role: str,
        correlation_id: str,
    ) -> Optional[str]:
        # Detect L2 transcript directly from files
        l2_transcript_file = find_l2_transcript_file(files)
        
        # Add explicit debug logging
        logger.info(
            "[%s] - l2_transcript_detection | candidate_folder=%s | file_names=%s | transcript_found=%s | transcript_file_name=%s",
            correlation_id,
            folder_name,
            [f.get("name") for f in files] if files else [],
            l2_transcript_file is not None,
            l2_transcript_file.get("name") if l2_transcript_file else None,
        )
        
        if not l2_transcript_file:
            self._record_candidate_result(
                candidate_name=folder_name,
                role=role,
                decision=self.DECISION_HOLD,
                reason="L2 transcript missing",
                hold_type=self.HOLD_TYPE_MISSING_L2_TRANSCRIPT,
                hold_reason=self.HOLD_REASON_CODE_MISSING_INFO,
                candidate_folder_id=folder_id,
            )
            self._write_status_file(
                folder_id,
                self.STATUS_ON_HOLD_MISSING_L2_TRANSCRIPT,
                "L2 transcript missing",
                correlation_id,
            )
            logger.info(
                "candidate_on_hold_missing_l2_transcript",
                extra={
                    "correlation_id": correlation_id,
                    "candidate_name": folder_name,
                    "role": role,
                },
            )
            return self.STATUS_ON_HOLD_MISSING_L2_TRANSCRIPT

        if not report.get("resume") or not report.get("jd"):
            self._mark_data_incomplete(
                folder_id,
                folder_name,
                role,
                correlation_id,
                reason="missing_resume_or_jd",
            )
            return self.STATUS_DATA_INCOMPLETE

        return None

    def _mark_data_incomplete(
        self,
        folder_id: str,
        folder_name: str,
        role: str,
        correlation_id: str,
        reason: str,
    ) -> None:
        self._record_candidate_result(
            candidate_name=folder_name,
            role=role,
            decision=self.DECISION_HOLD,
            reason=reason,
            hold_type=self.HOLD_TYPE_DATA_INCOMPLETE,
            hold_reason=self.HOLD_REASON_CODE_MISSING_INFO,
            candidate_folder_id=folder_id,
        )
        self._write_status_file(
            folder_id,
            self.STATUS_DATA_INCOMPLETE,
            reason,
            correlation_id,
        )
        logger.info(
            "candidate_data_incomplete_l2",
            extra={
                "correlation_id": correlation_id,
                "candidate_name": folder_name,
                "role": role,
                "reason": reason,
            },
        )

    def _extract_text_from_entry(
        self, entry: Dict[str, Any], correlation_id: str
    ) -> str:
        if not entry:
            return ""
        file_id = entry["id"]
        name = entry.get("name", "")
        mime = (entry.get("mimeType") or "").lower()

        if mime == "application/vnd.google-apps.document":
            return self.drive.export_google_doc_to_text(file_id)

        data = self.drive.download_file_bytes(file_id)

        if name.lower().endswith(".pdf") or mime == "application/pdf":
            return extract_pdf_text(data)

        if name.lower().endswith(".docx") or "wordprocessingml.document" in mime:
            return extract_docx_text(data)

        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning(
                "l2_text_decode_fallback",
                extra={
                    "correlation_id": correlation_id,
                    "file_id": file_id,
                    "name": name,
                },
            )
            return data.decode("utf-8", errors="ignore")

    @staticmethod
    def _compute_l1_l2_comparison(
        l1_score: Optional[int], l2_score: int
    ) -> str:
        if l1_score is None:
            return "N/A"
        delta = l2_score - l1_score
        if delta >= 5:
            return "IMPROVED"
        if delta <= -5:
            return "REGRESSED"
        return "CONSISTENT"

    def _persist_l2_result(
        self,
        folder_id: str,
        evaluation: L2Evaluation,
        result,
        pipeline_recommendation: str,
        comparison: str,
        correlation_id: str,
    ) -> None:
        payload = {
            "final_recommendation": pipeline_recommendation,
            "final_score": result.final_score,
            "l2_summary": result.l2_summary,
            "l1_l2_comparison": comparison,
            "risk_flags": result.risk_flags,
            "rationale": result.rationale,
            "structured_evaluation": evaluation.model_dump(),
        }
        try:
            self.drive.write_json_file(folder_id, self.RESULT_FILENAME, payload)
        except Exception as exc:
            logger.warning(
                "l2_result_write_failed",
                extra={
                    "correlation_id": correlation_id,
                    "folder_id": folder_id,
                    "error": str(exc),
                },
                exc_info=True,
            )

    def _persist_memory_state(
        self,
        evaluation: L2Evaluation,
        candidate_name: str,
        pipeline_recommendation: str,
        artifacts: Dict[str, str],
        role_profile: Optional[RoleProfileModel],
        l1_alignment: str,
        resume_text: str,
        jd_text: str,
        transcript_text: str,
    ) -> None:
        if not (self.memory_enabled and self.memory):
            return

        if self.use_candidate_memory:
            final_outcome = self._map_final_outcome(pipeline_recommendation)
            profile = CandidateProfileModel(
                candidate_id=evaluation.candidate_id,
                name=candidate_name,
                role=evaluation.role,
                skills={
                    "strengths": evaluation.strengths,
                    "weaknesses": evaluation.weaknesses,
                    "risk_flags": evaluation.risk_flags,
                },
                experience_years=None,
                final_outcome=final_outcome,
            )
            self.memory.upsert_candidate_profile(profile)

            event_inputs = self._build_event_inputs_snapshot(
                resume_text,
                jd_text,
                transcript_text,
            )
            inputs_hash = MemoryService.compute_inputs_hash(event_inputs)
            event = CandidateEventModel(
                candidate_id=evaluation.candidate_id,
                run_id=self.correlation_id,
                stage="L2",
                agent="arjun",
                inputs_hash=inputs_hash,
                scores=evaluation.scores,
                decision=candidate_event_decision_from_l2(evaluation.recommendation),
                confidence=evaluation.confidence,
                artifacts={**artifacts, "alignment_with_l1": l1_alignment},
            )
            self.memory.append_candidate_event(event)
            logger.info(
                "memory_l2_event_saved",
                extra={
                    "correlation_id": self.correlation_id,
                    "candidate_id": evaluation.candidate_id,
                    "run_id": self.correlation_id,
                    "stage": "L2",
                },
            )

        if self.use_role_memory and role_profile is None:
            derived_profile = RoleProfileModel(
                role=evaluation.role,
                competency_weights=evaluation.scores,
                common_rejection_reasons=evaluation.weaknesses[:5],
                top_performer_patterns=evaluation.strengths[:5],
                notes="Auto-generated from L2 evaluation",
            )
            self.memory.upsert_role_profile(derived_profile)
            logger.info(
                "memory_role_profile_seeded_l2",
                extra={
                    "correlation_id": self.correlation_id,
                    "role": evaluation.role,
                },
            )

    @staticmethod
    def _map_final_outcome(recommendation: str) -> str:
        mapping = {
            "HIRE": "shortlisted",
            "REJECT": "rejected",
            "HOLD": "on_hold",
        }
        return mapping.get(recommendation, "unknown")

    @staticmethod
    def _build_event_inputs_snapshot(
        resume_text: str,
        jd_text: str,
        transcript_text: str,
    ) -> Dict[str, str]:
        def _clip(text: str, limit: int = 2000) -> str:
            if not text:
                return ""
            return text[:limit]

        return {
            "resume": _clip(resume_text),
            "jd": _clip(jd_text),
            "transcript": _clip(transcript_text),
        }

    def _prepare_memory_context(
        self,
        candidate_id: str,
        role: str,
        candidate_name: str,
        correlation_id: str,
    ) -> Tuple[Optional[str], Optional[CandidateEventModel], Optional[RoleProfileModel]]:
        if not (self.memory_enabled and self.memory):
            return None, None, None

        context_sections: List[str] = []
        candidate_profile: Optional[CandidateProfileModel] = None
        last_l1_event: Optional[CandidateEventModel] = None
        role_profile: Optional[RoleProfileModel] = None

        event_count = 0
        if self.use_candidate_memory:
            candidate_profile = self.memory.get_candidate_profile(candidate_id)
            l1_events = self.memory.get_candidate_events(candidate_id, stage="L1", limit=3)
            event_count = len(l1_events)
            last_l1_event = l1_events[0] if l1_events else None

            if candidate_profile:
                context_sections.append(
                    "Candidate profile: "
                    f"name={candidate_profile.name}, role={candidate_profile.role}, "
                    f"outcome={candidate_profile.final_outcome}"
                )
                strengths = candidate_profile.skills.get("strengths") if isinstance(candidate_profile.skills, dict) else None
                if strengths:
                    context_sections.append("Stored strengths: " + ", ".join(strengths))

            if last_l1_event:
                context_sections.append(
                    f"Last L1 decision={last_l1_event.decision} (confidence={last_l1_event.confidence})"
                )

        if self.use_role_memory:
            role_profile = self.memory.get_role_profile(role)
            if role_profile:
                context_sections.append(
                    f"Role rubric v{role_profile.rubric_version}: weights={role_profile.competency_weights}"
                )
                if role_profile.common_rejection_reasons:
                    context_sections.append(
                        "Common L2 rejection reasons: " + ", ".join(role_profile.common_rejection_reasons)
                    )
                if role_profile.top_performer_patterns:
                    context_sections.append(
                        "Top performer traits: " + ", ".join(role_profile.top_performer_patterns)
                    )

        context_blob = "\n".join(context_sections) if context_sections else None

        logger.info(
            "memory_context_loaded_l2",
            extra={
                "correlation_id": correlation_id,
                "candidate_id": candidate_id,
                "candidate_profile": bool(candidate_profile),
                "role_profile": bool(role_profile),
                "has_l1_event": bool(last_l1_event),
                "event_count": event_count,
            },
        )

        return context_blob, last_l1_event, role_profile

    def _log_to_sheet(
        self,
        role: str,
        candidate_name: str,
        result,
        evaluation: L2Evaluation,
        recommendation: str,
    ) -> None:
        try:
            self.sheet.append_row(
                sheet_id="15iFeJ7kkM9_-29VC11DLhGx8NvZNQVkMYqpajeh3rho",
                sheet_name="Sheet1",
                row_values=[
                    role,
                    candidate_name,
                    result.final_score,
                    recommendation,
                    "; ".join(evaluation.strengths),
                    "; ".join(evaluation.weaknesses),
                    "; ".join(evaluation.risk_flags),
                    result.leadership_assessment,
                    result.technical_capability,
                ],
            )
        except Exception as exc:
            logger.warning(
                "l2_sheet_log_failed",
                extra={"candidate": candidate_name, "role": role, "error": str(exc)},
                exc_info=True,
            )

    @staticmethod
    def _normalize_recommendation(value: Optional[str]) -> str:
        if not value:
            return "HOLD"

        normalized = value.strip().upper()
        mapping = {
            "SHORTLIST": "HIRE",
            "ADVANCE": "HIRE",
            "MOVE_FORWARD": "HIRE",
            "PASS": "REJECT",
            "DECLINE": "REJECT",
            "DROP": "REJECT",
            "WAITLIST": "HOLD",
            "NEEDS_REVIEW": "HOLD",
        }

        normalized = mapping.get(normalized, normalized)
        if normalized not in {"HIRE", "REJECT", "HOLD"}:
            return "HOLD"
        return normalized

    def _route_candidate(
        self,
        recommendation: str,
        folder_id: str,
        role: str,
        candidate_name: str,
        correlation_id: str,
    ) -> None:
        if recommendation == "HIRE":
            target = get_shortlist_folder(role)
            if not target:
                logger.error(
                    "l2_shortlist_folder_missing",
                    extra={
                        "correlation_id": correlation_id,
                        "role": role,
                        "candidate_name": candidate_name,
                    },
                )
                return
            self.drive.move_folder(folder_id, target)
            return

        if recommendation == "REJECT":
            target = get_l2_reject_folder(role)
            if not target:
                logger.error(
                    "l2_reject_folder_missing",
                    extra={
                        "correlation_id": correlation_id,
                        "role": role,
                        "candidate_name": candidate_name,
                    },
                )
                return
            self.drive.move_folder(folder_id, target)
            return

        if recommendation == "HOLD":
            self._write_status_file(
                folder_id,
                self.STATUS_EVALUATION_HOLD,
                "Awaiting L2 reviewer",
                correlation_id,
            )
            return

        logger.warning(
            "unknown_l2_recommendation",
            extra={
                "correlation_id": correlation_id,
                "role": role,
                "candidate_name": candidate_name,
                "recommendation": recommendation,
            },
        )
        self._write_status_file(
            folder_id,
            self.STATUS_EVALUATION_HOLD,
            f"Unknown L2 recommendation: {recommendation}",
            correlation_id,
        )
        return

    def _write_status_file(
        self,
        folder_id: str,
        status: str,
        detail: str,
        correlation_id: str,
    ) -> None:
        payload = {
            "status": status,
            "detail": detail,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "correlation_id": correlation_id,
        }
        try:
            self.drive.write_json_file(folder_id, self.STATUS_FILENAME, payload)
        except Exception as exc:
            logger.warning(
                "l2_status_write_failed",
                extra={
                    "correlation_id": correlation_id,
                    "folder_id": folder_id,
                    "status": status,
                    "error": str(exc),
                },
                exc_info=True,
            )

    def _candidate_folder_link(self, candidate_folder_id: str) -> str:
        return f"https://drive.google.com/drive/folders/{candidate_folder_id}"

    def _build_dashboard_link(self) -> Optional[str]:
        if not self.recruiter_sheet_id:
            return None
        return f"https://docs.google.com/spreadsheets/d/{self.recruiter_sheet_id}"

    def _record_candidate_result(
        self,
        *,
        candidate_name: str,
        role: str,
        decision: str,
        reason: Optional[str],
        hold_type: Optional[str] = None,
        hold_reason: Optional[str] = None,
        candidate_folder_id: str,
        feedback_link: Optional[str] = None,
    ) -> None:
        normalized = (decision or "").lower()
        if normalized in {"shortlisted", "hire", "shortlist"}:
            normalized = self.DECISION_SHORTLIST
        elif normalized in {"rejected", "reject"}:
            normalized = self.DECISION_REJECT
        elif normalized not in {self.DECISION_SHORTLIST, self.DECISION_REJECT, self.DECISION_HOLD}:
            normalized = self.DECISION_HOLD

        self.summary.candidates.append(
            L2CandidateResult(
                candidate_name=candidate_name,
                role=role,
                decision=normalized,
                reason=reason,
                hold_type=hold_type,
                hold_reason=hold_reason,
                folder_link=self._candidate_folder_link(candidate_folder_id),
                feedback_link=feedback_link,
                dashboard_link=self._build_dashboard_link(),
            )
        )

        if normalized == self.DECISION_SHORTLIST:
            self.summary.hires += 1
        elif normalized == self.DECISION_REJECT:
            self.summary.rejects += 1
        elif normalized == self.DECISION_HOLD:
            self.summary.hold_decisions += 1
            if hold_reason == self.HOLD_REASON_CODE_MANUAL_REVIEW:
                self.summary.needs_manual_review += 1
            elif hold_reason == self.HOLD_REASON_CODE_BACKUP:
                self.summary.hold_backup_pool += 1

            if hold_type == self.HOLD_TYPE_MISSING_L2_TRANSCRIPT:
                self.summary.on_hold_missing_l2_transcript += 1
            if hold_type == self.HOLD_TYPE_DATA_INCOMPLETE:
                self.summary.data_incomplete += 1
            if hold_type == self.HOLD_TYPE_SKIPPED_NO_L2:
                self.summary.skipped_no_l2 += 1

    def _record_final_decision_if_applicable(
        self,
        *,
        candidate_name: str,
        role: str,
        decision: str,
        next_action: Optional[str],
    ) -> None:
        if not self._final_decision_store:
            return

        label = self._map_final_decision_label(decision)
        if not label:
            return

        try:
            self._final_decision_store.upsert_decision(
                candidate_name=candidate_name,
                role=role,
                decision=label,
                next_action=next_action,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "final_decision_store_write_failed",
                extra={
                    "candidate": candidate_name,
                    "role": role,
                    "decision": decision,
                    "error": str(exc),
                },
            )

    def _map_final_decision_label(self, decision: str) -> Optional[str]:
        normalized = (decision or "").strip().lower()
        if normalized == self.DECISION_SHORTLIST:
            return "Final Hire"
        if normalized == self.DECISION_REJECT:
            return "Final Reject"
        return None

    def _final_next_action_for_decision(self, decision: str) -> Optional[str]:
        normalized = (decision or "").strip().lower()
        if normalized == self.DECISION_SHORTLIST:
            return "Send offer & start onboarding"
        if normalized == self.DECISION_REJECT:
            return "Share rejection feedback"
        return None
