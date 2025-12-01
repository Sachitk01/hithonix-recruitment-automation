from unittest.mock import MagicMock

import pytest

import batch_jobs
from arjun_l2.arjun_l2_models import L2BatchSummary
from riva_l1.riva_l1_models import L1BatchSummary
from summary_store import SummaryStore


@pytest.fixture(autouse=True)
def reset_summary_store():
    SummaryStore.reset()
    yield
    SummaryStore.reset()


def test_run_riva_l1_batch_updates_summary_and_notifies(monkeypatch):
    fake_summary = L1BatchSummary(total_seen=3)

    class FakeProcessor:
        def run(self):
            return fake_summary

    monkeypatch.setattr(batch_jobs, "RivaL1BatchProcessor", lambda: FakeProcessor())
    notifier = MagicMock()

    result = batch_jobs.run_riva_l1_batch(notifier)

    assert result is fake_summary
    saved = SummaryStore.get_l1_summary()
    assert saved.total_seen == 3
    notifier.notify_l1_batch.assert_called_once_with(fake_summary)


def test_run_arjun_l2_batch_updates_summary_and_notifies(monkeypatch):
    fake_summary = L2BatchSummary(hires=2)

    class FakeProcessor:
        def run(self):
            return fake_summary

    monkeypatch.setattr(batch_jobs, "ArjunL2BatchProcessor", lambda: FakeProcessor())
    notifier = MagicMock()

    result = batch_jobs.run_arjun_l2_batch(notifier)

    assert result is fake_summary
    saved = SummaryStore.get_l2_summary()
    assert saved.hires == 2
    notifier.notify_l2_batch.assert_called_once_with(fake_summary)
