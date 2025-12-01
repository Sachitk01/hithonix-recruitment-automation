import types
import pytest
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import arjun_chat_handler
from arjun_chat_handler import ArjunChatHandler, matches_l2_snapshot_status
from arjun_l2.arjun_l2_models import L2BatchSummary, L2CandidateResult
from candidate_service import CandidateSnapshot
from chat_intents import WorkIntentType
from summary_store import SummaryStore


class DummyLLMClient:
    def __init__(self, response_text: str = "Structured response"):
        self.response_text = response_text
        self.requests = []
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content=self.response_text)
                )
            ]
        )


def make_snapshot(
    *,
    name: str,
    role: str,
    stage: str,
    ai_status: str,
    l1_outcome: str = "",
    l2_outcome: str = "",
    next_action: str = "",
    final_decision: Optional[str] = None,
    source: str = "test",
    updated_at: Optional[datetime] = None,
) -> CandidateSnapshot:
    return CandidateSnapshot(
        candidate_name=name,
        role=role,
        current_stage=stage,
        ai_status=ai_status,
        l1_outcome=l1_outcome or None,
        l2_outcome=l2_outcome or None,
        final_decision=final_decision,
        next_action=next_action or None,
        updated_at=updated_at or datetime.now(timezone.utc),
        source=source,
    )


class SnapshotServiceStub:
    def __init__(
        self,
        mapping: Dict[Tuple[str, str], CandidateSnapshot],
        *,
        all_snapshots: Optional[List[CandidateSnapshot]] = None,
    ):
        self.mapping = {
            (name.lower(), role.lower()): snapshot
            for (name, role), snapshot in mapping.items()
        }
        self.latest_calls: List[Tuple[str, str, bool]] = []
        self.record_calls: List[Tuple[str, str]] = []
        self.fuzzy_calls: List[Tuple[str, str]] = []
        self.all_calls: List[Optional[str]] = []
        self._all_snapshots = all_snapshots or list(mapping.values())

    def get_latest_candidate_snapshot(self, candidate_name, role_name, *, allow_fuzzy=False):
        key = ((candidate_name or "").lower(), (role_name or "").lower())
        self.latest_calls.append((candidate_name, role_name, allow_fuzzy))
        return self.mapping.get(key)

    def get_candidate_record(self, candidate_name, role_name):
        self.record_calls.append((candidate_name, role_name))
        key = ((candidate_name or "").lower(), (role_name or "").lower())
        return self.mapping.get(key)

    def get_candidate_record_fuzzy(self, candidate_name, role_name):
        self.fuzzy_calls.append((candidate_name, role_name))
        normalized_target = _normalize(candidate_name)
        if not normalized_target:
            return None, None
        for (name, role), snapshot in self.mapping.items():
            if normalized_target in name or name in normalized_target:
                return snapshot, snapshot.candidate_name
        return None, None

    def get_all_candidate_snapshots(self, role_name: Optional[str] = None) -> List[CandidateSnapshot]:
        self.all_calls.append(role_name)
        if role_name:
            role_lower = role_name.lower()
            return [snap for snap in self._all_snapshots if snap.role.lower() == role_lower]
        return list(self._all_snapshots)


def _normalize(value: Optional[str]) -> str:
    return " ".join((value or "").strip().lower().split())


def test_handle_chat_candidate_snapshot(monkeypatch):
    handler = ArjunChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Structured reply")
    handler.model = "fake-model"

    snapshot = make_snapshot(
        name="Vemula Sowmya",
        role="HR Support",
        stage="L2",
        ai_status="shortlist",
        l1_outcome="Move to L2",
        l2_outcome="Shortlist",
    )

    service = SnapshotServiceStub({("Vemula Sowmya", "HR Support"): snapshot})
    monkeypatch.setattr(arjun_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        arjun_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.CANDIDATE_QUERY,
    )

    response = handler.handle_chat(user_message="Review Vemula Sowmya for HR Support")

    assert response == "Structured reply"
    assert len(service.record_calls) == 1
    recorded_name, recorded_role = service.record_calls[0]
    assert recorded_name.lower() == "vemula sowmya"
    assert recorded_role == "HR Support"
    assert service.fuzzy_calls == []
    payload = handler.client.requests[0]
    assert payload["messages"][0]["content"] == arjun_chat_handler.ARJUN_STATUS_SYSTEM_PROMPT


