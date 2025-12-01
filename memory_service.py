# memory_service.py
"""
Talent Intelligence Memory Layer for persistent candidate and role memory.
Provides context across evaluation runs for Riva (L1) and Arjun (L2).
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    DateTime,
    Text,
    JSON,
    create_engine,
    Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from evaluation_models import (
    CandidateProfile as CandidateProfileModel,
    CandidateEvent as CandidateEventModel,
    RoleProfile as RoleProfileModel,
)
from memory_config import MEMORY_DB_URL, is_memory_enabled

logger = logging.getLogger(__name__)

Base = declarative_base()


# SQLAlchemy ORM Models

class DBCandidateProfile(Base):
    """Database model for candidate profiles."""
    
    __tablename__ = "candidate_profiles"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    role = Column(String(255), nullable=False)
    skills = Column(JSON, default=dict)
    experience_years = Column(Float, nullable=True)
    final_outcome = Column(String(50), default="unknown")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class DBCandidateEvent(Base):
    """Database model for candidate evaluation events."""
    
    __tablename__ = "candidate_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(255), nullable=False, index=True)
    run_id = Column(String(255), nullable=False, index=True)
    stage = Column(String(10), nullable=False)  # L1 or L2
    agent = Column(String(50), nullable=False)  # riva or arjun
    inputs_hash = Column(String(64), nullable=True)
    scores = Column(JSON, default=dict)
    decision = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=False)
    artifacts = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    
    __table_args__ = (
        Index('idx_candidate_stage', 'candidate_id', 'stage'),
        Index('idx_run_candidate', 'run_id', 'candidate_id'),
    )


class DBRoleProfile(Base):
    """Database model for role profiles."""
    
    __tablename__ = "role_profiles"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    role = Column(String(255), unique=True, nullable=False, index=True)
    rubric_version = Column(String(50), default="v1.0")
    competency_weights = Column(JSON, default=dict)
    common_rejection_reasons = Column(JSON, default=list)
    top_performer_patterns = Column(JSON, default=list)
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class DBDecisionOverride(Base):
    """Database model for manual decision overrides."""
    
    __tablename__ = "decision_overrides"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(255), nullable=False, index=True)
    stage = Column(String(10), nullable=False)
    from_decision = Column(String(50), nullable=False)
    to_decision = Column(String(50), nullable=False)
    reason = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DBEvaluation(Base):
    """Database model for detailed evaluation logs."""
    
    __tablename__ = "evaluations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id = Column(String(255), nullable=False, index=True)
    stage = Column(String(10), nullable=False)  # L1 or L2
    engine = Column(String(50), nullable=False)  # RIVA or ARJUN
    scores = Column(JSON, default=dict)
    risk_flags = Column(JSON, default=list)
    reason_codes = Column(JSON, default=list)
    raw_recommendation = Column(String(50), nullable=True)
    decision_outcome = Column(String(50), nullable=False)
    prompt_version = Column(String(50), nullable=True)
    decision_logic_version = Column(String(50), nullable=True)
    model_version = Column(String(50), nullable=True)
    debug_payload_uri = Column(String(1024), nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    
    __table_args__ = (
        Index('idx_eval_candidate', 'candidate_id', 'stage'),
    )


class DBAuditLog(Base):
    """Database model for system audit logs."""
    
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor = Column(String(100), nullable=False)
    action = Column(String(100), nullable=False)
    from_state = Column(String(100), nullable=True)
    to_state = Column(String(100), nullable=True)
    metadata_ = Column("metadata", JSON, default=dict) # 'metadata' is reserved in Base
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


# Memory Service

class MemoryService:
    """
    Persistent memory service for candidate and role intelligence.
    Enables context-aware evaluations across runs.
    """
    
    def __init__(self, db_url: Optional[str] = None, enabled: bool = True):
        """
        Initialize memory service.
        
        Args:
            db_url: Database connection URL (defaults to SQLite in repo root)
            enabled: Whether memory is enabled
        """
        self.enabled = enabled
        
        if not enabled:
            logger.info("Memory service initialized in DISABLED mode")
            self.engine = None
            self.SessionLocal = None
            return
        
        # Default to SQLite if not specified
        if not db_url:
            db_url = MEMORY_DB_URL
        
        self.engine = create_engine(db_url, echo=False, future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        
        # Create tables if they don't exist
        Base.metadata.create_all(self.engine)
        
        logger.info(f"Memory service initialized with database: {db_url}")
    
    def _get_session(self) -> Optional[Session]:
        """Get database session if enabled."""
        if not self.enabled or not self.SessionLocal:
            return None
        return self.SessionLocal()
    
    # Candidate Profile Methods
    
    def get_candidate_profile(self, candidate_id: str) -> Optional[CandidateProfileModel]:
        """
        Retrieve candidate profile by ID.
        
        Args:
            candidate_id: Google Drive folder ID
            
        Returns:
            CandidateProfile or None if not found
        """
        if not self.enabled:
            return None
        
        session = self._get_session()
        if not session:
            return None
        
        try:
            db_profile = session.query(DBCandidateProfile).filter_by(candidate_id=candidate_id).first()
            
            if not db_profile:
                return None
            
            return CandidateProfileModel(
                candidate_id=db_profile.candidate_id,
                name=db_profile.name,
                role=db_profile.role,
                skills=db_profile.skills or {},
                experience_years=db_profile.experience_years,
                final_outcome=db_profile.final_outcome,
            )
        except Exception as e:
            logger.error(f"Error retrieving candidate profile {candidate_id}: {e}", exc_info=True)
            return None
        finally:
            session.close()
    
    def upsert_candidate_profile(self, profile: CandidateProfileModel) -> None:
        """
        Create or update candidate profile.
        
        Args:
            profile: CandidateProfile to save
        """
        if not self.enabled:
            return
        
        session = self._get_session()
        if not session:
            return
        
        try:
            db_profile = session.query(DBCandidateProfile).filter_by(
                candidate_id=profile.candidate_id
            ).first()
            
            if db_profile:
                # Update existing
                db_profile.name = profile.name
                db_profile.role = profile.role
                db_profile.skills = profile.skills
                db_profile.experience_years = profile.experience_years
                db_profile.final_outcome = profile.final_outcome
                db_profile.updated_at = datetime.now(timezone.utc)
            else:
                # Create new
                db_profile = DBCandidateProfile(
                    candidate_id=profile.candidate_id,
                    name=profile.name,
                    role=profile.role,
                    skills=profile.skills,
                    experience_years=profile.experience_years,
                    final_outcome=profile.final_outcome,
                )
                session.add(db_profile)
            
            session.commit()
            logger.info(f"Upserted candidate profile: {profile.candidate_id}")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error upserting candidate profile {profile.candidate_id}: {e}", exc_info=True)
        finally:
            session.close()
    
    # Candidate Event Methods
    
    def append_candidate_event(self, event: CandidateEventModel) -> None:
        """
        Append a new evaluation event for a candidate.
        
        Args:
            event: CandidateEvent to record
        """
        if not self.enabled:
            return
        
        session = self._get_session()
        if not session:
            return
        
        try:
            # Check for duplicate run_id + candidate_id (idempotency)
            existing = session.query(DBCandidateEvent).filter_by(
                run_id=event.run_id,
                candidate_id=event.candidate_id,
                stage=event.stage
            ).first()
            
            if existing:
                logger.warning(f"Event already exists for run_id={event.run_id}, candidate={event.candidate_id}, stage={event.stage}")
                return
            
            db_event = DBCandidateEvent(
                candidate_id=event.candidate_id,
                run_id=event.run_id,
                stage=event.stage,
                agent=event.agent,
                inputs_hash=event.inputs_hash,
                scores=event.scores,
                decision=event.decision,
                confidence=event.confidence,
                artifacts=event.artifacts,
            )
            
            session.add(db_event)
            session.commit()
            logger.info(f"Appended event: stage={event.stage}, candidate={event.candidate_id}")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error appending candidate event: {e}", exc_info=True)
        finally:
            session.close()
    
    def get_candidate_events(
        self,
        candidate_id: str,
        stage: Optional[str] = None,
        limit: int = 10
    ) -> List[CandidateEventModel]:
        """
        Get recent events for a candidate.
        
        Args:
            candidate_id: Candidate Drive folder ID
            stage: Filter by stage (L1 or L2), optional
            limit: Maximum number of events to return
            
        Returns:
            List of CandidateEvents, most recent first
        """
        if not self.enabled:
            return []
        
        session = self._get_session()
        if not session:
            return []
        
        try:
            query = session.query(DBCandidateEvent).filter_by(candidate_id=candidate_id)
            
            if stage:
                query = query.filter_by(stage=stage.upper())
            
            db_events = query.order_by(DBCandidateEvent.timestamp.desc()).limit(limit).all()
            
            return [
                CandidateEventModel(
                    candidate_id=e.candidate_id,
                    run_id=e.run_id,
                    stage=e.stage,
                    agent=e.agent,
                    inputs_hash=e.inputs_hash,
                    scores=e.scores or {},
                    decision=e.decision,
                    confidence=e.confidence,
                    artifacts=e.artifacts or {},
                )
                for e in db_events
            ]
            
        except Exception as e:
            logger.error(f"Error retrieving candidate events: {e}", exc_info=True)
            return []
        finally:
            session.close()
    
    # Role Profile Methods
    
    def get_role_profile(self, role: str) -> Optional[RoleProfileModel]:
        """
        Retrieve role profile.
        
        Args:
            role: Role name
            
        Returns:
            RoleProfile or None if not found
        """
        if not self.enabled:
            return None
        
        session = self._get_session()
        if not session:
            return None
        
        try:
            db_role = session.query(DBRoleProfile).filter_by(role=role).first()
            
            if not db_role:
                return None
            
            return RoleProfileModel(
                role=db_role.role,
                rubric_version=db_role.rubric_version,
                competency_weights=db_role.competency_weights or {},
                common_rejection_reasons=db_role.common_rejection_reasons or [],
                top_performer_patterns=db_role.top_performer_patterns or [],
                notes=db_role.notes,
            )
            
        except Exception as e:
            logger.error(f"Error retrieving role profile {role}: {e}", exc_info=True)
            return None
        finally:
            session.close()
    
    def upsert_role_profile(self, profile: RoleProfileModel) -> None:
        """
        Create or update role profile.
        
        Args:
            profile: RoleProfile to save
        """
        if not self.enabled:
            return
        
        session = self._get_session()
        if not session:
            return
        
        try:
            db_role = session.query(DBRoleProfile).filter_by(role=profile.role).first()
            
            if db_role:
                # Update existing
                db_role.rubric_version = profile.rubric_version
                db_role.competency_weights = profile.competency_weights
                db_role.common_rejection_reasons = profile.common_rejection_reasons
                db_role.top_performer_patterns = profile.top_performer_patterns
                db_role.notes = profile.notes
                db_role.updated_at = datetime.now(timezone.utc)
            else:
                # Create new
                db_role = DBRoleProfile(
                    role=profile.role,
                    rubric_version=profile.rubric_version,
                    competency_weights=profile.competency_weights,
                    common_rejection_reasons=profile.common_rejection_reasons,
                    top_performer_patterns=profile.top_performer_patterns,
                    notes=profile.notes,
                )
                session.add(db_role)
            
            session.commit()
            logger.info(f"Upserted role profile: {profile.role}")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error upserting role profile {profile.role}: {e}", exc_info=True)
        finally:
            session.close()
    
    # Decision Override Methods
    
    def log_override(
        self,
        candidate_id: str,
        stage: str,
        from_decision: str,
        to_decision: str,
        reason: str
    ) -> None:
        """
        Log a manual decision override.
        
        Args:
            candidate_id: Candidate Drive folder ID
            stage: L1 or L2
            from_decision: Original AI decision
            to_decision: Manual override decision
            reason: Reason for override
        """
        if not self.enabled:
            return
        
        session = self._get_session()
        if not session:
            return
        
        try:
            override = DBDecisionOverride(
                candidate_id=candidate_id,
                stage=stage.upper(),
                from_decision=from_decision,
                to_decision=to_decision,
                reason=reason,
            )
            
            session.add(override)
            session.commit()
            logger.info(f"Logged override: {candidate_id} {stage} {from_decision}->{to_decision}")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error logging override: {e}", exc_info=True)
        finally:
            session.close()

    # Logging Methods

    def log_evaluation(self, evaluation_data: Dict[str, Any]) -> None:
        """
        Log a detailed evaluation record.
        
        Args:
            evaluation_data: Dictionary matching DBEvaluation fields
        """
        if not self.enabled:
            return
        
        session = self._get_session()
        if not session:
            return
        
        try:
            db_eval = DBEvaluation(
                candidate_id=evaluation_data["candidate_id"],
                stage=evaluation_data["stage"],
                engine=evaluation_data["engine"],
                scores=evaluation_data.get("scores", {}),
                risk_flags=evaluation_data.get("risk_flags", []),
                reason_codes=evaluation_data.get("reason_codes", []),
                raw_recommendation=evaluation_data.get("raw_recommendation"),
                decision_outcome=evaluation_data["decision_outcome"],
                prompt_version=evaluation_data.get("prompt_version"),
                decision_logic_version=evaluation_data.get("decision_logic_version"),
                model_version=evaluation_data.get("model_version"),
                debug_payload_uri=evaluation_data.get("debug_payload_uri"),
            )
            
            session.add(db_eval)
            session.commit()
            logger.info(f"Logged evaluation: {evaluation_data['candidate_id']} {evaluation_data['stage']}")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error logging evaluation: {e}", exc_info=True)
        finally:
            session.close()

    def log_audit_event(
        self,
        actor: str,
        action: str,
        from_state: Optional[str] = None,
        to_state: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log a system audit event.
        
        Args:
            actor: Who performed the action (Riva, Arjun, User)
            action: What happened
            from_state: Previous state (optional)
            to_state: New state (optional)
            metadata: Additional context
        """
        if not self.enabled:
            return
        
        session = self._get_session()
        if not session:
            return
        
        try:
            audit = DBAuditLog(
                actor=actor,
                action=action,
                from_state=from_state,
                to_state=to_state,
                metadata_=metadata or {},
            )
            
            session.add(audit)
            session.commit()
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error logging audit event: {e}", exc_info=True)
        finally:
            session.close()
    
    # Utility Methods
    
    @staticmethod
    def compute_inputs_hash(inputs: Dict) -> str:
        """
        Compute a hash of evaluation inputs for deduplication.
        
        Args:
            inputs: Dictionary of input data
            
        Returns:
            SHA-256 hash string
        """
        serialized = json.dumps(inputs, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()


# Global instance

_memory_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    """Get global memory service instance (lazy initialization)."""
    global _memory_service
    
    if _memory_service is None:
        enabled = is_memory_enabled()
        db_url = MEMORY_DB_URL
        try:
            _memory_service = MemoryService(db_url=db_url, enabled=enabled)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error(
                "memory_service_init_failed",
                extra={"error": str(exc), "db_url": db_url},
            )
            _memory_service = MemoryService(db_url=db_url, enabled=False)
    
    return _memory_service
