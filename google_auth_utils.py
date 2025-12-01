import json
import logging
import os
from typing import Optional, Sequence, Tuple

from google.oauth2 import service_account

try:  # pragma: no cover - optional dependency
    from google.cloud import secretmanager
except ImportError:  # pragma: no cover
    secretmanager = None


logger = logging.getLogger(__name__)
_secret_client = None


def _fetch_secret_payload(secret_ref: str) -> Optional[str]:
    if not secret_ref.startswith("gcp-secret://"):
        return None

    if secretmanager is None:
        logger.warning(
            "google-cloud-secret-manager not installed; cannot resolve %s",
            secret_ref,
        )
        return None

    project_id = os.getenv("GCP_SECRET_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        logger.warning(
            "Secret Manager project id missing while resolving %s",
            secret_ref,
        )
        return None

    secret_name = secret_ref.replace("gcp-secret://", "", 1)

    global _secret_client
    if _secret_client is None:
        _secret_client = secretmanager.SecretManagerServiceClient()

    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    try:
        response = _secret_client.access_secret_version(name=name)
        return response.payload.data.decode("utf-8")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to load secret %s: %s", secret_ref, exc)
        return None


def load_service_account_credentials(
    scopes: Sequence[str],
) -> Optional[Tuple[service_account.Credentials, Optional[str]]]:
    """Load service account credentials using Drive/Sheets precedence rules."""

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    sa_json = os.getenv("RIVA_SA_JSON")
    sa_inline = os.getenv("RIVA_SA_JSON_CONTENT")

    if creds_path:
        if os.path.exists(creds_path):
            creds = service_account.Credentials.from_service_account_file(
                creds_path, scopes=scopes
            )
            return creds, getattr(creds, "project_id", None)
        logger.warning("GOOGLE_APPLICATION_CREDENTIALS path %s does not exist", creds_path)

    if sa_inline:
        payload = sa_inline
        if sa_inline.startswith("gcp-secret://"):
            payload = _fetch_secret_payload(sa_inline)
            if payload is None:
                logger.warning("Failed to resolve secret for %s", sa_inline)
                payload = None
        if payload:
            info = json.loads(payload)
            creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
            return creds, info.get("project_id")

    if sa_json:
        if os.path.exists(sa_json):
            creds = service_account.Credentials.from_service_account_file(sa_json, scopes=scopes)
            return creds, getattr(creds, "project_id", None)
        try:
            info = json.loads(sa_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
            return creds, info.get("project_id")
        except json.JSONDecodeError:
            logger.warning("RIVA_SA_JSON is not valid JSON or file path")

    logger.warning(
        "Service account credentials not configured; GOOGLE_APPLICATION_CREDENTIALS, "
        "RIVA_SA_JSON, and RIVA_SA_JSON_CONTENT all empty.",
    )
    return None
