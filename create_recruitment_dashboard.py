"""Script to bootstrap the Hithonix Recruitment Dashboard spreadsheet."""

from __future__ import annotations

import sys
from typing import List, Tuple

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account

SERVICE_ACCOUNT_FILE = "infrastructure/service_account.json"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]
RECRUITMENT_ROOT_FOLDER_ID = "10PubI_n25X0slnSaWRAfg4ZTSBcB_3PX"
SPREADSHEET_TITLE = "Hithonix Recruitment Dashboard"
ROLE_SHEETS: List[str] = ["IT Support", "IT Admin", "HR Support"]
RAW_LOG_SHEET_NAME = "Raw_Log"
HEADER_ROW = [
    "Candidate Name",
    "Current Stage",
    "AI Status",
    "AI Recommendation Detail",
    "Overall Confidence",
    "Key Strengths (Bullets)",
    "Key Concerns (Bullets)",
    "L1 Outcome",
    "L2 Outcome",
    "Next Action",
    "Owner",
    "Feedback Report Link",
    "Folder Link",
    "Last Updated",
    "Candidate Folder ID",
]


def get_services() -> Tuple[object, object]:
    """Authenticate and return Drive and Sheets service clients."""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    drive_service = build("drive", "v3", credentials=creds)
    sheets_service = build("sheets", "v4", credentials=creds)
    return drive_service, sheets_service


def create_spreadsheet_in_folder(drive_service) -> str:
    """Create the spreadsheet file directly inside the recruitment root folder."""
    metadata = {
        "name": SPREADSHEET_TITLE,
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "parents": [RECRUITMENT_ROOT_FOLDER_ID],
    }
    file = (
        drive_service.files()
        .create(body=metadata, fields="id", supportsAllDrives=True)
        .execute()
    )
    spreadsheet_id = file.get("id")
    if not spreadsheet_id:
        raise RuntimeError("Failed to create spreadsheet via Drive API")
    return spreadsheet_id


def _get_default_sheet_id(sheets_service, spreadsheet_id: str) -> int:
    spreadsheet = (
        sheets_service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))")
        .execute()
    )
    sheets = spreadsheet.get("sheets", [])
    if not sheets:
        raise RuntimeError("Spreadsheet has no default sheet to rename")
    return sheets[0]["properties"]["sheetId"]


def setup_role_sheets(sheets_service, spreadsheet_id: str) -> None:
    """Rename/add sheets for each role, apply headers, and freeze rows."""
    if not ROLE_SHEETS:
        raise ValueError("ROLE_SHEETS cannot be empty")

    default_sheet_id = _get_default_sheet_id(sheets_service, spreadsheet_id)

    requests = [
        {
            "updateSpreadsheetProperties": {
                "properties": {"title": SPREADSHEET_TITLE},
                "fields": "title",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": default_sheet_id,
                    "title": ROLE_SHEETS[0],
                    "gridProperties": {
                        "rowCount": 1000,
                        "columnCount": 15,
                        "frozenRowCount": 1,
                    },
                },
                "fields": "title,gridProperties(rowCount,columnCount,frozenRowCount)",
            }
        },
    ]

    for role in ROLE_SHEETS[1:]:
        requests.append(
            {
                "addSheet": {
                    "properties": {
                        "title": role,
                        "gridProperties": {
                            "rowCount": 1000,
                            "columnCount": 15,
                            "frozenRowCount": 1,
                        },
                    }
                }
            }
        )

    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()

    for role in ROLE_SHEETS:
        header_range = f"'{role}'!A1:O1"
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=header_range,
            valueInputOption="RAW",
            body={"values": [HEADER_ROW]},
        ).execute()


def create_raw_log_sheet(sheets_service, spreadsheet_id: str) -> None:
    """Add a hidden Raw_Log sheet for technical logging."""
    requests = [
        {
            "addSheet": {
                "properties": {
                    "title": RAW_LOG_SHEET_NAME,
                    "hidden": True,
                    "gridProperties": {"rowCount": 1000, "columnCount": 10},
                }
            }
        }
    ]
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()


def main() -> None:
    try:
        drive_service, sheets_service = get_services()
        spreadsheet_id = create_spreadsheet_in_folder(drive_service)
        setup_role_sheets(sheets_service, spreadsheet_id)
        create_raw_log_sheet(sheets_service, spreadsheet_id)
    except HttpError as err:
        print(f"Google API error: {err}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Failed to create dashboard: {exc}", file=sys.stderr)
        sys.exit(1)

    print("==========")
    print("Recruitment dashboard created.")
    print(f"SPREADSHEET_ID = {spreadsheet_id}")
    print("Add this value to RECRUITER_SHEET_FILE_ID in your backend config.")
    print("==========")


if __name__ == "__main__":
    main()
