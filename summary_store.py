from __future__ import annotations

from threading import Lock
from typing import Optional

from riva_l1.riva_l1_models import L1BatchSummary
from arjun_l2.arjun_l2_models import L2BatchSummary


class SummaryStore:
    """In-memory keeper for the latest L1 and L2 batch summaries."""

    _l1_summary: Optional[L1BatchSummary] = None
    _l2_summary: Optional[L2BatchSummary] = None
    _lock: Lock = Lock()

    @classmethod
    def set_l1_summary(cls, summary: L1BatchSummary) -> None:
        if summary is None:
            return
        with cls._lock:
            cls._l1_summary = summary.model_copy(deep=True)

    @classmethod
    def set_l2_summary(cls, summary: L2BatchSummary) -> None:
        if summary is None:
            return
        with cls._lock:
            cls._l2_summary = summary.model_copy(deep=True)

    @classmethod
    def get_l1_summary(cls) -> Optional[L1BatchSummary]:
        with cls._lock:
            return cls._l1_summary.model_copy(deep=True) if cls._l1_summary else None

    @classmethod
    def get_l2_summary(cls) -> Optional[L2BatchSummary]:
        with cls._lock:
            return cls._l2_summary.model_copy(deep=True) if cls._l2_summary else None

    @classmethod
    def reset(cls) -> None:
        """Utility method for tests to clear cached summaries."""
        with cls._lock:
            cls._l1_summary = None
            cls._l2_summary = None
