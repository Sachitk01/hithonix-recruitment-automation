# sheet_service.py

import datetime
import logging
import re
from typing import Dict, List, Optional, Tuple

from google.oauth2 import service_account
from googleapiclient.discovery import build

from dotenv import load_dotenv

from google_auth_utils import load_service_account_credentials

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
ROLE_SHEET_MAP: Dict[str, str] = {
    "IT SUPPORT": "IT Support",
    "IT ADMIN": "IT Admin",
    "HR SUPPORT": "HR Support",
}

EXPECTED_HEADERS: List[str] = [
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

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _load_service_account_credentials() -> Optional[
    Tuple[service_account.Credentials, Optional[str]]
]:
    return load_service_account_credentials(SCOPES)


class SheetManager:
    def __init__(self, correlation_id: Optional[str] = None):
        """
        Initialise Google Sheets client using shared service account credential loader.
        The loader resolves credentials via:
        1. GOOGLE_APPLICATION_CREDENTIALS path
        2. RIVA_SA_JSON path
        3. RIVA_SA_JSON_CONTENT inline JSON
        4. gcp-secret:// reference via Secret Manager (if configured)
        """
        self.correlation_id = correlation_id or "no-correlation-id"

        creds_tuple = _load_service_account_credentials()
        if not creds_tuple:
            logger.error(
                "sheet_credentials_missing",
                extra={"correlation_id": self.correlation_id},
            )
            raise RuntimeError("Service account credentials not configured for Sheets")

        creds, source = creds_tuple
        logger.info(
            "sheet_credentials_loaded",
            extra={
                "correlation_id": self.correlation_id,
                "credential_source": source,
            },
        )

        self.service = build("sheets", "v4", credentials=creds)


def get_sheets_service():
    creds_tuple = _load_service_account_credentials()
    if not creds_tuple:
        logger.error("sheets_service_account_missing")
        raise RuntimeError("Service account credentials not configured for Sheets")

    creds, source = creds_tuple
    logger.info(
        "sheets_service_created",
        extra={
            "correlation_id": "sheets-service",
            "credential_source": source,
        },
    )
    return build("sheets", "v4", credentials=creds)


def map_role_to_sheet_title(role: str) -> str:
    """Resolve a role string to a sheet tab title, falling back to normalization."""
    if not role:
        return "Unknown Role"

    key = role.strip().upper()
    if key in ROLE_SHEET_MAP:
        return ROLE_SHEET_MAP[key]

    return normalize_role_to_sheet_title(role)


def normalize_role_to_sheet_title(role: str) -> str:
    """Turn an arbitrary role string into a safe sheet tab title."""
    if not role:
        return "Unknown Role"

    cleaned = re.sub(r"[^0-9A-Za-z]+", " ", role)
    cleaned = cleaned.strip()
    if not cleaned:
        return "Unknown Role"

    title = cleaned.title()
    overrides = {
        "It Support": "IT Support",
        "It Admin": "IT Admin",
        "Hr Support": "HR Support",
    }
    title = overrides.get(title, title)
    return title[:90]


def ensure_sheet_exists(
    service,
    spreadsheet_id: str,
    sheet_title: str,
    column_count: int = len(EXPECTED_HEADERS),
):
    """Ensure the destination sheet tab exists, creating it with headers if missing."""
    sheet_api = service.spreadsheets()
    spreadsheet = sheet_api.get(spreadsheetId=spreadsheet_id).execute()
    existing = {
        s["properties"]["title"]: s["properties"]["sheetId"]
        for s in spreadsheet.get("sheets", [])
    }

    if sheet_title in existing:
        return existing[sheet_title]

    requests = [
        {
            "addSheet": {
                "properties": {
                    "title": sheet_title,
                    "gridProperties": {
                        "rowCount": 1000,
                        "columnCount": column_count,
                        "frozenRowCount": 1,
                    },
                }
            }
        }
    ]

    batch_res = sheet_api.batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()

    new_sheet_id = batch_res["replies"][0]["addSheet"]["properties"]["sheetId"]
    logger.info(
        "Recruiter dashboard: created new sheet tab '%s' in spreadsheet %s",
        sheet_title,
        spreadsheet_id,
    )

    sheet_api.values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{sheet_title}'!A1:O1",
        valueInputOption="USER_ENTERED",
        body={"values": [EXPECTED_HEADERS]},
    ).execute()

    return new_sheet_id


