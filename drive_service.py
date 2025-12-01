# drive_service.py

import io
import json
import logging
from typing import Dict, List, Optional, Tuple

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2 import service_account

from google_auth_utils import load_service_account_credentials
from dotenv import load_dotenv


load_dotenv()

# Full Drive access – folders + files + exports
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Configure logger
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
    """Load credentials via shared helper; returns (creds, source_description)."""
    return load_service_account_credentials(SCOPES)


class DriveManager:
    def __init__(self, correlation_id: Optional[str] = None):
        """
        Google Drive manager using a service account.

        Expects either:
        - RIVA_SA_JSON: path to service_account.json
        or
        - RIVA_SA_JSON_CONTENT: inline JSON string
        
        Args:
            correlation_id: Optional correlation ID for tracing requests
        """
        self.correlation_id = correlation_id or "no-correlation-id"
        
        creds_tuple = _load_service_account_credentials()
        if not creds_tuple:
            raise RuntimeError("Service account credentials not configured")

        creds, project_id = creds_tuple
        logger.info(
            "Using service account credentials (project: %s)",
            project_id,
            extra={"correlation_id": self.correlation_id},
        )

        self.service = build("drive", "v3", credentials=creds)

    # ------------------------------------------------------------------
    # Private helper - raw list matching debug_it_admin.py
    # ------------------------------------------------------------------
    def _raw_list(self, parent_id: str) -> List[Dict]:
        """
        Raw list call matching debug_it_admin.py query and flags.
        Returns all items (folders and files) under parent_id.
        """
        response = (
            self.service.files()
            .list(
                q=f"'{parent_id}' in parents and trashed=false",
                fields="files(id,name,mimeType,shortcutDetails,parents)",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                corpora="allDrives",
            )
            .execute()
        )
        return response.get("files", [])

    # ------------------------------------------------------------------
    # Folder classification helpers
    # ------------------------------------------------------------------
    def is_folder(self, item: Dict) -> bool:
        """Check if an item is a regular folder."""
        mt = (item.get("mimeType") or "").lower()
        return "folder" in mt

    def is_folder_like(self, item: Dict) -> bool:
        """
        Check if an item is folder-like (real folder or shortcut).
        Future-proofed for shortcuts even if not currently present.
        """
        mt = (item.get("mimeType") or "").lower()
        return (
            "folder" in mt
            or mt == "application/vnd.google-apps.shortcut"
        )

    def get_real_folder_id(self, item: Dict) -> str:
        """
        Get the real folder ID, resolving shortcuts to their target.
        """
        mt = (item.get("mimeType") or "").lower()
        if mt == "application/vnd.google-apps.shortcut":
            return item.get("shortcutDetails", {}).get("targetId") or item.get("id")
        return item.get("id")

    # ------------------------------------------------------------------
    # Explicit folder and file listing methods
    # ------------------------------------------------------------------
    def list_folders(self, parent_id: str, correlation_id: Optional[str] = None) -> List[Dict]:
        """
        List only folder items under parent_id.
        Use this for discovering role folders or candidate folders.
        """
        items = self._raw_list(parent_id)
        folders = [i for i in items if self.is_folder(i)]
        
        corr_id = correlation_id or "no-correlation-id"
        logger.info(
            "listed_folders",
            extra={
                "folder_id": parent_id,
                "count": len(folders),
                "correlation_id": corr_id,
            },
        )
        return folders

    def list_folder_like(self, parent_id: str, correlation_id: Optional[str] = None) -> List[Dict]:
        """
        List folder-like items (real folders + shortcuts) under parent_id.
        Use this for discovering candidates when shortcuts might exist.
        """
        items = self._raw_list(parent_id)
        folder_like = [i for i in items if self.is_folder_like(i)]
        
        corr_id = correlation_id or "no-correlation-id"
        logger.info(
            "listed_folder_like",
            extra={
                "folder_id": parent_id,
                "count": len(folder_like),
                "correlation_id": corr_id,
            },
        )
        return folder_like

    def list_files(self, parent_id: str, correlation_id: Optional[str] = None) -> List[Dict]:
        """
        List only file items (non-folders) under parent_id.
        Use this for discovering documents inside a candidate folder.
        
        Returns: list of dicts with keys: id, name, mimeType
        """
        items = self._raw_list(parent_id)
        files = [i for i in items if not self.is_folder(i)]
        
        corr_id = correlation_id or "no-correlation-id"
        logger.info(
            "listed_files",
            extra={
                "folder_id": parent_id,
                "count": len(files),
                "correlation_id": corr_id,
            },
        )
        return files

    # ------------------------------------------------------------------
    # Download a file (PDF/DOCX/TXT/etc.) to local disk
    # ------------------------------------------------------------------
    def download_file(self, file_id: str, dest_path: str) -> None:
        """
        Download a binary file to dest_path.
        """
        request = self.service.files().get_media(
            fileId=file_id
        )
        fh = io.FileIO(dest_path, "wb")
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"[DriveManager] Download {int(status.progress() * 100)}%.")

    def download_file_bytes(self, file_id: str) -> bytes:
        """Download a binary file and return its bytes payload."""
        request = self.service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.debug(
                    "download_progress",
                    extra={
                        "correlation_id": self.correlation_id,
                        "file_id": file_id,
                        "progress": int(status.progress() * 100),
                    },
                )

        fh.seek(0)
        data = fh.read()
        logger.info(
            "downloaded_file_bytes",
            extra={"correlation_id": self.correlation_id, "file_id": file_id, "size": len(data)},
        )
        return data

    def _find_file_by_name(self, parent_id: str, filename: str) -> Optional[Dict]:
        """Return the first file under parent_id with the exact filename, if any."""
        response = (
            self.service.files()
            .list(
                q=f"'{parent_id}' in parents and name='{filename}' and trashed=false",
                spaces="drive",
                fields="files(id,name,mimeType)",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                corpora="allDrives",
            )
            .execute()
        )
        files = response.get("files", [])
        return files[0] if files else None

    def _upload_bytes(
        self,
        parent_id: str,
        filename: str,
        payload: bytes,
        mime_type: str,
    ) -> Dict:
        """Create or update a file with the given contents under parent_id."""
        media = MediaIoBaseUpload(io.BytesIO(payload), mimetype=mime_type, resumable=False)
        existing = self._find_file_by_name(parent_id, filename)
        metadata = {"name": filename, "parents": [parent_id]}

        if existing:
            logger.info(
                "Updating Drive file %s (id=%s) in folder %s",
                filename,
                existing["id"],
                parent_id,
                extra={
                    "correlation_id": self.correlation_id,
                    "file_id": existing["id"],
                    "parent_id": parent_id,
                    "drive_file_name": filename,
                },
            )
            return (
                self.service.files()
                .update(
                    fileId=existing["id"],
                    media_body=media,
                    body={"name": filename},
                    supportsAllDrives=True,
                    fields="id, name",
                )
                .execute()
            )

        logger.info(
            "Creating Drive file %s in folder %s (mime=%s)",
            filename,
            parent_id,
            mime_type,
            extra={
                "correlation_id": self.correlation_id,
                "parent_id": parent_id,
                "drive_file_name": filename,
            },
        )
        return (
            self.service.files()
            .create(
                body=metadata,
                media_body=media,
                supportsAllDrives=True,
                fields="id, name",
            )
            .execute()
        )

    def write_text_file(
        self,
        parent_id: str,
        filename: str,
        content: str,
        mime_type: str = "text/plain",
    ) -> Dict:
        """Convenience helper to upload UTF-8 text content to Drive."""
        payload = content.encode("utf-8")
        return self._upload_bytes(parent_id, filename, payload, mime_type)

    def write_json_file(self, parent_id: str, filename: str, data: Dict) -> Dict:
        """Upload structured JSON data with pretty formatting."""
        payload = json.dumps(data, indent=4, sort_keys=True).encode("utf-8")
        return self._upload_bytes(
            parent_id,
            filename,
            payload,
            mime_type="application/json",
        )

    # ------------------------------------------------------------------
    # Move a folder to a new parent
    # ------------------------------------------------------------------
    def move_folder(self, folder_id: str, new_parent_id: str) -> None:
        """
        Move a folder into a new parent folder.
        """
        logger.info(
            "Moving folder %s to parent %s",
            folder_id,
            new_parent_id,
            extra={
                "correlation_id": self.correlation_id,
                "folder_id": folder_id,
                "new_parent_id": new_parent_id
            }
        )
        
        file = (
            self.service.files()
            .get(fileId=folder_id, fields="parents", supportsAllDrives=True)
            .execute()
        )
        prev_parents = ",".join(file.get("parents", []))

        self.service.files().update(
            fileId=folder_id,
            addParents=new_parent_id,
            removeParents=prev_parents,
            fields="id, parents",
            supportsAllDrives=True,
        ).execute()

        logger.info(
            "Successfully moved folder %s to parent %s",
            folder_id,
            new_parent_id,
            extra={
                "correlation_id": self.correlation_id,
                "folder_id": folder_id,
                "new_parent_id": new_parent_id,
                "prev_parents": prev_parents
            }
        )
    # ------------------------------------------------------------------
    # Rename a file in Drive
    # ------------------------------------------------------------------
    def rename_file(self, file_id: str, new_name: str):
        """
        Rename a file (or Google Doc) to a new name.
        """
        logger.info(
            "Renaming file %s to %s",
            file_id,
            new_name,
            extra={
                "correlation_id": self.correlation_id,
                "file_id": file_id,
                "new_name": new_name
            }
        )
        
        self.service.files().update(
            fileId=file_id,
            body={"name": new_name},
            fields="id, name",
            supportsAllDrives=True,
        ).execute()
        
        logger.info(
            "Successfully renamed file %s to %s",
            file_id,
            new_name,
            extra={
                "correlation_id": self.correlation_id,
                "file_id": file_id,
                "new_name": new_name
            }
        )


    # ------------------------------------------------------------------
    # Export Google Docs → text (safe version)
    # ------------------------------------------------------------------
    def export_google_doc_to_text(self, file_id: str) -> str:
        """
        Export a Google Docs file to plain text and return its content.

        If the file is NOT a Google Doc (e.g. PDF, image, etc.), this method:
        - logs a warning
        - returns an empty string
        without raising, so batch jobs don't crash.
        """

        # Check mimeType first
        meta = (
            self.service.files()
            .get(
                fileId=file_id,
                fields="mimeType",
                supportsAllDrives=True,
            )
            .execute()
        )
        mime = meta.get("mimeType", "")
        if mime != "application/vnd.google-apps.document":
            logger.warning(
                "export_google_doc_to_text called on non-Doc (mimeType=%s, fileId=%s). Returning empty text.",
                mime,
                file_id,
                extra={
                    "correlation_id": self.correlation_id,
                    "file_id": file_id,
                    "mime_type": mime
                }
            )
            return ""

        try:
            logger.debug(
                "Exporting Google Doc %s to text",
                file_id,
                extra={"correlation_id": self.correlation_id, "file_id": file_id}
            )
            
            request = self.service.files().export_media(
                fileId=file_id,
                mimeType="text/plain",
            )
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)

            done = False
            while not done:
                status, done = downloader.next_chunk()

            fh.seek(0)
            content = fh.read().decode("utf-8", errors="ignore")
            
            logger.info(
                "Successfully exported Google Doc %s (%d chars)",
                file_id,
                len(content),
                extra={
                    "correlation_id": self.correlation_id,
                    "file_id": file_id,
                    "content_length": len(content)
                }
            )
            
            return content

        except Exception as e:
            logger.warning(
                "export_google_doc_to_text failed for fileId=%s: %s",
                file_id,
                str(e),
                extra={
                    "correlation_id": self.correlation_id,
                    "file_id": file_id,
                    "error": str(e)
                },
                exc_info=True
            )
            return ""
