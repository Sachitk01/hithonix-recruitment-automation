import json
import logging
import os
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from decision_store import DecisionStore
from drive_service import DriveManager
from evaluation_converters import convert_riva_result
from evaluation_models import (
    CandidateEvent as CandidateEventModel,
    CandidateProfile as CandidateProfileModel,
    L1Evaluation,
    RoleProfile as RoleProfileModel,
)
from folder_map import L1_FOLDERS
from folder_resolver import get_l2_folder, get_reject_folder
from memory_config import (
    is_memory_enabled,
    should_use_candidate_memory,
    should_use_role_memory,
)
from memory_service import MemoryService, get_memory_service
from debug_storage import get_debug_storage
from normalizer import Normalizer
from riva_file_resolver import RivaFileBundle, RivaFileResolver
from riva_l1.riva_l1_models import L1BatchSummary, L1CandidateResult
from riva_l1.riva_l1_service import RivaL1Service
from riva_l1.decision_engine import decide_l1_outcome
from riva_output_writer import RivaOutputWriter
from sheet_service import map_role_to_sheet_title, upsert_role_sheet_row


RECRUITER_SHEET_FILE_ID = os.getenv("RECRUITER_SHEET_FILE_ID")

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class RivaL1BatchProcessor:
    RESULT_FILENAME = "l1_result.json"
    STATUS_FILENAME = "l1_status.json"
    STATUS_ON_HOLD_MISSING_L1_TRANSCRIPT = "ON_HOLD_MISSING_L1_TRANSCRIPT"
    STATUS_DATA_INCOMPLETE = "DATA_INCOMPLETE"
    STATUS_EVALUATION_HOLD = "HOLD"

    DECISION_MOVE_TO_L2 = "move_to_l2"
    DECISION_REJECT = "reject"
    DECISION_HOLD = "hold"

    HOLD_REASON_MISSING_TRANSCRIPT = "MISSING_L1_TRANSCRIPT"
    HOLD_REASON_DATA_INCOMPLETE = "DATA_INCOMPLETE"
    HOLD_REASON_LOW_CONFIDENCE = "LOW_CONFIDENCE"
    HOLD_REASON_AMBIGUOUS = "AMBIGUOUS_SIGNALS"
    HOLD_REASON_JD_MISMATCH = "JD_MISMATCH"
    HOLD_REASON_CAPACITY = "CAPACITY_BACKUP"

    HOLD_REASON_CODE_MANUAL_REVIEW = "manual_review_required"
    HOLD_REASON_CODE_BACKUP = "backup_for_l2_capacity"
    HOLD_REASON_CODE_MISSING_INFO = "missing_noncritical_info"

    PASS_MIN_OVERALL = 0.78
    PASS_MIN_CONFIDENCE = 0.55
    REJECT_MAX_OVERALL = 0.45
    REJECT_MAX_CONFIDENCE = 0.40
    LOW_COMMUNICATION_REJECT_MAX = 0.65
    CREAMY_LAYER_CAP = 0.45

    def __init__(
        self,
        *,
        correlation_id: Optional[str] = None,
        drive: Optional[DriveManager] = None,
        normalizer: Optional[Normalizer] = None,
        file_resolver: Optional[RivaFileResolver] = None,
        riva: Optional[RivaL1Service] = None,
        decision_store: Optional[DecisionStore] = None,
        memory_service: Optional[MemoryService] = None,
    ) -> None:
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.drive = drive or DriveManager(correlation_id=self.correlation_id)
        self.normalizer = normalizer or Normalizer(self.drive)
        self.file_resolver = file_resolver or RivaFileResolver(self.drive)
        self.riva = riva or RivaL1Service()
        self.summary = L1BatchSummary()
        self.decision_store = decision_store or DecisionStore()
        self.recruiter_sheet_id = RECRUITER_SHEET_FILE_ID

        self.memory_enabled = is_memory_enabled()
        self.use_candidate_memory = should_use_candidate_memory()
        self.use_role_memory = should_use_role_memory()
        self.memory: Optional[MemoryService] = None

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
                    exc_info=True,
                )
                self.memory_enabled = False
                self.use_candidate_memory = False
                self.use_role_memory = False
        else:
            self.use_candidate_memory = False
            self.use_role_memory = False

        if not self.recruiter_sheet_id:
            logger.info(
                "recruiter_sheet_id_missing",
                extra={"correlation_id": self.correlation_id},
            )
        else:
            logger.info(
                "recruiter_sheet_id_loaded",
                extra={
                    "correlation_id": self.correlation_id,
                    "sheet_id": self.recruiter_sheet_id,
                },
            )

    # -------------------------------------------------------
    # CANDIDATE FOLDER DISCOVERY
    # -------------------------------------------------------
    def get_candidate_folders_for_role(self, role_folder_id: str, role_name: str, corr_id: str) -> list:
        """
        Discover candidate folders for a given role.
        Uses folder-like to pick up both real folders and future shortcuts.
        
        Args:
            role_folder_id: The role folder ID
            role_name: The role name for logging
            corr_id: Correlation ID for tracing
            
        Returns:
            List of candidate folder items (dicts with id, name, mimeType, etc.)
        """
        candidates = self.drive.list_folder_like(role_folder_id, correlation_id=corr_id)
        
        logger.info(
            "role_candidate_folders",
            extra={
                "role": role_name,
                "role_folder_id": role_folder_id,
                "candidate_count": len(candidates),
                "correlation_id": corr_id,
            },
        )
        
        return candidates

    # -------------------------------------------------------
    # MAIN PIPELINE
    # -------------------------------------------------------
    def run(self) -> L1BatchSummary:
        logger.info(
            "Starting Riva L1 Batch processing",
            extra={"correlation_id": self.correlation_id}
        )
        
        print("\n===================================")
        print("🚀 Riva L1 Batch — Starting")
        print(f"🔍 Correlation ID: {self.correlation_id}")
        print("===================================\n")

        # ---------------------------------------------------
        # STEP 1 — NORMALIZE CANDIDATE FOLDERS
        # ---------------------------------------------------
        try:
            logger.info(
                "Starting normalization phase",
                extra={"correlation_id": self.correlation_id}
            )
            print("🔧 Normalizing candidate folders...")
            self.normalizer.run(correlation_id=self.correlation_id)
            logger.info(
                "Normalization phase completed successfully",
                extra={"correlation_id": self.correlation_id}
            )
            print("✔ Normalization Completed.\n")
        except Exception as e:
            logger.error(
                "Normalization phase failed: %s",
                str(e),
                extra={"correlation_id": self.correlation_id, "error": str(e)},
                exc_info=True
            )
            print(f"❌ Normalization failed: {e}")
            traceback.print_exc()
            # non-blocking – we still attempt processing

        # ---------------------------------------------------
        # STEP 2 — L1 PROCESSING LOOP
        # ---------------------------------------------------
        total_roles = len(L1_FOLDERS)
        logger.info(
            "Starting L1 processing for %d role folders",
            total_roles,
            extra={"correlation_id": self.correlation_id, "role_count": total_roles}
        )
        
        for role, l1_folder_id in L1_FOLDERS.items():
            logger.info(
                "Processing role folder: %s",
                role,
                extra={
                    "correlation_id": self.correlation_id,
                    "role": role,
                    "folder_id": l1_folder_id
                }
            )
            print(f"📁 Checking Role Folder: {role}\n")

            try:
                # Discover candidate folders under this role folder
                candidate_folders = self.get_candidate_folders_for_role(
                    l1_folder_id, 
                    role, 
                    self.correlation_id
                )
                
                if len(candidate_folders) == 0:
                    logger.warning(
                        "No candidate folders found in role folder %s",
                        role,
                        extra={
                            "correlation_id": self.correlation_id,
                            "role": role,
                            "folder_id": l1_folder_id
                        }
                    )
                    print(f"⚠️  No candidate folders found for role: {role}\n")
                    continue
                
            except Exception as e:
                logger.error(
                    "Failed to list candidate folders for role %s: %s",
                    role,
                    str(e),
                    extra={
                        "correlation_id": self.correlation_id,
                        "role": role,
                        "folder_id": l1_folder_id,
                        "error": str(e)
                    },
                    exc_info=True
                )
                print(f"❌ Failed to list candidate folders for role={role}: {e}")
                traceback.print_exc()
                self.summary.errors += 1
                continue

            for candidate in candidate_folders:
                folder_id = self.drive.get_real_folder_id(candidate)
                folder_name = candidate["name"]
                candidate_correlation_id = f"{self.correlation_id}::{folder_name}"
                self.summary.total_seen += 1

                logger.info(
                    "Processing candidate: %s",
                    folder_name,
                    extra={
                        "correlation_id": candidate_correlation_id,
                        "candidate_name": folder_name,
                        "candidate_folder_id": folder_id,
                        "role": role,
                    },
                )

                print("\n-------------------------------------")
                print(f"👤 Processing Candidate: {folder_name}")
                print(f"🔍 Candidate Correlation ID: {candidate_correlation_id}")
                print("-------------------------------------\n")

                try:
                    files = self.drive.list_files(
                        folder_id, correlation_id=candidate_correlation_id
                    )
                    artifacts = self._load_candidate_artifacts(
                        files, candidate_correlation_id
                    )
                    if artifacts is None:
                        self._mark_data_incomplete(
                            folder_id,
                            folder_name,
                            role,
                            candidate_correlation_id,
                            reason="normalization_report_missing",
                        )
                        continue

                    gating_status = self._apply_gating(
                        artifacts,
                        folder_id,
                        folder_name,
                        role,
                        candidate_correlation_id,
                    )
                    if gating_status:
                        continue

                    bundle = self.file_resolver.load(
                        folder_id,
                        role_name=role,
                        candidate_name=folder_name,
                        correlation_id=candidate_correlation_id,
                    )

                    memory_context, _, _, role_profile = (
                        self._prepare_memory_context(
                            folder_id,
                            role,
                            folder_name,
                            candidate_correlation_id,
                        )
                    )

                    logger.info(
                        "Running Riva L1 evaluation for candidate %s",
                        folder_name,
                        extra={
                            "correlation_id": candidate_correlation_id,
                            "candidate_name": folder_name,
                        },
                    )
                    result = self.riva.evaluate(
                        resume_text=bundle.resume_text,
                        jd_text=bundle.jd_text,
                        transcript_text=bundle.transcript_text,
                        feedback_text=bundle.feedback_text,
                        memory_context=memory_context,
                    )

                    bundle_meta = bundle.meta if hasattr(bundle, "meta") else {}
                    preliminary_evaluation = convert_riva_result(
                        candidate_id=folder_id,
                        role=role,
                        pipeline_decision="HOLD",
                        result=result,
                    )
                    pipeline_decision, decision_reason, hold_type = self._determine_pipeline_decision(
                        evaluation=preliminary_evaluation,
                        result=result,
                        bundle=bundle,
                        evaluated_so_far=self.summary.evaluated,
                    )
                    hold_reason_code = self._resolve_hold_reason_code(hold_type)
                    evaluation = convert_riva_result(
                        candidate_id=folder_id,
                        role=role,
                        pipeline_decision=pipeline_decision,
                        result=result,
                    )
                    human_decision = {
                        "SEND_TO_L2": self.DECISION_MOVE_TO_L2,
                        "REJECT_AT_L1": self.DECISION_REJECT,
                    }.get(pipeline_decision, self.DECISION_HOLD)
                    feedback_link = self._extract_meta_file_link(bundle_meta, "l1_feedback")
                    logger.info(
                        "[%s::%s] l1_decision=%s manual_review_reason=%s",
                        candidate_correlation_id,
                        folder_name,
                        human_decision,
                        decision_reason if human_decision == self.DECISION_HOLD else "",
                        extra={
                            "fit_score": result.fit_score,
                            "confidence": evaluation.confidence,
                            "pipeline_decision": pipeline_decision,
                        },
                    )
                    self._record_candidate_result(
                        candidate_name=folder_name,
                        role=role,
                        decision=human_decision,
                        reason=decision_reason,
                        hold_type=hold_type,
                        hold_reason=hold_reason_code,
                        candidate_folder_id=folder_id,
                        feedback_link=feedback_link,
                        dashboard_link=self._build_dashboard_link(role),
                    )

                    logger.info(
                        "Riva L1 evaluation completed for %s",
                        folder_name,
                        extra={
                            "correlation_id": candidate_correlation_id,
                            "candidate_name": folder_name,
                            "decision": pipeline_decision,
                            "fit_score": result.fit_score,
                        },
                    )

                    # Log structured evaluation and audit event
                    if self.memory_enabled and self.memory:
                        try:
                            # Create debug payload
                            debug_payload = {
                                "candidate_id": folder_id,
                                "candidate_name": folder_name,
                                "stage": "L1",
                                "prompt": "RIVA_L1_PROMPT",  # Could extract from service
                                "raw_response": result.model_dump(),
                                "bundle_meta": bundle_meta,
                                "decision_trace": {
                                    "pipeline_decision": pipeline_decision,
                                    "decision_reason": decision_reason,
                                    "hold_type": hold_type,
                                },
                            }
                            debug_storage = get_debug_storage()
                            debug_uri = debug_storage.upload_debug_payload(
                                debug_payload,
                                prefix="riva_l1",
                                run_id=self.correlation_id
                            )
                            
                            # Log evaluation
                            self.memory.log_evaluation({
                                "candidate_id": folder_id,
                                "stage": "L1",
                                "engine": "RIVA",
                                "scores": evaluation.scores,
                                "risk_flags": evaluation.risk_flags or [],
                                "reason_codes": [],  # Not available in current model
                                "raw_recommendation": result.final_decision,
                                "decision_outcome": pipeline_decision,
                                "prompt_version": "v1.0",
                                "decision_logic_version": "v2.0",  # Updated with new engine
                                "model_version": "gpt-4",  # Could be dynamic
                                "debug_payload_uri": debug_uri,
                            })
                            
                            # Log audit event for state transition
                            self.memory.log_audit_event(
                                actor="RIVA",
                                action="L1_EVALUATION_COMPLETE",
                                from_state="PENDING_L1",
                                to_state=pipeline_decision,
                                metadata={
                                    "candidate_id": folder_id,
                                    "candidate_name": folder_name,
                                    "role": role,
                                    "fit_score": result.fit_score,
                                }
                            )
                        except Exception as log_err:
                            logger.warning(f"Failed to log evaluation/audit: {log_err}", exc_info=True)

                    self._persist_l1_result(
                        folder_id,
                        result,
                        evaluation,
                        pipeline_decision,
                        candidate_correlation_id,
                    )

                    RivaOutputWriter.generate_riva_report(folder_id, result)
                    if pipeline_decision == "SEND_TO_L2":
                        RivaOutputWriter.generate_l2_questionnaire(folder_id, result)

                    artifacts = {
                        "folder_id": folder_id,
                        "l1_result_path": self.RESULT_FILENAME,
                        "status_path": self.STATUS_FILENAME,
                    }
                    self._persist_memory_state(
                        evaluation=evaluation,
                        candidate_name=folder_name,
                        bundle=bundle,
                        artifacts=artifacts,
                        role_profile=role_profile,
                    )

                    self._log_decision(
                        candidate_name=folder_name,
                        role=role,
                        correlation_id=candidate_correlation_id,
                        result=result,
                        evaluation=evaluation,
                        pipeline_recommendation=pipeline_decision,
                        candidate_folder_id=folder_id,
                        hold_reason_code=hold_reason_code,
                        hold_type=hold_type,
                        bundle_meta=bundle_meta,
                    )

                    self._route_candidate(
                        pipeline_decision,
                        folder_id,
                        role,
                        folder_name,
                        candidate_correlation_id,
                    )

                    self.summary.evaluated += 1

                except Exception as e:
                    logger.error(
                        "Error processing candidate %s: %s",
                        folder_name,
                        str(e),
                        extra={
                            "correlation_id": candidate_correlation_id,
                            "candidate_name": folder_name,
                            "error": str(e),
                        },
                        exc_info=True,
                    )
                    print(f"❌ Error processing {folder_name}: {str(e)}")
                    traceback.print_exc()
                    self.summary.errors += 1

        # ---------------------------------------------------
        # STEP 3 — SUMMARY
        # ---------------------------------------------------
        summary_payload = self.summary.to_logging_dict()
        logger.info(
            "riva_l1_batch_summary",
            extra={"correlation_id": self.correlation_id, **summary_payload},
        )

        print("\n===================================")
        print("✅ Riva L1 Batch Completed")
        print("===================================")
        print(f"Total seen: {self.summary.total_seen}")
        print(f"Evaluated: {self.summary.evaluated}")
        print(f"Moved to L2: {self.summary.moved_to_l2}")
        print(f"Rejected at L1: {self.summary.rejected_at_l1}")
        print(f"Hold (total): {self.summary.hold_decisions}")
        print(
            f"Hold – manual review subset: {self.summary.needs_manual_review} | backup pool: {self.summary.hold_backup_pool}"
        )
        print(
            f"Missing transcript holds: {self.summary.hold_missing_transcript}"
        )
        print(f"Data incomplete: {self.summary.data_incomplete}")
        print(f"Errors: {self.summary.errors}\n")

        return self.summary

    # -------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------
    def _update_recruiter_dashboard_row(
        self,
        *,
        role: str,
        candidate_name: str,
        candidate_folder_id: str,
        evaluation: L1Evaluation,
        result,
        pipeline_decision: str,
        hold_reason_code: Optional[str],
        hold_type: Optional[str],
        bundle_meta: Optional[Dict[str, Any]],
        correlation_id: str,
    ) -> None:
        if not self.recruiter_sheet_id:
            return

        try:
            sheet_title = map_role_to_sheet_title(role)
            logger.info(
                "recruiter_dashboard_updating",
                extra={
                    "correlation_id": correlation_id,
                    "candidate_name": candidate_name,
                    "role": role,
                    "sheet_title": sheet_title,
                },
            )

            decision_key = (pipeline_decision or "").upper()
            base_detail = (
                getattr(result, "match_summary", None)
                or getattr(result, "summary", None)
                or "L1 evaluation completed."
            )

            if decision_key == "SEND_TO_L2":
                ai_status = "Move to L2"
                l1_outcome = "Move to L2"
                next_action = "Move to L2"
                ai_recommendation_detail = base_detail
            elif decision_key == "REJECT_AT_L1":
                ai_status = "Reject"
                l1_outcome = "Reject"
                next_action = "Reject & Send Email"
                ai_recommendation_detail = base_detail
            else:
                ai_status = "Hold"
                l1_outcome = "Hold"
                ai_recommendation_detail = self._describe_hold_reason_for_sheet(
                    hold_reason_code,
                    hold_type,
                    base_detail,
                )
                next_action = ai_recommendation_detail or "Hold – recruiter follow-up"

            confidence = evaluation.confidence or 0.0
            if confidence >= 0.8:
                overall_confidence = "High"
            elif confidence >= 0.5:
                overall_confidence = "Medium"
            else:
                overall_confidence = "Low"

            key_strengths = evaluation.strengths or []
            key_concerns = evaluation.weaknesses or evaluation.risk_flags or []
            feedback_link = self._extract_meta_file_link(bundle_meta, "l1_feedback")
            folder_link = self._candidate_folder_link(candidate_folder_id)

            upsert_role_sheet_row(
                file_id=self.recruiter_sheet_id,
                role=role,
                candidate_folder_id=candidate_folder_id,
                candidate_name=candidate_name,
                current_stage="L1 Completed",
                ai_status=ai_status,
                ai_recommendation_detail=ai_recommendation_detail,
                overall_confidence=overall_confidence,
                key_strengths=key_strengths,
                key_concerns=key_concerns,
                l1_outcome=l1_outcome,
                l2_outcome=None,
                next_action=next_action,
                owner=None,
                feedback_link=feedback_link,
                folder_link=folder_link,
                last_updated=datetime.utcnow(),
            )
            logger.info(
                "recruiter_dashboard_row_updated",
                extra={
                    "correlation_id": correlation_id,
                    "candidate_name": candidate_name,
                    "role": role,
                },
            )
        except Exception as exc:  # pragma: no cover - network interaction
            logger.warning(
                "recruiter_dashboard_update_failed",
                extra={
                    "correlation_id": correlation_id,
                    "candidate_name": candidate_name,
                    "role": role,
                    "error": str(exc),
                },
                exc_info=True,
            )

    @staticmethod
    def _extract_meta_file_link(
        meta: Optional[Dict[str, Any]], key: str
    ) -> Optional[str]:
        if not isinstance(meta, dict):
            return None

        entry = meta.get(key)
        if isinstance(entry, dict):
            link = entry.get("webViewLink") or entry.get("alternateLink")
            if link:
                return link
            file_id = entry.get("id")
            if file_id:
                return f"https://drive.google.com/file/d/{file_id}/view"
        return None

    @staticmethod
    def _extract_meta_file_name(
        meta: Optional[Dict[str, Any]], key: str
    ) -> Optional[str]:
        if not isinstance(meta, dict):
            return None
        entry = meta.get(key)
        if isinstance(entry, dict):
            return entry.get("name")
        return None

    def _load_candidate_artifacts(
        self, files: List[Dict[str, Any]], correlation_id: str
    ) -> Optional[Dict[str, Any]]:
        for file_obj in files:
            if file_obj.get("name") == Normalizer.REPORT_NAME:
                try:
                    payload = self.drive.download_file_bytes(file_obj["id"])
                    report = json.loads(payload.decode("utf-8"))
                    logger.debug(
                        "normalization_report_loaded",
                        extra={
                            "correlation_id": correlation_id,
                            "report_file_id": file_obj["id"],
                        },
                    )
                    return report
                except Exception as exc:
                    logger.warning(
                        "normalization_report_parse_failed",
                        extra={
                            "correlation_id": correlation_id,
                            "report_file_id": file_obj["id"],
                            "error": str(exc),
                        },
                        exc_info=True,
                    )
                    return None
        logger.warning(
            "normalization_report_missing",
            extra={"correlation_id": correlation_id},
        )
        return None

    def _apply_gating(
        self,
        artifacts: Dict[str, Any],
        folder_id: str,
        folder_name: str,
        role: str,
        correlation_id: str,
    ) -> Optional[str]:
        if not artifacts.get("l1_transcript"):
            self._record_candidate_result(
                candidate_name=folder_name,
                role=role,
                decision=self.DECISION_HOLD,
                reason="Transcript missing",
                hold_type=self.HOLD_REASON_MISSING_TRANSCRIPT,
                hold_reason=self.HOLD_REASON_CODE_MISSING_INFO,
                candidate_folder_id=folder_id,
            )
            self._write_status_file(
                folder_id,
                self.STATUS_ON_HOLD_MISSING_L1_TRANSCRIPT,
                "L1 transcript missing",
                correlation_id,
            )
            logger.info(
                "candidate_on_hold_missing_transcript",
                extra={
                    "correlation_id": correlation_id,
                    "candidate_name": folder_name,
                    "role": role,
                },
            )
            return self.STATUS_ON_HOLD_MISSING_L1_TRANSCRIPT

        resume_present = bool(artifacts.get("resume"))
        jd_present = bool(artifacts.get("jd"))
        if not resume_present or not jd_present:
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
            hold_type=self.HOLD_REASON_DATA_INCOMPLETE,
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
            "candidate_data_incomplete",
            extra={
                "correlation_id": correlation_id,
                "candidate_name": folder_name,
                "role": role,
                "reason": reason,
            },
        )

    def _persist_l1_result(
        self,
        folder_id: str,
        result,
        evaluation: L1Evaluation,
        pipeline_recommendation: str,
        correlation_id: str,
    ) -> Dict[str, Any]:
        payload = {
            "overall_score": result.fit_score,
            "strengths": evaluation.strengths,
            "risks": evaluation.risk_flags,
            "recommendation": evaluation.recommendation,
            "pipeline_recommendation": pipeline_recommendation,
            "rationale": result.match_summary,
            "structured_evaluation": evaluation.model_dump(),
        }
        try:
            self.drive.write_json_file(
                folder_id,
                self.RESULT_FILENAME,
                payload,
            )
            logger.info(
                "l1_result_written",
                extra={
                    "correlation_id": correlation_id,
                    "folder_id": folder_id,
                },
            )
        except Exception as exc:
            logger.warning(
                "l1_result_write_failed",
                extra={
                    "correlation_id": correlation_id,
                    "folder_id": folder_id,
                    "error": str(exc),
                },
                exc_info=True,
            )
        return payload

    def _persist_memory_state(
        self,
        evaluation: L1Evaluation,
        candidate_name: str,
        bundle: RivaFileBundle,
        artifacts: Dict[str, str],
        role_profile: Optional[RoleProfileModel],
    ) -> None:
        if not (self.memory_enabled and self.memory):
            return

        experience_years = self._extract_experience_years(bundle.meta)

        if self.use_candidate_memory:
            profile = CandidateProfileModel(
                candidate_id=evaluation.candidate_id,
                name=candidate_name,
                role=evaluation.role,
                skills={
                    "strengths": evaluation.strengths,
                    "weaknesses": evaluation.weaknesses,
                    "risk_flags": evaluation.risk_flags,
                },
                experience_years=experience_years,
                final_outcome="unknown",
            )
            self.memory.upsert_candidate_profile(profile)

            inputs_snapshot = self._build_event_inputs_snapshot(bundle)
            inputs_hash = MemoryService.compute_inputs_hash(inputs_snapshot)
            event = CandidateEventModel(
                candidate_id=evaluation.candidate_id,
                run_id=self.correlation_id,
                stage="L1",
                agent="riva",
                inputs_hash=inputs_hash,
                scores=evaluation.scores,
                decision=evaluation.recommendation,
                confidence=evaluation.confidence,
                artifacts=artifacts,
            )

            self.memory.append_candidate_event(event)
            logger.info(
                "memory_candidate_event_saved",
                extra={
                    "correlation_id": self.correlation_id,
                    "candidate_id": evaluation.candidate_id,
                    "run_id": self.correlation_id,
                    "stage": "L1",
                },
            )

        if self.use_role_memory and role_profile is None:
            # No role profile yet; seed with aggregate strengths/risks for future runs.
            derived_profile = RoleProfileModel(
                role=evaluation.role,
                competency_weights=evaluation.scores,
                common_rejection_reasons=evaluation.weaknesses[:5],
                top_performer_patterns=evaluation.strengths[:5],
                notes="Auto-generated from L1 evaluation",
            )
            self.memory.upsert_role_profile(derived_profile)
            logger.info(
                "memory_role_profile_seeded",
                extra={
                    "correlation_id": self.correlation_id,
                    "role": evaluation.role,
                },
            )

    def _build_event_inputs_snapshot(self, bundle: RivaFileBundle) -> Dict[str, str]:
        def _clip(text: str, limit: int = 2000) -> str:
            if not text:
                return ""
            return text[:limit]

        return {
            "resume": _clip(bundle.resume_text),
            "jd": _clip(bundle.jd_text),
            "transcript": _clip(bundle.transcript_text),
            "feedback": _clip(bundle.feedback_text),
        }

    @staticmethod
    def _extract_experience_years(meta: Dict[str, Any]) -> Optional[float]:
        resume_meta = meta.get("resume_metadata") if isinstance(meta, dict) else None
        candidate_exp = None
        if isinstance(resume_meta, dict):
            candidate_exp = resume_meta.get("experience_years")
        if candidate_exp is None and isinstance(meta, dict):
            candidate_exp = meta.get("experience_years")
        try:
            return float(candidate_exp) if candidate_exp is not None else None
        except (TypeError, ValueError):
            return None

    def _prepare_memory_context(
        self,
        candidate_id: str,
        role: str,
        candidate_name: str,
        correlation_id: str,
    ) -> Tuple[Optional[str], Optional[CandidateProfileModel], List[CandidateEventModel], Optional[RoleProfileModel]]:
        if not (self.memory_enabled and self.memory):
            return None, None, [], None

        candidate_profile = None
        candidate_events: List[CandidateEventModel] = []
        role_profile: Optional[RoleProfileModel] = None
        context_sections: List[str] = []

        if self.use_candidate_memory:
            candidate_profile = self.memory.get_candidate_profile(candidate_id)
            candidate_events = self.memory.get_candidate_events(candidate_id, limit=3)
            if candidate_profile:
                context_sections.append(
                    "Candidate profile: "
                    f"name={candidate_profile.name}, role={candidate_profile.role}, "
                    f"last_outcome={candidate_profile.final_outcome}"
                )
                strengths = candidate_profile.skills.get("strengths") if isinstance(candidate_profile.skills, dict) else None
                if strengths:
                    context_sections.append(
                        "Known strengths: " + ", ".join(strengths)
                    )
            if candidate_events:
                for event in candidate_events:
                    context_sections.append(
                        f"Recent {event.stage} decision ({event.agent}) => {event.decision} (confidence={event.confidence})"
                    )

        if self.use_role_memory:
            role_profile = self.memory.get_role_profile(role)
            if role_profile:
                context_sections.append(
                    f"Role rubric v{role_profile.rubric_version}: weights={role_profile.competency_weights}"
                )
                if role_profile.common_rejection_reasons:
                    context_sections.append(
                        "Common rejection reasons: " + ", ".join(role_profile.common_rejection_reasons)
                    )
                if role_profile.top_performer_patterns:
                    context_sections.append(
                        "Top performer traits: " + ", ".join(role_profile.top_performer_patterns)
                    )

        context_blob = "\n".join(context_sections) if context_sections else None

        logger.info(
            "memory_context_loaded",
            extra={
                "correlation_id": correlation_id,
                "candidate_id": candidate_id,
                "candidate_profile": bool(candidate_profile),
                "event_count": len(candidate_events),
                "role_profile": bool(role_profile),
            },
        )

        return context_blob, candidate_profile, candidate_events, role_profile

    def _log_decision(
        self,
        *,
        candidate_name: str,
        role: str,
        correlation_id: str,
        result,
        evaluation: L1Evaluation,
        pipeline_recommendation: str,
        candidate_folder_id: str,
        hold_reason_code: Optional[str],
        hold_type: Optional[str],
        bundle_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        jd_title = self._extract_meta_file_name(bundle_meta, "jd")
        l1_confidence = evaluation.confidence or 0.0
        try:
            self.decision_store.log_l1_decision(
                candidate_id=candidate_folder_id,
                candidate_name=candidate_name,
                role_name=role,
                jd_title=jd_title,
                source="L1",
                recruiter_name="Riva AI",
                l1_score=result.fit_score,
                l1_decision=pipeline_recommendation,
                l1_summary=result.match_summary,
                l1_strengths="; ".join(evaluation.strengths),
                l1_concerns="; ".join(evaluation.weaknesses),
                l1_red_flags="; ".join(evaluation.risk_flags),
                l1_confidence=l1_confidence,
                l1_recommendation=pipeline_recommendation,
            )
            logger.info(
                "[%s::%s] decision_store_l1_logged",
                correlation_id,
                candidate_name,
            )
        except Exception as exc:
            logger.warning(
                "[%s::%s] decision_store_log_failed: %s",
                correlation_id,
                candidate_name,
                exc,
                exc_info=True,
            )

        try:
            logger.info(
                "[%s::%s] recruiter_dashboard_updating",
                correlation_id,
                candidate_name,
            )
            self._update_recruiter_dashboard_row(
                role=role,
                candidate_name=candidate_name,
                candidate_folder_id=candidate_folder_id,
                evaluation=evaluation,
                result=result,
                pipeline_decision=pipeline_recommendation,
                hold_reason_code=hold_reason_code,
                hold_type=hold_type,
                bundle_meta=bundle_meta,
                correlation_id=correlation_id,
            )
            logger.info(
                "[%s::%s] recruiter_dashboard_row_updated",
                correlation_id,
                candidate_name,
            )
        except Exception as exc:
            logger.warning(
                "[%s::%s] recruiter_dashboard_upsert_failed: %s",
                correlation_id,
                candidate_name,
                exc,
                exc_info=True,
            )

    def _route_candidate(
        self,
        recommendation: str,
        folder_id: str,
        role: str,
        folder_name: str,
        correlation_id: str,
    ) -> None:
        if recommendation == "SEND_TO_L2":
            target_folder = get_l2_folder(role)
            if not target_folder:
                logger.error(
                    "l2_folder_missing",
                    extra={
                        "correlation_id": correlation_id,
                        "role": role,
                        "candidate_name": folder_name,
                    },
                )
                return
            self.drive.move_folder(folder_id, target_folder)
            logger.info(
                "candidate_moved_to_l2",
                extra={
                    "correlation_id": correlation_id,
                    "candidate_name": folder_name,
                    "role": role,
                },
            )
            return

        if recommendation == "REJECT_AT_L1":
            target_folder = get_reject_folder(role)
            if not target_folder:
                logger.error(
                    "reject_folder_missing",
                    extra={
                        "correlation_id": correlation_id,
                        "role": role,
                        "candidate_name": folder_name,
                    },
                )
                return
            self.drive.move_folder(folder_id, target_folder)
            logger.info(
                "candidate_moved_to_l1_reject",
                extra={
                    "correlation_id": correlation_id,
                    "candidate_name": folder_name,
                    "role": role,
                },
            )
            return

        if recommendation == "HOLD":
            self._write_status_file(
                folder_id,
                self.STATUS_EVALUATION_HOLD,
                "Awaiting recruiter review",
                correlation_id,
            )
            logger.info(
                "candidate_on_hold",
                extra={
                    "correlation_id": correlation_id,
                    "candidate_name": folder_name,
                    "role": role,
                },
            )

    @staticmethod
    def _map_recommendation(final_decision: str) -> str:
        mapping = {
            "MOVE_TO_L2": "SEND_TO_L2",
            "SEND_TO_L2": "SEND_TO_L2",
            "REJECT": "REJECT_AT_L1",
            "REJECT_AT_L1": "REJECT_AT_L1",
            "HOLD": "HOLD",
        }
        return mapping.get(final_decision, "HOLD")

    def _candidate_folder_link(self, candidate_folder_id: str) -> str:
        return f"https://drive.google.com/drive/folders/{candidate_folder_id}"

    def _build_dashboard_link(self, role: str) -> Optional[str]:
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
        hold_type: Optional[str],
        hold_reason: Optional[str] = None,
        candidate_folder_id: str,
        feedback_link: Optional[str] = None,
        dashboard_link: Optional[str] = None,
    ) -> None:
        normalized_decision = (decision or "").lower() or self.DECISION_HOLD
        folder_link = self._candidate_folder_link(candidate_folder_id)
        dashboard_link = dashboard_link or self._build_dashboard_link(role)
        resolved_hold_reason_code = hold_reason or self._resolve_hold_reason_code(hold_type)
        resolved_reason = reason or self._resolve_hold_reason_label(hold_type)
        self.summary.candidates.append(
            L1CandidateResult(
                candidate_name=candidate_name,
                role=role,
                decision=normalized_decision,
                reason=resolved_reason,
                hold_type=hold_type,
                hold_reason=resolved_hold_reason_code,
                folder_link=folder_link,
                feedback_link=feedback_link,
                dashboard_link=dashboard_link,
            )
        )

        if normalized_decision == self.DECISION_MOVE_TO_L2:
            self.summary.moved_to_l2 += 1
        elif normalized_decision == self.DECISION_REJECT:
            self.summary.rejected_at_l1 += 1
        elif normalized_decision == self.DECISION_HOLD:
            self.summary.hold_decisions += 1
            if resolved_hold_reason_code == self.HOLD_REASON_CODE_MANUAL_REVIEW:
                self.summary.needs_manual_review += 1
            elif resolved_hold_reason_code == self.HOLD_REASON_CODE_BACKUP:
                self.summary.hold_backup_pool += 1
            if hold_type == self.HOLD_REASON_MISSING_TRANSCRIPT:
                self.summary.hold_missing_transcript += 1
                self.summary.on_hold_missing_transcript += 1
            elif hold_type == self.HOLD_REASON_DATA_INCOMPLETE:
                self.summary.hold_data_incomplete += 1
            elif hold_type == self.HOLD_REASON_LOW_CONFIDENCE:
                self.summary.hold_low_confidence += 1
            elif hold_type == self.HOLD_REASON_AMBIGUOUS:
                self.summary.hold_ambiguous += 1
            elif hold_type == self.HOLD_REASON_JD_MISMATCH:
                self.summary.hold_jd_mismatch += 1
            if hold_type == self.HOLD_REASON_DATA_INCOMPLETE:
                self.summary.data_incomplete += 1

    def _resolve_hold_reason_label(
        self,
        hold_type: Optional[str],
        fallback_reason: Optional[str],
    ) -> Optional[str]:
        mapping = {
            self.HOLD_REASON_MISSING_TRANSCRIPT: "Missing transcript",
            self.HOLD_REASON_DATA_INCOMPLETE: "Data incomplete",
            self.HOLD_REASON_LOW_CONFIDENCE: "Model low confidence",
            self.HOLD_REASON_AMBIGUOUS: "Ambiguous evaluation signals",
            self.HOLD_REASON_JD_MISMATCH: "JD mismatch",
        }
        if hold_type and hold_type in mapping:
            return mapping[hold_type]
        return fallback_reason

    def _resolve_hold_reason_code(self, hold_type: Optional[str]) -> Optional[str]:
        mapping = {
            self.HOLD_REASON_MISSING_TRANSCRIPT: self.HOLD_REASON_CODE_MISSING_INFO,
            self.HOLD_REASON_DATA_INCOMPLETE: self.HOLD_REASON_CODE_MISSING_INFO,
            self.HOLD_REASON_LOW_CONFIDENCE: self.HOLD_REASON_CODE_MANUAL_REVIEW,
            self.HOLD_REASON_AMBIGUOUS: self.HOLD_REASON_CODE_MANUAL_REVIEW,
            self.HOLD_REASON_JD_MISMATCH: self.HOLD_REASON_CODE_MANUAL_REVIEW,
            self.HOLD_REASON_CAPACITY: self.HOLD_REASON_CODE_BACKUP,
        }
        if hold_type and hold_type in mapping:
            return mapping[hold_type]
        return None

    def _describe_hold_reason_for_sheet(
        self,
        hold_reason_code: Optional[str],
        hold_type: Optional[str],
        fallback_detail: Optional[str],
    ) -> Optional[str]:
        if hold_reason_code == self.HOLD_REASON_CODE_BACKUP:
            return "Hold – backup for L2 capacity"

        if hold_reason_code == self.HOLD_REASON_CODE_MISSING_INFO:
            if hold_type == self.HOLD_REASON_MISSING_TRANSCRIPT:
                return "Hold – missing L1 transcript"
            if hold_type == self.HOLD_REASON_DATA_INCOMPLETE:
                return "Hold – missing required documents"
            return "Hold – missing information"

        if hold_reason_code == self.HOLD_REASON_CODE_MANUAL_REVIEW:
            if hold_type == self.HOLD_REASON_LOW_CONFIDENCE:
                return "Hold – manual review (low confidence)"
            if hold_type == self.HOLD_REASON_AMBIGUOUS:
                return "Hold – manual review (ambiguous signals)"
            if hold_type == self.HOLD_REASON_JD_MISMATCH:
                return "Hold – JD alignment uncertain"
            return "Hold – manual review required"

        return fallback_detail

    def _should_limit_creamy_layer(self, evaluated_so_far: int) -> bool:
        total_evaluated = evaluated_so_far + 1
        if total_evaluated < 5:
            return False
        projected_ratio = (self.summary.moved_to_l2 + 1) / max(1, total_evaluated)
        return projected_ratio > self.CREAMY_LAYER_CAP

    def _has_keywords(self, text: Optional[str], keywords: List[str]) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return any(keyword in lowered for keyword in keywords)

    def _detect_missing_jd_skills(self, evaluation: L1Evaluation, result, bundle: RivaFileBundle) -> bool:
        phrases = (evaluation.weaknesses or []) + (evaluation.risk_flags or []) + (result.concerns or [])
        for item in phrases:
            if self._has_keywords(item, ["missing", "skill"]):
                return True
        meta = getattr(bundle, "meta", None)
        if isinstance(meta, dict):
            missing = meta.get("missing_critical_skills")
            if isinstance(missing, list) and missing:
                return True
        return False

    def _transcript_too_short(self, transcript_text: Optional[str]) -> bool:
        if not transcript_text:
            return False
        non_empty_lines = [line for line in transcript_text.splitlines() if line.strip()]
        return len(non_empty_lines) < 100

    def _low_communication(self, evaluation: L1Evaluation, result) -> bool:
        if self._has_keywords(result.communication_signals, ["weak", "poor", "unclear", "limited", "needs improvement"]):
            return True
        for weakness in evaluation.weaknesses or []:
            if self._has_keywords(weakness, ["communication", "clarity"]):
                return True
        return False

    def _ambiguous_signals(self, evaluation: L1Evaluation) -> bool:
        return bool(evaluation.strengths and evaluation.weaknesses and len(evaluation.strengths) >= 2 and len(evaluation.weaknesses) >= 2)

    def _alignment_uncertain(self, evaluation: L1Evaluation) -> bool:
        items = (evaluation.weaknesses or []) + (evaluation.risk_flags or [])
        for entry in items:
            if self._has_keywords(entry, ["alignment", "jd", "role fit"]):
                return True
        return False

    def _determine_pipeline_decision(
        self,
        *,
        evaluation: L1Evaluation,
        result,
        bundle: RivaFileBundle,
        evaluated_so_far: int,
    ) -> Tuple[str, str, Optional[str]]:
        # Use the new deterministic decision engine
        outcome = decide_l1_outcome(result.model_dump())

        if outcome == "MOVE_TO_L2":
            if self._should_limit_creamy_layer(evaluated_so_far):
                return "HOLD", "Hold for backup pool (capacity limit)", self.HOLD_REASON_CAPACITY
            return "SEND_TO_L2", "Model confident pass", None

        if outcome == "REJECT_AT_L1":
            reason = "Low overall alignment"
            # If we have specific risk flags, use them for the reason
            if result.risk_flags:
                reason = f"Rejected: {', '.join(result.risk_flags[:2])}"
            elif result.concerns:
                reason = f"Rejected: {', '.join(result.concerns[:2])}"
            return "REJECT_AT_L1", reason, None

        if outcome == "HOLD_DATA_INCOMPLETE":
            return "HOLD", "Data incomplete", self.HOLD_REASON_DATA_INCOMPLETE

        # Fallback for HOLD_MANUAL_REVIEW
        # We map this to AMBIGUOUS to trigger the manual review flow
        return "HOLD", "Manual review required", self.HOLD_REASON_AMBIGUOUS

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
            self.drive.write_json_file(
                folder_id,
                self.STATUS_FILENAME,
                payload,
            )
        except Exception as exc:
            logger.warning(
                "status_file_write_failed",
                extra={
                    "correlation_id": correlation_id,
                    "folder_id": folder_id,
                    "status": status,
                    "error": str(exc),
                },
                exc_info=True,
            )
