# arjun_l2_models.py

from pydantic import BaseModel, Field
from typing import List, Optional


class ArjunL2Result(BaseModel):
    leadership_assessment: str
    technical_capability: str
    communication_depth: str
    culture_alignment: str
    career_potential: str
    strengths: List[str] = Field(default_factory=list)
    concerns: List[str] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)
    final_score: int
    final_recommendation: str
    l2_summary: str
    rationale: str


class L2CandidateResult(BaseModel):
    candidate_name: str
    role: str
    decision: str  # shortlist | reject | hold
    reason: Optional[str] = None
    hold_type: Optional[str] = None
    hold_reason: Optional[str] = None
    folder_link: Optional[str] = None
    feedback_link: Optional[str] = None
    dashboard_link: Optional[str] = None
    risk_flags: List[str] = Field(default_factory=list)


class L2BatchSummary(BaseModel):
    total_seen: int = 0
    evaluated: int = 0
    hires: int = 0
    rejects: int = 0
    needs_manual_review: int = 0
    hold_decisions: int = 0
    hold_backup_pool: int = 0
    on_hold_missing_l2_transcript: int = 0
    data_incomplete: int = 0
    skipped_no_l2: int = 0
    errors: int = 0
    candidates: List[L2CandidateResult] = Field(default_factory=list)

    def to_logging_dict(self) -> dict:
        return self.model_dump()
