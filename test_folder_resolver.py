"""Regression tests for `folder_resolver` helpers."""

from folder_resolver import (
    get_l2_folder,
    get_reject_folder,
    get_l2_reject_folder,
    get_shortlist_folder,
)
from folder_map import FOLDER_MAP


def test_get_l2_folder_returns_expected_ids():
    assert get_l2_folder("HR Support") == FOLDER_MAP[
        "L2 Pending Review/HR Support"
    ]
    assert get_l2_folder("IT Admin") == FOLDER_MAP[
        "L2 Pending Review/IT Admin"
    ]


def test_get_reject_folder_returns_expected_ids():
    assert get_reject_folder("IT Admin") == FOLDER_MAP["Profiles/L1 Rejected/IT Admin"]


def test_get_l2_reject_folder_returns_expected_ids():
    assert get_l2_reject_folder("IT Support") == FOLDER_MAP[
        "Profiles/L2 Rejected/IT Support"
    ]


def test_get_shortlist_folder_returns_expected_ids():
    assert get_shortlist_folder("IT Support") == FOLDER_MAP[
        "Profiles/Final Selected/IT Support"
    ]


def test_unknown_role_returns_none():
    assert get_l2_folder("Nonexistent Role") is None
    assert get_l2_reject_folder("Nonexistent Role") is None
