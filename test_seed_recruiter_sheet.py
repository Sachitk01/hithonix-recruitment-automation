"""Utility script to seed fake candidates into the recruiter dashboard."""

import datetime
import os

from sheet_service import upsert_role_sheet_row


def main():
    recruiter_sheet_id = os.getenv(
        "RECRUITER_SHEET_FILE_ID",
        "1ZqNfOsyyNs5wBSTU8Xm-IxZAF1X27SpJsDwyaAwvpj4",
    )

    fake_candidates = [
        ("IT Support", "John Doe", "folder-it-1"),
        ("IT Admin", "Jane Admin", "folder-itadmin-1"),
        ("HR Support", "Priya HR", "folder-hr-1"),
    ]

    print("Seeding fake candidates into recruiter dashboard...")

    for role, name, folder_id in fake_candidates:
        upsert_role_sheet_row(
            file_id=recruiter_sheet_id,
            role=role,
            candidate_folder_id=folder_id,
            candidate_name=name,
            current_stage="L1 Completed",
            ai_status="Shortlist",
            ai_recommendation_detail="Strong sample candidate for smoke testing.",
            overall_confidence="High",
            key_strengths=["Test strength A", "Test strength B"],
            key_concerns=["Test concern A"],
            l1_outcome="Pass",
            l2_outcome=None,
            next_action="Move to L2",
            owner="Test Owner",
            feedback_link="https://example.com/feedback",
            folder_link="https://example.com/folder",
            last_updated=datetime.datetime.utcnow(),
        )

    print("Done seeding test candidates.")


if __name__ == "__main__":
    main()