def test_arjun_aggregate_filters_using_snapshots(monkeypatch):
    handler = ArjunChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Aggregate view")
    handler.model = "fake-model"

    SummaryStore.set_l2_summary(
        L2BatchSummary(
            candidates=[
                L2CandidateResult(candidate_name="Sowmya", role="HR Support", decision="hire"),
                L2CandidateResult(candidate_name="Alex Rao", role="IT Support", decision="hold"),
            ]
        )
    )

    snapshots = [
        make_snapshot(
            name="Sowmya",
            role="HR Support",
            stage="FINAL",
            ai_status="hire",
            l2_outcome="Hire",
            final_decision="Final Hire",
        ),
        make_snapshot(
            name="Alex Rao",
            role="IT Support",
            stage="L2",
            ai_status="hold",
            l2_outcome="Hold",
        ),
    ]

    service = SnapshotServiceStub({(snap.candidate_name, snap.role): snap for snap in snapshots}, all_snapshots=snapshots)

    monkeypatch.setattr(arjun_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        arjun_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.AGGREGATE_QUERY,
    )

    response = handler.handle_chat(user_message="Show hires for HR Support")

    assert response == "Aggregate view"
    payload = handler.client.requests[0]
    assert payload["messages"][0]["content"] == arjun_chat_handler.ARJUN_AGGREGATE_SYSTEM_PROMPT
    assert "Total candidates: 1" in payload["messages"][1]["content"]
    assert "Sowmya" in payload["messages"][1]["content"]
    assert service.all_calls == ["HR Support"]
    SummaryStore.reset()


def test_arjun_handles_bot_noise_and_fuzzy_name(monkeypatch):
    handler = ArjunChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Snapshot reply")
    handler.model = "fake-model"

    sowmya_snapshot = make_snapshot(
        name="Vemula Sowmya",
        role="HR Support",
        stage="L2",
        ai_status="Shortlist",
        l1_outcome="Move to L2",
        l2_outcome="Shortlist",
    )

    service = SnapshotServiceStub({("Vemula Sowmya", "HR Support"): sowmya_snapshot})
    monkeypatch.setattr(arjun_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        arjun_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.CANDIDATE_QUERY,
    )

    response = handler.handle_chat(user_message="hey arjun can you review vemula sowmya for hr support")

    assert response == "Snapshot reply"
    assert len(service.record_calls) == 1
    recorded_name, recorded_role = service.record_calls[0]
    assert recorded_name.lower() == "vemula sowmya"
    assert recorded_role == "HR Support"
    assert service.fuzzy_calls == []
    payload = handler.client.requests[0]
    assert "L2" in payload["messages"][1]["content"]


def test_arjun_candidate_summary_mentions_final_decision(monkeypatch):
    handler = ArjunChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Arjun final reply")
    handler.model = "fake-model"

    snapshot = make_snapshot(
        name="Kotlo Dhanush",
        role="IT Admin Support",
        stage="L2",
        ai_status="On Hold",
        l1_outcome="On Hold",
        l2_outcome="Cleared",
        final_decision="Final Hire",
        next_action="Offer & onboarding",
    )

    service = SnapshotServiceStub({("Kotlo Dhanush", "IT Admin Support"): snapshot})
    monkeypatch.setattr(arjun_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        arjun_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.CANDIDATE_QUERY,
    )

    response = handler.handle_chat(
        user_message="can you please evaluate kotlo dhanush - IT Admin Support"
    )

    assert response == "Arjun final reply"
    payload = handler.client.requests[0]
    summary = payload["messages"][1]["content"]
    assert "Final decision: Final Hire" in summary


