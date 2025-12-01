"""Candidate data access helpers for conversational and structured flows."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher, get_close_matches
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from slack_bots import ArjunSlackBot, RivaSlackBot
from drive_service import DriveManager
from summary_store import SummaryStore
from final_decision_store import FinalDecisionStore, get_final_decision_store

logger = logging.getLogger(__name__)

STAGE_PRIORITY = {
    "FINAL": 3,
    "L2": 2,
    "L1": 1,
}


class CandidateSnapshot(BaseModel):
    """Canonical candidate view used by every user-facing surface (Slack, dashboards, etc.)."""

    candidate_name: str
    role: str
    current_stage: str
    ai_status: Optional[str] = None
    l1_outcome: Optional[str] = None
    l2_outcome: Optional[str] = None
    final_decision: Optional[str] = None
    next_action: Optional[str] = None
    updated_at: datetime
    source: str


class CandidateService:
    """Fetch candidate snapshots using existing Slack bot drive logic."""

    def __init__(self) -> None:
        self._riva_bot = RivaSlackBot(slack_client=None)
        self._arjun_bot = ArjunSlackBot(slack_client=None)
        self._final_decisions: FinalDecisionStore = get_final_decision_store()

    def get_latest_candidate_snapshot(
        self,
        candidate_name: str,
        role_name: Optional[str],
        *,
        allow_fuzzy: bool = False,
    ) -> Optional[CandidateSnapshot]:
        """Return the most up-to-date snapshot across L1, L2, and finals."""

        candidate = (candidate_name or "").strip()
        role = (role_name or "").strip()

        if not candidate:
            return None

        try:
            raw_snapshots = self._collect_raw_snapshots(candidate, role, allow_fuzzy=allow_fuzzy)
            return self._resolve_snapshot_group(raw_snapshots)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error(
                "latest_snapshot_fetch_failed",
                extra={"candidate": candidate, "role": role, "error": str(exc)},
                exc_info=True,
            )
            return None

    def get_candidate_record(self, candidate_name: str, role_name: str) -> Optional[CandidateSnapshot]:
        """Backward-compatible accessor for legacy callers."""
        return self.get_latest_candidate_snapshot(candidate_name, role_name)

    def get_all_candidate_snapshots(self, role_name: Optional[str] = None) -> List[CandidateSnapshot]:
        """Return the latest snapshot for every candidate/role pair, optionally filtered by role."""

        role_filter = (role_name or "").strip() or None
        combos = self._collect_summary_candidate_pairs(role_filter)
        combo_map: Dict[str, Tuple[str, str]] = {}

        for candidate, role in combos:
            key = self._build_group_key(candidate, role)
            if key:
                combo_map.setdefault(key, (candidate, role))

        try:
            final_records = self._final_decisions.list_decisions(role_filter)
            for record in final_records:
                key = self._build_group_key(record.candidate_name, record.role)
                if key and key not in combo_map:
                    combo_map[key] = (record.candidate_name, record.role)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning(
                "final_decision_list_failed",
                extra={"role": role_filter, "error": str(exc)},
            )

        resolved_snapshots: List[CandidateSnapshot] = []
        grouped: Dict[str, List[CandidateSnapshot]] = defaultdict(list)

        for key, (candidate, role) in combo_map.items():
            raw_snapshots = self._collect_raw_snapshots(candidate, role)
            if not raw_snapshots:
                continue
            grouped[key].extend(raw_snapshots)

        for snapshot_list in grouped.values():
            merged = self._resolve_snapshot_group(snapshot_list)
            if merged:
                resolved_snapshots.append(merged)

        resolved_snapshots.sort(key=lambda snap: snap.updated_at, reverse=True)
        return resolved_snapshots

    def get_candidate_record_fuzzy(
        self, candidate_name: Optional[str], role_name: Optional[str]
    ) -> Tuple[Optional[CandidateSnapshot], Optional[str]]:
        """Broader lookup that tolerates missing or imprecise role values."""

        candidate = (candidate_name or "").strip()
        role = (role_name or "").strip()

        if not candidate:
            return None, None

        preload = self._preload_role_snapshots(role or None)
        normalized_target = _normalize_name(candidate)
        if preload and normalized_target:
            names = list(preload.keys())
            matches = get_close_matches(normalized_target, names, n=1, cutoff=0.6)
            if matches:
                matched_key = matches[0]
                matched_snapshot = preload[matched_key]
                return matched_snapshot, matched_snapshot.candidate_name

        snapshot = self.get_latest_candidate_snapshot(candidate, role or None, allow_fuzzy=True)
        if not snapshot:
            return None, None
        return snapshot, snapshot.candidate_name

    # ------------------------------------------------------------------
    def _fetch_l1_snapshot(
        self,
        candidate_name: str,
        role_name: str,
        *,
        allow_fuzzy: bool = False,
    ) -> Optional[Dict[str, str]]:
        located = self._locate_candidate(
            bot=self._riva_bot,
            candidate_name=candidate_name,
            role_name=role_name,
            folder_maps=getattr(self._riva_bot, "_search_roots", []),
            allow_fuzzy=allow_fuzzy,
        )
        if not located:
            return None

        actual_name, resolved_role, folder_id, files, drive = located
        status_payload = self._riva_bot._load_json_from_listing(drive, folder_id, self._riva_bot.L1_STATUS, files)  # type: ignore[attr-defined]
        result_payload = self._riva_bot._load_json_from_listing(drive, folder_id, self._riva_bot.L1_RESULT, files)  # type: ignore[attr-defined]

        status_value = (status_payload or {}).get("status")
        recommendation = (result_payload or {}).get("recommendation")
        current_stage = (status_payload or {}).get("current_stage") or "L1"
        ai_status = status_value or recommendation or "Unknown"
        next_action = self._riva_bot._map_l1_next_step(ai_status) if ai_status else "Awaiting recruiter action"  # type: ignore[attr-defined]
        updated_raw = (
            (status_payload or {}).get("updated_at")
            or (status_payload or {}).get("timestamp")
            or (result_payload or {}).get("updated_at")
            or (result_payload or {}).get("timestamp")
        )

        return {
            "name": actual_name,
            "role": resolved_role,
            "current_stage": current_stage,
            "ai_status": ai_status,
            "l1_outcome": status_value or recommendation or "Unknown",
            "next_action": next_action,
            "updated_at": updated_raw,
        }

    def _fetch_l2_snapshot(
        self,
        candidate_name: str,
        role_name: str,
        *,
        allow_fuzzy: bool = False,
    ) -> Optional[Dict[str, str]]:
        located = self._locate_candidate(
            bot=self._arjun_bot,
            candidate_name=candidate_name,
            role_name=role_name,
            folder_maps=getattr(self._arjun_bot, "_search_roots", []),
            allow_fuzzy=allow_fuzzy,
        )
        if not located:
            return None

        actual_name, resolved_role, folder_id, files, drive = located
        status_payload = self._arjun_bot._load_json_from_listing(drive, folder_id, self._arjun_bot.L2_STATUS, files)  # type: ignore[attr-defined]
        result_payload = self._arjun_bot._load_json_from_listing(drive, folder_id, self._arjun_bot.L2_RESULT, files)  # type: ignore[attr-defined]

        status_value = (status_payload or {}).get("status") or (result_payload or {}).get("final_recommendation")
        next_action = self._arjun_bot._map_l2_next_step(status_value) if status_value else "Awaiting recruiter action"  # type: ignore[attr-defined]
        updated_raw = (
            (status_payload or {}).get("updated_at")
            or (status_payload or {}).get("timestamp")
            or (result_payload or {}).get("updated_at")
            or (result_payload or {}).get("timestamp")
        )

        return {
            "name": actual_name,
            "role": resolved_role,
            "current_stage": "L2",
            "ai_status": status_value,
            "l2_outcome": status_value,
            "l1_outcome": (status_payload or {}).get("l1_status"),
            "next_action": next_action,
            "updated_at": updated_raw,
        }

    def _locate_candidate(
        self,
        bot: RivaSlackBot,
        candidate_name: str,
        role_name: str,
        folder_maps: List[Dict[str, str]],
        *,
        allow_fuzzy: bool = False,
    ) -> Optional[Tuple[str, str, str, List[Dict], DriveManager]]:
        """Locate candidate folder and return metadata plus drive reference."""
        if not folder_maps:
            return None

        drive = bot._get_drive()  # type: ignore[attr-defined]
        normalized_candidate = bot._normalize(candidate_name)  # type: ignore[attr-defined]
        best_match: Optional[Tuple[str, str, str, List[Dict], DriveManager]] = None
        best_ratio = 0.0

        for role_map in folder_maps:
            if role_name:
                role_targets = [bot._resolve_role(role_map, role_name)]  # type: ignore[attr-defined]
            else:
                role_targets = list(role_map.items())

            for resolved_role, parent_id in role_targets:
                if not parent_id:
                    continue
                try:
                    candidates = drive.list_folder_like(parent_id)
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.warning(
                        "candidate_folder_list_failed",
                        extra={"role": role_name or resolved_role, "parent": parent_id, "error": str(exc)},
                    )
                    continue

                for candidate in candidates:
                    candidate_label = candidate.get("name", "")
                    normalized_label = bot._normalize(candidate_label)  # type: ignore[attr-defined]
                    if normalized_label == normalized_candidate:
                        folder_id = drive.get_real_folder_id(candidate)
                        files = drive.list_files(folder_id)
                        actual_role = resolved_role or role_name or "Unknown"
                        actual_name = candidate_label or candidate_name
                        return actual_name, actual_role, folder_id, files, drive

                    if allow_fuzzy and normalized_candidate:
                        ratio = SequenceMatcher(None, normalized_label, normalized_candidate).ratio()
                        if ratio > best_ratio:
                            folder_id = drive.get_real_folder_id(candidate)
                            files = drive.list_files(folder_id)
                            actual_role = resolved_role or role_name or "Unknown"
                            actual_name = candidate_label or candidate_name
                            best_ratio = ratio
                            best_match = (actual_name, actual_role, folder_id, files, drive)

        if allow_fuzzy and best_match and best_ratio >= 0.72:
            return best_match
        return None

    def _build_snapshot_from_dict(
        self,
        payload: Dict[str, str],
        *,
        stage: str,
        source: str,
    ) -> CandidateSnapshot:
        updated_at = self._parse_timestamp(payload.get("updated_at"))
        return CandidateSnapshot(
            candidate_name=payload.get("name") or payload.get("candidate_name") or "Unknown",
            role=payload.get("role") or payload.get("resolved_role") or "Unknown",
            current_stage=stage,
            ai_status=payload.get("ai_status"),
            l1_outcome=payload.get("l1_outcome"),
            l2_outcome=payload.get("l2_outcome"),
            final_decision=payload.get("final_decision"),
            next_action=payload.get("next_action"),
            updated_at=updated_at,
            source=source,
        )

    def _fetch_final_snapshot(
        self,
        candidate_name: str,
        role_name: Optional[str],
    ) -> Optional[CandidateSnapshot]:
        if not self._final_decisions:
            return None

        record = self._final_decisions.get_decision(
            candidate_name=candidate_name,
            role_name=role_name,
        )
        if not record:
            return None

        return CandidateSnapshot(
            candidate_name=record.candidate_name,
            role=record.role,
            current_stage="Final",
            ai_status=record.decision,
            l1_outcome=None,
            l2_outcome=None,
            final_decision=record.decision,
            next_action=record.next_action,
            updated_at=record.updated_at,
            source="final_decision",
        )

    def _collect_raw_snapshots(
        self,
        candidate_name: str,
        role_name: Optional[str],
        *,
        allow_fuzzy: bool = False,
    ) -> List[CandidateSnapshot]:
        snapshots: List[CandidateSnapshot] = []

        l1_data = self._fetch_l1_snapshot(candidate_name, role_name or "", allow_fuzzy=allow_fuzzy)
        if l1_data:
            snapshots.append(self._build_snapshot_from_dict(l1_data, stage="L1", source="riva_l1"))

        l2_data = self._fetch_l2_snapshot(candidate_name, role_name or "", allow_fuzzy=allow_fuzzy)
        if l2_data:
            snapshots.append(self._build_snapshot_from_dict(l2_data, stage="L2", source="arjun_l2"))

        final_snapshot = self._fetch_final_snapshot(candidate_name, role_name or None)
        if final_snapshot:
            snapshots.append(final_snapshot)

        return snapshots

    def _resolve_snapshot_group(self, snapshots: List[CandidateSnapshot]) -> Optional[CandidateSnapshot]:
        if not snapshots:
            return None

        final_snaps = sorted(
            [snap for snap in snapshots if snap.final_decision],
            key=lambda snap: snap.updated_at,
            reverse=True,
        )

        if final_snaps:
            winner = final_snaps[0].model_copy(
                update={
                    "current_stage": "Final",
                    "ai_status": final_snaps[0].final_decision,
                }
            )
        else:
            ordered = sorted(
                snapshots,
                key=lambda snap: (
                    STAGE_PRIORITY.get((snap.current_stage or "").upper(), 0),
                    snap.updated_at,
                ),
                reverse=True,
            )
            winner = ordered[0]

        l1_outcome = self._latest_stage_value(snapshots, stage="L1", attr="l1_outcome") or winner.l1_outcome
        l2_outcome = self._latest_stage_value(snapshots, stage="L2", attr="l2_outcome") or winner.l2_outcome
        next_action = winner.next_action or self._latest_value(snapshots, attr="next_action")

        return winner.model_copy(
            update={
                "l1_outcome": l1_outcome,
                "l2_outcome": l2_outcome,
                "next_action": next_action,
            }
        )

    @staticmethod
    def _latest_stage_value(
        snapshots: List[CandidateSnapshot],
        *,
        stage: str,
        attr: str,
    ) -> Optional[str]:
        stage_upper = stage.upper()
        staged = [snap for snap in snapshots if (snap.current_stage or "").upper() == stage_upper]
        staged.sort(key=lambda snap: snap.updated_at, reverse=True)
        for snap in staged:
            value = getattr(snap, attr, None)
            if value:
                return value
        return None

    @staticmethod
    def _latest_value(snapshots: List[CandidateSnapshot], attr: str) -> Optional[str]:
        ordered = sorted(snapshots, key=lambda snap: snap.updated_at, reverse=True)
        for snap in ordered:
            value = getattr(snap, attr, None)
            if value:
                return value
        return None

    @staticmethod
    def _build_group_key(candidate_name: Optional[str], role_name: Optional[str]) -> Optional[str]:
        normalized_candidate = _normalize_name(candidate_name or "")
        normalized_role = (role_name or "").strip().lower()
        if not normalized_candidate or not normalized_role:
            return None
        return f"{normalized_candidate}::{normalized_role}"

    @staticmethod
    def _parse_timestamp(value: Optional[str]) -> datetime:
        if isinstance(value, str) and value.strip():
            cleaned = value.strip().replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(cleaned)
            except ValueError:
                pass
        return datetime.now(timezone.utc)

    def _preload_role_snapshots(self, role_name: Optional[str]) -> Dict[str, CandidateSnapshot]:
        combos = self._collect_summary_candidate_pairs(role_name)
        if not combos:
            return {}

        snapshots: Dict[str, CandidateSnapshot] = {}
        for candidate_name, role in combos:
            snapshot = self.get_latest_candidate_snapshot(candidate_name, role)
            if not snapshot:
                continue
            normalized = _normalize_name(snapshot.candidate_name)
            if not normalized:
                continue
            snapshots[normalized] = snapshot
        return snapshots

    def _collect_summary_candidate_pairs(self, role_name: Optional[str]) -> List[Tuple[str, str]]:
        role_lower = role_name.lower() if role_name else None
        combos: List[Tuple[str, str]] = []
        seen: set[str] = set()

        def add_candidates(summary) -> None:
            if not summary or not getattr(summary, "candidates", None):
                return
            for candidate in summary.candidates:
                candidate_role = getattr(candidate, "role", None)
                if role_lower and (candidate_role or "").lower() != role_lower:
                    continue
                name = getattr(candidate, "candidate_name", None)
                if not name or not candidate_role:
                    continue
                key = f"{name.lower()}::{candidate_role.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                combos.append((name, candidate_role))

        add_candidates(SummaryStore.get_l1_summary())
        add_candidates(SummaryStore.get_l2_summary())

        return combos


_candidate_service: Optional[CandidateService] = None


def get_candidate_service() -> CandidateService:
    global _candidate_service
    if _candidate_service is None:
        _candidate_service = CandidateService()
    return _candidate_service


async def get_candidate_record(candidate_name: str, role_name: str) -> Optional[CandidateSnapshot]:
    """Async-friendly wrapper for legacy compatibility."""
    service = get_candidate_service()
    return service.get_candidate_record(candidate_name, role_name)


async def get_candidate_record_fuzzy(
    candidate_name: Optional[str],
    role_name: Optional[str],
) -> Tuple[Optional[CandidateSnapshot], Optional[str]]:
    service = get_candidate_service()
    return service.get_candidate_record_fuzzy(candidate_name, role_name)


async def get_latest_candidate_snapshot(
    candidate_name: str,
    role_name: str,
) -> Optional[CandidateSnapshot]:
    service = get_candidate_service()
    return service.get_latest_candidate_snapshot(candidate_name, role_name)


async def get_all_candidate_snapshots(role_name: Optional[str] = None) -> List[CandidateSnapshot]:
    service = get_candidate_service()
    return service.get_all_candidate_snapshots(role_name)


# Backward compatibility alias
CandidateRecord = CandidateSnapshot


def _normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().split()) if value else ""
