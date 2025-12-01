import types
import pytest
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import riva_chat_handler
from candidate_service import CandidateSnapshot
from chat_intents import WorkIntentType
from chat_parsers import build_role_lookup, try_extract_candidate_and_role_from_text
from folder_map import L1_FOLDERS
from riva_chat_handler import RivaChatHandler, matches_snapshot_status
from riva_l1.riva_l1_models import L1BatchSummary, L1CandidateResult
from summary_store import SummaryStore


ROLE_LOOKUP = build_role_lookup(L1_FOLDERS.keys())


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


def test_try_extract_candidate_and_role_handles_status_question():
    candidate, role = try_extract_candidate_and_role_from_text(
        "What's the status of Priya Singh for HR Support?",
        ROLE_LOOKUP,
        riva_chat_handler.COMMAND_PREFIXES,
    )

    assert candidate == "Priya Singh"
    assert role == "HR Support"


def test_handle_chat_uses_structured_candidate_snapshot(monkeypatch):
    handler = RivaChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Structured reply")
    handler.model = "fake-model"

    expected_snapshot = make_snapshot(
        name="Priya Singh",
        role="HR Support",
        stage="L1",
        ai_status="Ready for L2",
        l1_outcome="Move to L2",
        next_action="Schedule L2 interview",
    )

    service = SnapshotServiceStub({("Priya Singh", "HR Support"): expected_snapshot})
    monkeypatch.setattr(riva_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        riva_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.CANDIDATE_QUERY,
    )

    response = handler.handle_chat("Review Priya Singh for HR Support")

    assert response == "Structured reply"
    assert service.record_calls == [("Priya Singh", "HR Support")]
    assert service.fuzzy_calls == []
    assert handler.client.requests
    request_payload = handler.client.requests[0]
    assert request_payload["temperature"] == 0.2
    assert request_payload["model"] == "fake-model"


def test_handle_chat_returns_not_found_when_snapshot_missing(monkeypatch):
    handler = RivaChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient()

    service = SnapshotServiceStub({})
    monkeypatch.setattr(riva_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        riva_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.CANDIDATE_QUERY,
    )

    response = handler.handle_chat("Review Someone Unknown for IT Support")

    assert "evaluation data" in response.lower()
    assert "someone unknown" in response.lower()
    assert handler.client.requests == []
    assert service.record_calls == [("Someone Unknown", "IT Support")]
    assert service.fuzzy_calls == [("Someone Unknown", "IT Support")]


def test_handle_chat_aggregate_query_formats_snapshot_summary(monkeypatch):
    handler = RivaChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Aggregate view")
    handler.model = "fake-model"

    SummaryStore.set_l1_summary(
        L1BatchSummary(
            candidates=[
                L1CandidateResult(candidate_name="Priya Singh", role="HR Support", decision="move_to_l2"),
                L1CandidateResult(candidate_name="Alex Rao", role="IT Support", decision="hold", reason="Need transcript"),
            ]
        )
    )

    snapshots = [
        make_snapshot(
            name="Priya Singh",
            role="HR Support",
            stage="L2",
            ai_status="send_to_l2",
            l1_outcome="Move to L2",
            l2_outcome="Shortlist",
        ),
        make_snapshot(
            name="Alex Rao",
            role="IT Support",
            stage="HOLD",
            ai_status="hold",
            l1_outcome="Hold",
            next_action="Need transcript",
        ),
    ]

    service = SnapshotServiceStub({(snap.candidate_name, snap.role): snap for snap in snapshots}, all_snapshots=snapshots)
    monkeypatch.setattr(riva_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        riva_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.AGGREGATE_QUERY,
    )

    response = handler.handle_chat("Show everyone who moved to L2")

    assert response == "Aggregate view"
    assert handler.client.requests
    payload = handler.client.requests[0]
    assert payload["messages"][0]["content"] == riva_chat_handler.RIVA_AGGREGATE_SYSTEM_PROMPT
    assert "Total candidates: 1" in payload["messages"][1]["content"]
    assert "Priya Singh" in payload["messages"][1]["content"]
    assert service.all_calls == [None]
    SummaryStore.reset()


def test_riva_handles_bot_noise_and_fuzzy_name(monkeypatch):
    handler = RivaChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Snapshot reply")
    handler.model = "fake-model"

    sowmya_snapshot = make_snapshot(
        name="Vemula Sowmya",
        role="HR Support",
        stage="L2",
        ai_status="Move to L2",
        l1_outcome="Move to L2",
        l2_outcome="Shortlist",
    )

    service = SnapshotServiceStub({("Vemula Sowmya", "HR Support"): sowmya_snapshot})
    monkeypatch.setattr(riva_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        riva_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.CANDIDATE_QUERY,
    )

    response = handler.handle_chat("hey riva can you evaluate vemula sowmya of hr support")

    assert response == "Snapshot reply"
    assert len(service.record_calls) == 1
    recorded_name, recorded_role = service.record_calls[0]
    assert recorded_name.lower() == "vemula sowmya"
    assert recorded_role == "HR Support"
    assert service.fuzzy_calls == []
    payload = handler.client.requests[0]
    assert "L2" in payload["messages"][1]["content"]


def test_riva_candidate_summary_prioritizes_final_decision(monkeypatch):
    handler = RivaChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Final decision reply")
    handler.model = "fake-model"

    snapshot = make_snapshot(
        name="Kotlo Dhanush",
        role="IT Admin Support",
        stage="L2",
        ai_status="On Hold",
        l1_outcome="On Hold",
        l2_outcome="Cleared",
        next_action="Offer & onboarding",
        final_decision="Final Hire",
    )

    service = SnapshotServiceStub({("Kotlo Dhanush", "IT Admin Support"): snapshot})
    monkeypatch.setattr(riva_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        riva_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.CANDIDATE_QUERY,
    )

    response = handler.handle_chat("check kotlo dhanush profile for it admin support")

    assert response == "Final decision reply"
    payload = handler.client.requests[0]
    summary = payload["messages"][1]["content"]
    assert "Decision: Final Hire" in summary
    assert "AI status: On Hold" not in summary


