from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from sheet_service import SheetManager


class DecisionStore:
    """
    Handles logging L1/L2 decisions into the 'Recruitment Decisions (Master)' sheet.
    """

    def __init__(
        self,
        sheet_manager: Optional[SheetManager] = None,
        default_sheet_title: str = "Decisions",
    ) -> None:
        self.sheet_manager = sheet_manager or SheetManager()
        self.default_sheet_title = default_sheet_title

    # ------------------------------------------------------------------
    def _now_ist_iso(self) -> str:
        # simple UTC timestamp; you can later localise to IST
        return datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    def log_l1_decision(
        self,
        *,
        candidate_id: str,
        candidate_name: str,
        role_name: str,
        l1_score: float,
        l1_decision: str,
        l1_strengths: str,
        l1_concerns: str,
        jd_hash: str = "",
        resume_hash: str = "",
        jd_title: Optional[str] = None,
        **_extra_kwargs,
    ) -> Dict[str, Any]:
        """
        Writes/append an L1 decision row. For now we use append only.
        Columns (A–P):

        A: candidate_id
        B: candidate_name
        C: role_name
        D: l1_score
        E: l1_decision
        F: l1_strengths
        G: l1_concerns
        H: l1_reviewed_at
        I: l2_score
        J: l2_decision
        K: l2_summary
        L: l2_reviewed_at
        M: final_status
        N: final_summary
        O: jd_hash
        P: resume_hash
        """
        reviewed_at = self._now_ist_iso()

        values: List[Any] = [
            candidate_id,
            candidate_name,
            role_name,
            l1_score,
            l1_decision,
            l1_strengths,
            l1_concerns,
            reviewed_at,
            "",  # l2_score
            "",  # l2_decision
            "",  # l2_summary
            "",  # l2_reviewed_at
            "",  # final_status
            "",  # final_summary
            jd_hash,
            resume_hash,
        ]

        # jd_title currently unused because the decision sheet schema
        # does not expose a dedicated JD column. We still accept it to
        # keep parity with upstream callers.

        return self.sheet_manager.append_row(
            values, sheet_title=self.default_sheet_title
        )

    # ------------------------------------------------------------------
    def log_l2_decision(
        self,
        candidate_id: str,
        candidate_name: str,
        role_name: str,
        l2_score: float,
        l2_decision: str,
        l2_summary: str,
        final_status: str,
        final_summary: str,
    ) -> Dict[str, Any]:
        """
        For now, we ALSO append an L2 row instead of updating L1 row.
        Later we can implement a search+update if you want 1 row per candidate.

        This keeps the schema consistent: each row still matches A–P.
        """
        reviewed_at = self._now_ist_iso()

        values: List[Any] = [
            candidate_id,
            candidate_name,
            role_name,
            "",  # l1_score
            "",  # l1_decision
            "",  # l1_strengths
            "",  # l1_concerns
            "",  # l1_reviewed_at
            l2_score,
            l2_decision,
            l2_summary,
            reviewed_at,
            final_status,
            final_summary,
            "",  # jd_hash
            "",  # resume_hash
        ]

        return self.sheet_manager.append_row(
            values, sheet_title=self.default_sheet_title
        )
