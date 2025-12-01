import json
from typing import Dict

from google.oauth2 import service_account
from googleapiclient.discovery import build

# ========== CONFIGURATION ==========

# Your service account JSON in the SAME folder as this script
SERVICE_ACCOUNT_FILE = "service_account.json"

# Your existing Shared Drive ID (the one you sent me)
EXISTING_DRIVE_ID = "0AHfgdXYa9mVcUk9PVA"

# Roles you want under each pipeline folder
ROLES = [
    "HR Support",
    "IT Support",
    "IT Admin",
    # add more roles later if needed
]

# Top-level pipeline folders to create
TOP_LEVEL_FOLDERS = [
    "Pending Review Profiles (L1)",
    "L2 Pending Reviews",
    "Shortlisted (Final Selected)",
    "On Hold",
    "Rejected",
]

# ===================================


def get_drive_service():
    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=scopes
    )
    service = build("drive", "v3", credentials=creds)
    return service


def create_folder(service, name: str, parent_id: str) -> str:
    """Create a folder under a given parent folder."""
    file_metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }

    folder = (
        service.files()
        .create(
            body=file_metadata,
            fields="id, name",
            supportsAllDrives=True,
        )
        .execute()
    )

    folder_id = folder["id"]
    print(f"  Created folder: {name} (id={folder_id}) under parent={parent_id}")
    return folder_id


def main():
    service = get_drive_service()

    drive_id = EXISTING_DRIVE_ID
    print(f"Using existing Shared Drive: {drive_id}")

    folder_ids: Dict[str, str] = {}

    # 1) Create top-level pipeline folders in the Shared Drive root
    for top in TOP_LEVEL_FOLDERS:
        top_folder_metadata = {
            "name": top,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [drive_id],  # root of the shared drive
        }

        top_folder = (
            service.files()
            .create(
                body=top_folder_metadata,
                fields="id, name",
                supportsAllDrives=True,
            )
            .execute()
        )

        top_folder_id = top_folder["id"]
        folder_ids[top] = top_folder_id
        print(f"Created top-level folder: {top} (id={top_folder_id})")

        # 2) Create role subfolders under each top-level folder
        for role in ROLES:
            sub_key = f"{top}/{role}"
            sub_id = create_folder(service, role, top_folder_id)
            folder_ids[sub_key] = sub_id

    print("\n===== FOLDER ID MAP (copy this somewhere safe) =====\n")
    print(json.dumps(folder_ids, indent=2))


if __name__ == "__main__":
    main()
