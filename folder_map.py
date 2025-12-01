# folder_map.py

# Source-of-truth for all Drive folder IDs

# Root-level buckets
PENDING_REVIEW_L1_ROOT_FOLDER_ID = "10PubI_n25X0slnSaWRAfg4ZTSBcB_3PX"
PENDING_REVIEW_L2_ROOT_FOLDER_ID = "190vIVukdn7Q84LJDIKqDSgqE1uDutcm2"
ON_HOLD_ROOT_FOLDER_ID           = "1oawd17qQNW8eut7UTIPI76Xjh5ckxpKW"
REJECTED_ROOT_FOLDER_ID          = "1r0SV_UcK4CcH2p3LZilHCVrrexoqQpB-"
SHORTLISTED_ROOT_FOLDER_ID       = "1ILLcp1XWqDUPE5zq1JD8hZGsY6lSpPju"

# Pending Review (L1) role folders
PENDING_REVIEW_L1_HR_SUPPORT_FOLDER_ID = "1MAcnmuecPNm4uq7lE6GExk4vYnA6BTP0"
PENDING_REVIEW_L1_IT_ADMIN_FOLDER_ID   = "1VHOV7ouwRPoIY10V_tO5ChCBcQctBUix"
PENDING_REVIEW_L1_IT_SUPPORT_FOLDER_ID = "1l1DBK1BLVcrPiqVrnUvmvfw5QmpGheJQ"

# Pending Review (L2) role folders
PENDING_REVIEW_L2_HR_SUPPORT_FOLDER_ID = "1EXUxgp3gm2c_iseBUBVyNOPebMDSPEnN"
PENDING_REVIEW_L2_IT_ADMIN_FOLDER_ID   = "1uCrlRIlS_hZr3iB3U2T9piwxIyxeMHM8"
PENDING_REVIEW_L2_IT_SUPPORT_FOLDER_ID = "1WaAA2befuEVyTv1T3TSKrRBrbnahhkKP"

# On Hold role folders
ON_HOLD_HR_SUPPORT_FOLDER_ID = "1YX2I3GhsVtVUXGVQ1kGzlsMqDrv6-UYc"
ON_HOLD_IT_ADMIN_FOLDER_ID   = "1nxorLaZoQysfbePvfPr0Ei546I-0ksq0"
ON_HOLD_IT_SUPPORT_FOLDER_ID = "1jtN6O6bw-hhl8-MLtsyvm_MWkzy8oIbk"

# Rejected role folders
REJECTED_HR_SUPPORT_FOLDER_ID = "1Nqkjb2sPVzERNMEGScOnAuT75rcWkJLE"
REJECTED_IT_ADMIN_FOLDER_ID   = "1nJUY1h_xD4RE5bmf0BondAcVSkcnACH0"
REJECTED_IT_SUPPORT_FOLDER_ID = "1B_ABstRN9DkHHdfi3KX1QMGwRu5Db0rH"

# Shortlisted (Final Selected) role folders
SHORTLISTED_HR_SUPPORT_FOLDER_ID = "1JhEUzvTkAK0RMF6lBqwi7jrsEbXBuuyB"
SHORTLISTED_IT_ADMIN_FOLDER_ID   = "18P9XOhXzw82QLqD1sEDz0plndq8__thn"
SHORTLISTED_IT_SUPPORT_FOLDER_ID = "16Ks7gdztu-pbBcVKkeQhfLFOveSxnxja"


