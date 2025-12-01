
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

try:
    from google.cloud import storage
except ImportError:
    storage = None

logger = logging.getLogger(__name__)

class DebugStorageService:
    """
    Handles storage of deep debug payloads (full prompt + response + trace).
    Supports Google Cloud Storage with local filesystem fallback.
    """
    
    def __init__(self, bucket_name: Optional[str] = None):
        self.bucket_name = bucket_name or os.getenv("DEBUG_BUCKET_NAME")
        self.local_debug_dir = os.getenv("LOCAL_DEBUG_DIR", "debug_payloads")
        self.gcs_client = None
        
        if self.bucket_name and storage:
            try:
                self.gcs_client = storage.Client()
                logger.info(f"DebugStorageService initialized with GCS bucket: {self.bucket_name}")
            except Exception as e:
                logger.warning(f"Failed to initialize GCS client: {e}. Falling back to local storage.")
        
        if not self.gcs_client:
            os.makedirs(self.local_debug_dir, exist_ok=True)
            logger.info(f"DebugStorageService using local directory: {self.local_debug_dir}")

    def upload_debug_payload(
        self,
        payload: Dict[str, Any],
        prefix: str = "debug",
        run_id: Optional[str] = None
    ) -> str:
        """
        Uploads a debug payload and returns the URI.
        
        Args:
            payload: The JSON serializable data to store.
            prefix: Prefix for the filename (e.g., 'riva_l1', 'arjun_l2').
            run_id: Correlation ID for the run.
            
        Returns:
            URI string (gs://... or file://...)
        """
        run_id = run_id or str(uuid.uuid4())
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{timestamp}_{run_id}.json"
        
        json_str = json.dumps(payload, indent=2, default=str)
        
        if self.gcs_client and self.bucket_name:
            try:
                bucket = self.gcs_client.bucket(self.bucket_name)
                blob = bucket.blob(filename)
                blob.upload_from_string(json_str, content_type="application/json")
                uri = f"gs://{self.bucket_name}/{filename}"
                logger.info(f"Uploaded debug payload to {uri}")
                return uri
            except Exception as e:
                logger.error(f"GCS upload failed: {e}. Falling back to local.")
                # Fallback to local
        
        # Local storage
        local_path = os.path.join(self.local_debug_dir, filename)
        try:
            with open(local_path, "w") as f:
                f.write(json_str)
            uri = f"file://{os.path.abspath(local_path)}"
            logger.info(f"Saved debug payload to {uri}")
            return uri
        except Exception as e:
            logger.error(f"Local debug save failed: {e}")
            return "error://save_failed"

# Global instance
_debug_storage: Optional[DebugStorageService] = None

def get_debug_storage() -> DebugStorageService:
    global _debug_storage
    if _debug_storage is None:
        _debug_storage = DebugStorageService()
    return _debug_storage
