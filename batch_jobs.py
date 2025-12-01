from __future__ import annotations

import logging
from typing import Optional

from arjun_l2.arjun_l2_batch import ArjunL2BatchProcessor
from arjun_l2.arjun_l2_models import L2BatchSummary
from riva_l1.riva_l1_batch import RivaL1BatchProcessor
from riva_l1.riva_l1_models import L1BatchSummary
from slack_service import SlackNotifier
from summary_store import SummaryStore

logger = logging.getLogger(__name__)


def run_riva_l1_batch(notifier: Optional[SlackNotifier] = None) -> L1BatchSummary:
    """Execute the Riva L1 batch pipeline, persist the summary, and notify Slack."""
    processor = RivaL1BatchProcessor()
    summary = processor.run()
    SummaryStore.set_l1_summary(summary)

    if notifier:
        try:
            notifier.notify_l1_batch(summary)
        except Exception as exc:  # pragma: no cover - logging path
            logger.error("l1_slack_notification_failed", exc_info=True, extra={"error": str(exc)})

    return summary


def run_arjun_l2_batch(notifier: Optional[SlackNotifier] = None) -> L2BatchSummary:
    """Execute the Arjun L2 batch pipeline, persist the summary, and notify Slack."""
    processor = ArjunL2BatchProcessor()
    summary = processor.run()
    SummaryStore.set_l2_summary(summary)

    if notifier:
        try:
            notifier.notify_l2_batch(summary)
        except Exception as exc:  # pragma: no cover - logging path
            logger.error("l2_slack_notification_failed", exc_info=True, extra={"error": str(exc)})

    return summary