def test_matches_snapshot_status_respects_finalization():
    finalist = make_snapshot(
        name="Priya",
        role="HR Support",
        stage="L2",
        ai_status="Move to L2",
        final_decision="Final Hire",
    )
    hold_snapshot = make_snapshot(
        name="Alex",
        role="IT Support",
        stage="HOLD",
        ai_status="On Hold",
    )
    final_reject = make_snapshot(
        name="Ravi",
        role="IT Support",
        stage="Final",
        ai_status="Move to L2",
        final_decision="Final Reject",
    )

    assert matches_snapshot_status(finalist, "ready_for_l2") is False
    assert matches_snapshot_status(hold_snapshot, "hold") is True
    assert matches_snapshot_status(final_reject, "hold") is False
    assert matches_snapshot_status(final_reject, "reject") is True


@pytest.mark.parametrize(
    "snapshot, expected_snippet, unexpected_snippet",
    [
        (
            make_snapshot(
                name="Sowmya",
                role="HR Support",
                stage="L2",
                ai_status="Move to L2",
                l1_outcome="Move to L2",
            ),
            "AI status: Move to L2",
            None,
        ),
        (
            make_snapshot(
                name="Kotlo Dhanush",
                role="IT Admin Support",
                stage="Final",
                ai_status="On Hold",
                final_decision="Final Hire",
                next_action="Offer & onboarding",
            ),
            "Decision: Final Hire",
            "AI status: On Hold",
        ),
        (
            make_snapshot(
                name="Priya HR",
                role="HR Support",
                stage="Final",
                ai_status="Shortlist",
                final_decision="Final Reject",
            ),
            "Decision: Final Reject",
            "AI status: Shortlist",
        ),
    ],
)
def test_riva_candidate_queries_use_snapshot_truth(monkeypatch, snapshot, expected_snippet, unexpected_snippet):
    handler = RivaChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Snapshot reply")
    handler.model = "fake-model"

    service = SnapshotServiceStub({(snapshot.candidate_name, snapshot.role): snapshot})
    monkeypatch.setattr(riva_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        riva_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.CANDIDATE_QUERY,
    )

    response = handler.handle_chat(f"check {snapshot.candidate_name} for {snapshot.role}")

    assert response == "Snapshot reply"
    summary = handler.client.requests[0]["messages"][1]["content"]
    assert expected_snippet in summary
    if unexpected_snippet:
        assert unexpected_snippet not in summary


def test_riva_aggregate_ready_for_l2_uses_latest_snapshot_state(monkeypatch):
    handler = RivaChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Aggregate list")
    handler.model = "fake-model"

    snapshots = [
        make_snapshot(
            name="Sowmya",
            role="HR Support",
            stage="L2",
            ai_status="Move to L2",
        ),
        make_snapshot(
            name="Kotlo Dhanush",
            role="IT Admin Support",
            stage="Final",
            ai_status="On Hold",
            final_decision="Final Hire",
        ),
    ]

    service = SnapshotServiceStub({(snap.candidate_name, snap.role): snap for snap in snapshots}, all_snapshots=snapshots)
    monkeypatch.setattr(riva_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        riva_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.AGGREGATE_QUERY,
    )

    response = handler.handle_chat("list out all the candidates moved to L2")

    assert response == "Aggregate list"
    payload = handler.client.requests[0]
    text = payload["messages"][1]["content"]
    assert "Sowmya" in text
    assert "Kotlo Dhanush" not in text
    assert service.all_calls == [None]


def test_riva_aggregate_hold_excludes_finalized_candidates(monkeypatch):
    handler = RivaChatHandler(openai_api_key=None)
    handler.client = DummyLLMClient("Aggregate hold list")
    handler.model = "fake-model"

    SummaryStore.set_l1_summary(
        L1BatchSummary(
            candidates=[
                L1CandidateResult(candidate_name="Alex Rao", role="IT Support", decision="hold"),
                L1CandidateResult(candidate_name="Kotlo Dhanush", role="IT Admin Support", decision="move_to_l2"),
            ]
        )
    )

    hold_snapshot = make_snapshot(
        name="Alex Rao",
        role="IT Support",
        stage="HOLD",
        ai_status="On Hold",
    )
    finalized = make_snapshot(
        name="Kotlo Dhanush",
        role="IT Admin Support",
        stage="Final",
        ai_status="On Hold",
        final_decision="Final Hire",
    )

    service = SnapshotServiceStub(
        {
            (hold_snapshot.candidate_name, hold_snapshot.role): hold_snapshot,
            (finalized.candidate_name, finalized.role): finalized,
        },
        all_snapshots=[hold_snapshot, finalized],
    )

    monkeypatch.setattr(riva_chat_handler, "get_candidate_service", lambda: service)
    monkeypatch.setattr(
        riva_chat_handler,
        "classify_work_intent",
        lambda *_: WorkIntentType.AGGREGATE_QUERY,
    )

    response = handler.handle_chat("Show everyone on hold")

    assert response == "Aggregate hold list"
    payload = handler.client.requests[0]
    text = payload["messages"][1]["content"]
    assert "Alex Rao" in text
    assert "Kotlo Dhanush" not in text
    SummaryStore.reset()
