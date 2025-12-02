# riva_l1_models.py

from pydantic import BaseModel, Field
from typing import List, Optional


class RivaL1Result(BaseModel):
    match_summary: str
    strengths: List[str]
    concerns: List[str]
    behavioral_signals: str
    communication_signals: str
    red_flags: List[str]
    risk_flags: List[str] = Field(default_factory=list)
    compensation_alignment: str
    joining_feasibility: str
    fit_score: int
    final_decision: str


class L1CandidateResult(BaseModel):
    candidate_name: str
    role: str
    decision: str  # move_to_l2 | reject | hold
    reason: Optional[str] = None
    hold_type: Optional[str] = None  # legacy enums for granular reporting
    hold_reason: Optional[str] = None  # manual_review_required | backup_for_l2_capacity | missing_noncritical_info
    folder_link: Optional[str] = None
    feedback_link: Optional[str] = None
    dashboard_link: Optional[str] = None
    risk_flags: List[str] = Field(default_factory=list)


class L1BatchError(BaseModel):
    candidate_name: Optional[str] = None
    role: Optional[str] = None
    folder_id: Optional[str] = None
    error_code: str
    error_message: str
    technical_detail: Optional[str] = None


class L1BatchSummary(BaseModel):
    total_seen: int = 0
    evaluated: int = 0
    moved_to_l2: int = 0
    rejected_at_l1: int = 0
    needs_manual_review: int = 0
    hold_decisions: int = 0
    hold_backup_pool: int = 0
    hold_missing_transcript: int = 0
    on_hold_missing_transcript: int = 0
    hold_data_incomplete: int = 0
    hold_low_confidence: int = 0
    hold_ambiguous: int = 0
    hold_jd_mismatch: int = 0
    data_incomplete: int = 0
    errors: List[L1BatchError] = Field(default_factory=list)
    candidates: List[L1CandidateResult] = Field(default_factory=list)

    def to_logging_dict(self) -> dict:
        return self.model_dump()

    @property
    def error_count(self) -> int:
        return len(self.errors)
