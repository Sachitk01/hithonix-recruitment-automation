"""Monitor recruiter dashboard health by verifying headers and row counts."""

import os
import sys

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "infrastructure/service_account.json",
)
RECRUITER_SHEET_FILE_ID = os.getenv(
    "RECRUITER_SHEET_FILE_ID",
    "1ZqNfOsyyNs5wBSTU8Xm-IxZAF1X27SpJsDwyaAwvpj4",
)

ROLE_SHEETS = ["IT Support", "IT Admin", "HR Support"]
EXPECTED_HEADERS = [
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


def get_sheets_service():
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
    return build("sheets", "v4", credentials=creds)


def main():
    service = get_sheets_service()
    sheet = service.spreadsheets()

    overall_ok = True

    for role_sheet in ROLE_SHEETS:
        header_range = f"'{role_sheet}'!A1:O1"
        data_range = f"'{role_sheet}'!A2:O"

        try:
            header_res = sheet.values().get(
                spreadsheetId=RECRUITER_SHEET_FILE_ID,
                range=header_range,
            ).execute()
        except Exception as exc:  # pragma: no cover - network interaction
            print(f"[ERROR] Unable to read sheet '{role_sheet}': {exc}")
            overall_ok = False
            continue

        headers = header_res.get("values", [[]])[0] if header_res.get("values") else []
        if headers != EXPECTED_HEADERS:
            print(f"[WARN] Sheet '{role_sheet}': header mismatch.")
            print(f"       Got: {headers}")
            overall_ok = False
            continue

        data_res = sheet.values().get(
            spreadsheetId=RECRUITER_SHEET_FILE_ID,
            range=data_range,
        ).execute()
        rows = data_res.get("values", [])
        print(f"[OK] Sheet '{role_sheet}': {len(rows)} candidate rows, headers valid.")

    if not overall_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