@pytest.mark.parametrize(
    "snapshot, expected_snippet, unexpected",
    [
        (
            make_snapshot(
                name="Sowmya",
                role="HR Support",
                stage="L2",
                ai_status="Shortlist",
                l2_outcome="Shortlist",
            ),
            "L2 outcome: Shortlist",
            None,
        ),
        (
            make_snapshot(
                name="Kotlo Dhanush",
                role="IT Admin Support",
                stage="Final",
                ai_status="On Hold",
                final_decision="Final Hire",
            ),
            "Final decision: Final Hire",
            "L2 outcome: On Hold",
        ),
        (
            make_snapshot(
                name="Priya HR",
                role="HR Support",
                stage="Final",
                ai_status="Shortlist",
                final_decision="Final Reject",
            ),
            "Final decision: Final Reject",
            "L2 outcome: Shortlist",
        ),
    ],
)
def test_arjun_candidate_responses_use_snapshot_truth(monkeypatch, snapshot, expected_snippet, unexpected):
    handler = ArjunChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Snapshot reply")
    handler.model = "fake-model"

    service = SnapshotServiceStub({(snapshot.candidate_name, snapshot.role): snapshot})
    monkeypatch.setattr(arjun_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        arjun_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.CANDIDATE_QUERY,
    )

    response = handler.handle_chat(user_message=f"review {snapshot.candidate_name} - {snapshot.role}")

    assert response == "Snapshot reply"
    summary = handler.client.requests[0]["messages"][1]["content"]
    assert expected_snippet in summary
    if unexpected:
        assert unexpected not in summary


def test_arjun_aggregate_shortlist_includes_final_decisions(monkeypatch):
    handler = ArjunChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Aggregate view")
    handler.model = "fake-model"

    snapshots = [
        make_snapshot(
            name="Kotlo Dhanush",
            role="IT Admin Support",
            stage="Final",
            ai_status="On Hold",
            final_decision="Final Hire",
        ),
        make_snapshot(
            name="Alex Rao",
            role="IT Support",
            stage="L2",
            ai_status="Hold",
            l2_outcome="Hold",
        ),
    ]

    service = SnapshotServiceStub({(snap.candidate_name, snap.role): snap for snap in snapshots}, all_snapshots=snapshots)
    monkeypatch.setattr(arjun_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        arjun_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.AGGREGATE_QUERY,
    )

    response = handler.handle_chat(user_message="list final hire candidates")

    assert response == "Aggregate view"
    payload = handler.client.requests[0]
    text = payload["messages"][1]["content"]
    assert "Kotlo Dhanush" in text
    assert "Alex Rao" not in text
    assert service.all_calls == [None]


def test_matches_l2_snapshot_status_variants():
    shortlist_snapshot = make_snapshot(
        name="Priya",
        role="HR Support",
        stage="L2",
        ai_status="shortlist",
        l2_outcome="Shortlist",
    )
    hold_snapshot = make_snapshot(
        name="Alex",
        role="IT Support",
        stage="L2",
        ai_status="hold",
        l2_outcome="Hold",
        next_action="Need recruiter call",
    )
    reject_snapshot = make_snapshot(
        name="Ravi",
        role="IT Support",
        stage="FINAL",
        ai_status="Rejected",
        l2_outcome="Rejected",
    )
    final_hire = make_snapshot(
        name="Dhanush",
        role="IT Admin Support",
        stage="L2",
        ai_status="Hold",
        final_decision="Final Hire",
    )
    final_reject = make_snapshot(
        name="Sanya",
        role="HR Support",
        stage="L2",
        ai_status="Shortlist",
        final_decision="Final Reject",
    )

    assert matches_l2_snapshot_status(shortlist_snapshot, "shortlist") is True
    assert matches_l2_snapshot_status(hold_snapshot, "shortlist") is False
    assert matches_l2_snapshot_status(hold_snapshot, "hold") is True
    assert matches_l2_snapshot_status(reject_snapshot, "reject") is True
    assert matches_l2_snapshot_status(final_hire, "shortlist") is True
    assert matches_l2_snapshot_status(final_hire, "hold") is False
    assert matches_l2_snapshot_status(final_reject, "reject") is True
