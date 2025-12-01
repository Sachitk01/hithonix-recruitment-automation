# folder_resolver.py

from folder_map import (
    FOLDER_MAP,
    L2_FOLDERS,
    PROFILES_L1_REJECTED_FOLDERS,
    PROFILES_L2_REJECTED_FOLDERS,
    PROFILES_FINAL_SELECTED_FOLDERS,
)

"""
This resolver converts:
 - stage (L1 → L2, HOLD, REJECT)
 - role (HR Support, IT Support, IT Admin, etc.)

into the correct Google Drive folder ID.

It dynamically supports unlimited roles.
"""


def get_l2_folder(role_name: str):
    """Return correct L2 folder for the given role."""
    return L2_FOLDERS.get(role_name)


def get_hold_folder(role_name: str):
    """Return On Hold folder for the given role."""
    key = f"On Hold/{role_name}"
    return FOLDER_MAP.get(key)


def get_reject_folder(role_name: str):
    """Return Profiles/L1 Rejected folder for the given role."""
    return PROFILES_L1_REJECTED_FOLDERS.get(role_name)


def get_l2_reject_folder(role_name: str):
    """Return Profiles/L2 Rejected folder for the given role."""
    return PROFILES_L2_REJECTED_FOLDERS.get(role_name)


def get_shortlist_folder(role_name: str):
    """Return folder for Final Selected."""
    return PROFILES_FINAL_SELECTED_FOLDERS.get(role_name)


# OPTIONAL: for debugging
def debug_role_paths(role_name: str):
    return {
        "L2": get_l2_folder(role_name),
        "HOLD": get_hold_folder(role_name),
        "REJECT": get_reject_folder(role_name),
        "SHORTLIST": get_shortlist_folder(role_name),
    }
