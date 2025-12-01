# evaluation_models.py
"""
Standardized Pydantic models for L1 and L2 evaluation outputs.
These ensure consistency and validation before writing to Drive/Sheets/Memory.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class L1Evaluation(BaseModel):
    """Standardized L1 (Riva) evaluation output."""
    
    candidate_id: str = Field(..., description="Google Drive folder ID")
    role: str = Field(..., description="Role being evaluated for")
    scores: Dict[str, float] = Field(default_factory=dict, description="Competency scores (0-5)")
    strengths: List[str] = Field(default_factory=list, description="Identified strengths")
    weaknesses: List[str] = Field(default_factory=list, description="Identified weaknesses")
    risk_flags: List[str] = Field(default_factory=list, description="Red flags or concerns")
    recommendation: str = Field(..., description="pass | reject | hold")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0-1)")
    feedback_link: Optional[str] = Field(None, description="Link to feedback document")
    report_link: Optional[str] = Field(None, description="Link to evaluation report")
    
    @field_validator('recommendation')
    @classmethod
    def validate_recommendation(cls, v: str) -> str:
        allowed = {'pass', 'reject', 'hold'}
        if v.lower() not in allowed:
            raise ValueError(f"recommendation must be one of {allowed}, got {v}")
        return v.lower()


class L2Evaluation(BaseModel):
    """Standardized L2 (Arjun) evaluation output."""
    
    candidate_id: str = Field(..., description="Google Drive folder ID")
    role: str = Field(..., description="Role being evaluated for")
    scores: Dict[str, float] = Field(default_factory=dict, description="Competency scores (0-5)")
    strengths: List[str] = Field(default_factory=list, description="Identified strengths")
    weaknesses: List[str] = Field(default_factory=list, description="Identified weaknesses")
    risk_flags: List[str] = Field(default_factory=list, description="Red flags or concerns")
    recommendation: str = Field(..., description="strong_yes | yes | lean_yes | lean_no | no")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0-1)")
    alignment_with_l1: str = Field(default="unknown", description="high | medium | low | unknown")
    feedback_link: Optional[str] = Field(None, description="Link to feedback document")
    report_link: Optional[str] = Field(None, description="Link to evaluation report")
    
    @field_validator('recommendation')
    @classmethod
    def validate_recommendation(cls, v: str) -> str:
        allowed = {'strong_yes', 'yes', 'lean_yes', 'lean_no', 'no'}
        if v.lower() not in allowed:
            raise ValueError(f"recommendation must be one of {allowed}, got {v}")
        return v.lower()
    
    @field_validator('alignment_with_l1')
    @classmethod
    def validate_alignment(cls, v: str) -> str:
        allowed = {'high', 'medium', 'low', 'unknown'}
        if v.lower() not in allowed:
            raise ValueError(f"alignment_with_l1 must be one of {allowed}, got {v}")
        return v.lower()


# Memory layer Pydantic models

class CandidateProfile(BaseModel):
    """Candidate profile for memory layer."""
    
    candidate_id: str = Field(..., description="Google Drive folder ID (unique)")
    name: str = Field(..., description="Candidate name")
    role: str = Field(..., description="Role")
    skills: Dict[str, Any] = Field(default_factory=dict, description="Skills metadata")
    experience_years: Optional[float] = Field(None, description="Years of experience")
    final_outcome: str = Field(default="unknown", description="shortlisted | rejected | joined | unknown")
    
    @field_validator('final_outcome')
    @classmethod
    def validate_outcome(cls, v: str) -> str:
        allowed = {'shortlisted', 'rejected', 'joined', 'unknown', 'on_hold'}
        if v.lower() not in allowed:
            raise ValueError(f"final_outcome must be one of {allowed}, got {v}")
        return v.lower()


class CandidateEvent(BaseModel):
    """Event record for candidate evaluation."""
    
    candidate_id: str = Field(..., description="Google Drive folder ID")
    run_id: str = Field(..., description="UUID for this batch run")
    stage: str = Field(..., description="L1 or L2")
    agent: str = Field(..., description="riva or arjun")
    inputs_hash: Optional[str] = Field(None, description="Hash of core inputs")
    scores: Dict[str, float] = Field(default_factory=dict, description="Evaluation scores")
    decision: str = Field(..., description="pass | reject | hold")
    hold_reason: Optional[str] = Field(None, description="manual_review_required | backup_for_l2_capacity | missing_noncritical_info")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence (0-1)")
    artifacts: Dict[str, str] = Field(default_factory=dict, description="Links to Drive artifacts")
    
    @field_validator('stage')
    @classmethod
    def validate_stage(cls, v: str) -> str:
        if v.upper() not in {'L1', 'L2'}:
            raise ValueError(f"stage must be L1 or L2, got {v}")
        return v.upper()
    
    @field_validator('agent')
    @classmethod
    def validate_agent(cls, v: str) -> str:
        if v.lower() not in {'riva', 'arjun'}:
            raise ValueError(f"agent must be riva or arjun, got {v}")
        return v.lower()

    @field_validator('decision')
    @classmethod
    def validate_decision(cls, v: str) -> str:
        allowed = {'pass', 'reject', 'hold'}
        if v.lower() not in allowed:
            raise ValueError(f"decision must be one of {allowed}, got {v}")
        return v.lower()


class RoleProfile(BaseModel):
    """Role profile for memory layer."""
    
    role: str = Field(..., description="Role name (unique)")
    rubric_version: str = Field(default="v1.0", description="Rubric version")
    competency_weights: Dict[str, float] = Field(default_factory=dict, description="Competency -> weight")
    common_rejection_reasons: List[str] = Field(default_factory=list, description="Common rejection patterns")
    top_performer_patterns: List[str] = Field(default_factory=list, description="Top performer characteristics")
    notes: Optional[str] = Field(None, description="Additional notes")
