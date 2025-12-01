# riva_output_writer.py

import io
from googleapiclient.http import MediaIoBaseUpload

from drive_service import DriveManager
from docx_builder import (
    build_riva_report_docx,
    build_l2_questionnaire
)

class RivaOutputWriter:
    """
    Handles exporting Riva results as DOCX files into the candidate's folder.
    """

    REPORT_NAME = "05_Riva_L1_Evaluation_Report.docx"
    QUESTIONNAIRE_NAME = "06_L2_Questionnaire.docx"

    def __init__(self):
        self.drive = DriveManager()

    def _upload_bytes(self, folder_id: str, filename: str, mime_type: str, data: bytes):
        """
        Upload raw bytes to Google Drive under a given filename.
        """

        file_metadata = {
            "name": filename,
            "parents": [folder_id]
        }

        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, resumable=False)

        self.drive.service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id",
            supportsAllDrives=True
        ).execute()

        print(f"[RivaOutputWriter] Uploaded {filename} to folder {folder_id}")

    # -----------------------------------------------------------
    #   Public Methods
    # -----------------------------------------------------------

    @classmethod
    def generate_riva_report(cls, folder_id: str, result):
        """
        Generate L1 evaluation report and upload into Drive.
        """
        writer = cls()
        doc_bytes = build_riva_report_docx(result)

        writer._upload_bytes(
            folder_id=folder_id,
            filename=cls.REPORT_NAME,
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            data=doc_bytes
        )

    @classmethod
    def generate_l2_questionnaire(cls, folder_id: str, result):
        """
        Generate a personalized L2 questionnaire based on the L1 evaluation.
        """
        writer = cls()
        doc_bytes = build_l2_questionnaire(result)

        writer._upload_bytes(
            folder_id=folder_id,
            filename=cls.QUESTIONNAIRE_NAME,
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            data=doc_bytes
        )
