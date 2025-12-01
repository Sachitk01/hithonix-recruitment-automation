from evaluation_models import CandidateEvent, CandidateProfile, RoleProfile
from memory_service import MemoryService


def build_memory_service() -> MemoryService:
    return MemoryService(db_url="sqlite:///:memory:", enabled=True)


def test_candidate_profile_upsert_and_fetch():
    service = build_memory_service()
    profile = CandidateProfile(
        candidate_id="folder-1",
        name="Alice",
        role="Product Manager",
        skills={"strengths": ["Strategy"]},
        experience_years=5.0,
        final_outcome="unknown",
    )
    service.upsert_candidate_profile(profile)

    fetched = service.get_candidate_profile("folder-1")
    assert fetched is not None
    assert fetched.name == "Alice"
    assert fetched.skills["strengths"] == ["Strategy"]


def test_candidate_event_deduplication():
    service = build_memory_service()
    event = CandidateEvent(
        candidate_id="folder-2",
        run_id="run-123",
        stage="L1",
        agent="riva",
        inputs_hash="abc",
        scores={"overall_fit": 4.2},
        decision="pass",
        confidence=0.9,
        artifacts={"result": "l1_result.json"},
    )
    service.append_candidate_event(event)
    # duplicate should be ignored
    service.append_candidate_event(event)

    events = service.get_candidate_events("folder-2")
    assert len(events) == 1
    assert events[0].scores["overall_fit"] == 4.2


def test_role_profile_upsert():
    service = build_memory_service()
    profile = RoleProfile(
        role="Engineering Manager",
        rubric_version="v2",
        competency_weights={"leadership": 0.6},
        common_rejection_reasons=["Communication"],
        top_performer_patterns=["Ownership"],
        notes="Initial seed",
    )
    service.upsert_role_profile(profile)

    fetched = service.get_role_profile("Engineering Manager")
    assert fetched is not None
    assert fetched.rubric_version == "v2"