FOLDER_MAP = {
    # L1 intake
    "L1 Pending Review": PENDING_REVIEW_L1_ROOT_FOLDER_ID,
    "L1 Pending Review/HR Support": PENDING_REVIEW_L1_HR_SUPPORT_FOLDER_ID,
    "L1 Pending Review/IT Support": PENDING_REVIEW_L1_IT_SUPPORT_FOLDER_ID,
    "L1 Pending Review/IT Admin": PENDING_REVIEW_L1_IT_ADMIN_FOLDER_ID,

    # L2 intake
    "L2 Pending Review": PENDING_REVIEW_L2_ROOT_FOLDER_ID,
    "L2 Pending Review/HR Support": PENDING_REVIEW_L2_HR_SUPPORT_FOLDER_ID,
    "L2 Pending Review/IT Support": PENDING_REVIEW_L2_IT_SUPPORT_FOLDER_ID,
    "L2 Pending Review/IT Admin": PENDING_REVIEW_L2_IT_ADMIN_FOLDER_ID,

    # On Hold buckets (aliases for compatibility)
    "On Hold": ON_HOLD_ROOT_FOLDER_ID,
    "On Hold/HR Support": ON_HOLD_HR_SUPPORT_FOLDER_ID,
    "On Hold/IT Support": ON_HOLD_IT_SUPPORT_FOLDER_ID,
    "On Hold/IT Admin": ON_HOLD_IT_ADMIN_FOLDER_ID,
    "Profiles/L2 Rejected": ON_HOLD_ROOT_FOLDER_ID,
    "Profiles/L2 Rejected/HR Support": ON_HOLD_HR_SUPPORT_FOLDER_ID,
    "Profiles/L2 Rejected/IT Support": ON_HOLD_IT_SUPPORT_FOLDER_ID,
    "Profiles/L2 Rejected/IT Admin": ON_HOLD_IT_ADMIN_FOLDER_ID,

    # Profiles outcomes – Final Selected / Shortlisted
    "Profiles": SHORTLISTED_ROOT_FOLDER_ID,
    "Profiles/Final Selected": SHORTLISTED_ROOT_FOLDER_ID,  # root alias
    "Profiles/Final Selected/HR Support": SHORTLISTED_HR_SUPPORT_FOLDER_ID,
    "Profiles/Final Selected/IT Support": SHORTLISTED_IT_SUPPORT_FOLDER_ID,
    "Profiles/Final Selected/IT Admin": SHORTLISTED_IT_ADMIN_FOLDER_ID,

    # Rejected (L1) buckets
    "Profiles/L1 Rejected": REJECTED_ROOT_FOLDER_ID,
    "Profiles/L1 Rejected/HR Support": REJECTED_HR_SUPPORT_FOLDER_ID,
    "Profiles/L1 Rejected/IT Support": REJECTED_IT_SUPPORT_FOLDER_ID,
    "Profiles/L1 Rejected/IT Admin": REJECTED_IT_ADMIN_FOLDER_ID,
}


# --------------------------------------------------------------------
#  Convenience maps for L1 and L2 role folders
#  These are derived dynamically so new roles work automatically.
# --------------------------------------------------------------------

def _build_role_map(prefix: str) -> dict[str, str]:
    """
    Build a mapping of role_name -> folder_id for keys
    like 'prefix/Role Name' in FOLDER_MAP.
    """
    result: dict[str, str] = {}
    prefix_with_slash = prefix + "/"

    for key, folder_id in FOLDER_MAP.items():
        if key.startswith(prefix_with_slash):
            # Example: key = "Pending Review Profiles (L1)/HR Support"
            role_name = key[len(prefix_with_slash):]  # "HR Support"
            result[role_name] = folder_id

    return result


# All L1 role folders: "L1 Pending Review/<Role>"
L1_FOLDERS = _build_role_map("L1 Pending Review")

# All L2 pending role folders: "L2 Pending Review/<Role>"
L2_FOLDERS = _build_role_map("L2 Pending Review")

# Profiles maps
PROFILES_FINAL_SELECTED_FOLDERS = _build_role_map("Profiles/Final Selected")
PROFILES_L1_REJECTED_FOLDERS = _build_role_map("Profiles/L1 Rejected")
PROFILES_L2_REJECTED_FOLDERS = _build_role_map("Profiles/L2 Rejected")