def upsert_role_sheet_row(
    *,
    file_id: str,
    role: str,
    candidate_folder_id: str,
    candidate_name: str,
    current_stage: str,
    ai_status: str,
    ai_recommendation_detail: str,
    overall_confidence: str,
    key_strengths: List[str],
    key_concerns: List[str],
    l1_outcome: Optional[str],
    l2_outcome: Optional[str],
    next_action: str,
    owner: Optional[str],
    feedback_link: Optional[str],
    folder_link: Optional[str],
    last_updated: datetime.datetime,
) -> None:
    """
    Upsert a row in the appropriate role sheet tab in the recruiter dashboard.
    - file_id: spreadsheet ID (RECRUITER_SHEET_FILE_ID).
    - role: logical role name ("IT Support", "IT Admin", "HR Support", etc).
    - candidate_folder_id: used as a technical key to find/update the candidate row.
    - If no row exists for (role, candidate_folder_id), append a new row at the bottom.
    - If a row exists, update that row in place.
    """

    strengths_str = " • ".join(key_strengths) if key_strengths else ""
    concerns_str = " • ".join(key_concerns) if key_concerns else ""
    last_updated_str = last_updated.strftime("%d-%b-%Y %H:%M")

    row_values = [
        candidate_name or "",
        current_stage or "",
        ai_status or "",
        ai_recommendation_detail or "",
        overall_confidence or "",
        strengths_str,
        concerns_str,
        l1_outcome or "",
        l2_outcome or "",
        next_action or "",
        owner or "",
        feedback_link or "",
        folder_link or "",
        last_updated_str,
        candidate_folder_id,
    ]

    service = get_sheets_service()
    sheet = service.spreadsheets()

    sheet_title = map_role_to_sheet_title(role)
    logger.info(
        "Recruiter dashboard: resolving role '%s' to sheet '%s'",
        role,
        sheet_title,
    )

    ensure_sheet_exists(service, file_id, sheet_title, column_count=len(row_values))

    header_range = f"'{sheet_title}'!A1:O1"
    data_range = f"'{sheet_title}'!A2:O"

    _ = sheet.values().get(
        spreadsheetId=file_id,
        range=header_range,
    ).execute()

    result = sheet.values().get(
        spreadsheetId=file_id,
        range=data_range,
    ).execute()
    rows = result.get("values", [])

    existing_row_index = None
    for idx, row in enumerate(rows):
        if len(row) >= 15 and row[14] == candidate_folder_id:
            existing_row_index = idx
            break

    if existing_row_index is not None:
        start_row = existing_row_index + 2
        update_range = f"'{sheet_title}'!A{start_row}:O{start_row}"
        sheet.values().update(
            spreadsheetId=file_id,
            range=update_range,
            valueInputOption="USER_ENTERED",
            body={"values": [row_values]},
        ).execute()
    else:
        append_range = f"'{sheet_title}'!A:O"
        sheet.values().append(
            spreadsheetId=file_id,
            range=append_range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row_values]},
        ).execute()

    # ------------------------------------------------------------------
    # Append a single row to a sheet tab
    # ------------------------------------------------------------------
    def append_row(self, sheet_id: str, sheet_name: str, row_values: List):
        """
        Append a row to the given sheet tab.

        We use A1-style range: 'SheetName!A1:Z' to avoid 'Unable to parse range' errors.
        """
        # Make sure we don't exceed 26 columns (A–Z)
        if len(row_values) > 26:
            row_values = row_values[:26]

        range_name = f"{sheet_name}!A1:Z"

        body = {
            "values": [row_values]
        }

        request = (
            self.service.spreadsheets()
            .values()
            .append(
                spreadsheetId=sheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            )
        )

        response = request.execute()
        # Optional: log for debugging
        updated = response.get("updates", {}).get("updatedRange")
        if updated:
            logger.info(
                "sheet_row_appended",
                extra={
                    "correlation_id": self.correlation_id,
                    "sheet_id": sheet_id,
                    "sheet_name": sheet_name,
                    "range": updated,
                },
            )
        else:
            logger.info(
                "sheet_row_append_response",
                extra={
                    "correlation_id": self.correlation_id,
                    "sheet_id": sheet_id,
                    "sheet_name": sheet_name,
                    "response": response,
                },
            )
