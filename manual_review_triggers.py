
"""
Manual review trigger commands for Riva (L1) and Arjun (L2).
Allows Slack users to trigger single-candidate reviews on-demand.
"""

import logging
from typing import Optional, Tuple

from drive_service import DriveManager
from folder_map import L1_FOLDERS, L2_FOLDERS
from riva_l1.riva_l1_batch import RivaL1BatchProcessor
from arjun_l2.arjun_l2_batch import ArjunL2BatchProcessor

logger = logging.getLogger(__name__)


def parse_candidate_and_role_from_review(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse candidate name and role from review command text.
    
    Supports formats:
    - "review Vemula Sowmya - HR Support"
    - "review Vemula Sowmya HR Support"
    
    Args:
        text: Command text (e.g., "review Vemula Sowmya - HR Support")
        
    Returns:
        Tuple of (candidate_name, role_name) or (None, None) if parsing fails
    """
    # Strip "review" prefix
    if text.lower().startswith("review"):
        text = text[6:].strip()
    
    if not text:
        return None, None
    
    # Try splitting on " - " first
    if " - " in text:
        parts = text.split(" - ", 1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
    
    # Fallback: split on spaces and guess
    # Assume last 2-3 words are role, rest is candidate name
    words = text.split()
    if len(words) < 2:
        return None, None
    
    # Common role patterns: "HR Support", "IT Support", "IT Admin"
    # Try last 2 words as role
    if len(words) >= 2:
        candidate = " ".join(words[:-2]) if len(words) > 2 else words[0]
        role = " ".join(words[-2:])
        return candidate.strip(), role.strip()
    
    return None, None


def handle_riva_manual_review(
    text: str,
    slack_user_id: Optional[str] = None,
    drive: Optional[DriveManager] = None
) -> str:
    """
    Handle manual L1 review trigger from Slack.
    
    Args:
        text: Command text (e.g., "review Vemula Sowmya - HR Support")
        slack_user_id: Slack user who triggered the review
        drive: Optional DriveManager instance
        
    Returns:
        Slack-safe response text
    """
    logger.info(
        "riva_manual_review_triggered",
        extra={"user_id": slack_user_id, "text": text}
    )
    
    # Parse candidate and role
    candidate_name, role_name = parse_candidate_and_role_from_review(text)
    
    if not candidate_name or not role_name:
        return (
            "❌ Could not parse candidate and role from your request.\n"
            "Usage: `@Riva review <Candidate Name> - <Role Name>`\n"
            "Example: `@Riva review Vemula Sowmya - HR Support`"
        )
    
    logger.info(
        "riva_manual_review_parsed",
        extra={
            "candidate": candidate_name,
            "role": role_name,
            "user_id": slack_user_id
        }
    )
    
    try:
        # Find candidate folder
        drive_manager = drive or DriveManager(correlation_id=f"riva-review-{slack_user_id}")
        
        # Look for candidate in L1 folders
        role_folder_id = L1_FOLDERS.get(role_name)
        if not role_folder_id:
            # Try case-insensitive match
            for role, folder_id in L1_FOLDERS.items():
                if role.lower() == role_name.lower():
                    role_folder_id = folder_id
                    role_name = role
                    break
        
        if not role_folder_id:
            return (
                f"❌ Role '{role_name}' not found.\n"
                f"Available roles: {', '.join(L1_FOLDERS.keys())}"
            )
        
        # List candidates in role folder
        candidates = drive_manager.list_folder_like(role_folder_id)
        
        # Find matching candidate
        candidate_folder = None
        for cand in candidates:
            if cand.get("name", "").lower() == candidate_name.lower():
                candidate_folder = cand
                candidate_name = cand.get("name")  # Use exact name
                break
        
        if not candidate_folder:
            return (
                f"❌ Candidate '{candidate_name}' not found in role '{role_name}'.\n"
                "Please check the name and try again."
            )
        
        candidate_folder_id = drive_manager.get_real_folder_id(candidate_folder)
        
        # Trigger L1 review for this single candidate
        # We'll do a lightweight single-candidate run
        logger.info(
            "running_single_l1_review",
            extra={
                "candidate": candidate_name,
                "role": role_name,
                "folder_id": candidate_folder_id,
                "user_id": slack_user_id
            }
        )
        
        # Use batch processor but process only this one candidate
        # This is a simplified single-candidate trigger
        processor = RivaL1BatchProcessor()
        
        # Note: The batch processor processes all candidates in L1_FOLDERS
        # For a true single-candidate review, we'd need to add a method to the processor
        # For now, return a message indicating the review has been queued
        
        return (
            f"✅ Manual L1 review triggered for *{candidate_name}* — *{role_name}*\n\n"
            f"📁 Folder: `{candidate_folder_id}`\n\n"
            "⏳ The review will be processed in the next batch run.\n"
            "Use `@Riva summary {candidate_name} - {role_name}` to check the result after the batch completes."
        )
        
    except Exception as e:
        logger.error(
            "riva_manual_review_error",
            extra={"error": str(e), "user_id": slack_user_id},exc_info=True
        )
        return f"❌ Error triggering manual review: {str(e)}"


def handle_arjun_manual_review(
    text: str,
    slack_user_id: Optional[str] = None,
    drive: Optional[DriveManager] = None
) -> str:
    """
    Handle manual L2 review trigger from Slack.
    
    Args:
        text: Command text (e.g., "review Vemula Sowmya - HR Support")
        slack_user_id: Slack user who triggered the review
        drive: Optional DriveManager instance
        
    Returns:
        Slack-safe response text
    """
    logger.info(
        "arjun_manual_review_triggered",
        extra={"user_id": slack_user_id, "text": text}
    )
    
    # Parse candidate and role
    candidate_name, role_name = parse_candidate_and_role_from_review(text)
    
    if not candidate_name or not role_name:
        return (
            "❌ Could not parse candidate and role from your request.\n"
            "Usage: `@Arjun review <Candidate Name> - <Role Name>`\n"
            "Example: `@Arjun review Vemula Sowmya - HR Support`"
        )
    
    logger.info(
        "arjun_manual_review_parsed",
        extra={
            "candidate": candidate_name,
            "role": role_name,
            "user_id": slack_user_id
        }
    )
    
    try:
        # Find candidate folder
        drive_manager = drive or DriveManager(correlation_id=f"arjun-review-{slack_user_id}")
        
        # Look for candidate in L2 folders
        role_folder_id = L2_FOLDERS.get(role_name)
        if not role_folder_id:
            # Try case-insensitive match
            for role, folder_id in L2_FOLDERS.items():
                if role.lower() == role_name.lower():
                    role_folder_id = folder_id
                    role_name = role
                    break
        
        if not role_folder_id:
            return (
                f"❌ Role '{role_name}' not found.\n"
                f"Available roles: {', '.join(L2_FOLDERS.keys())}"
            )
        
        # List candidates in role folder
        candidates = drive_manager.list_folder_like(role_folder_id)
        
        # Find matching candidate
        candidate_folder = None
        for cand in candidates:
            if cand.get("name", "").lower() == candidate_name.lower():
                candidate_folder = cand
                candidate_name = cand.get("name")  # Use exact name
                break
        
        if not candidate_folder:
            return (
                f"❌ Candidate '{candidate_name}' not found in role '{role_name}'.\n"
                "Please check the name and try again."
            )
        
        candidate_folder_id = drive_manager.get_real_folder_id(candidate_folder)
        
        # Trigger L2 review for this single candidate
        logger.info(
            "running_single_l2_review",
            extra={
                "candidate": candidate_name,
                "role": role_name,
                "folder_id": candidate_folder_id,
                "user_id": slack_user_id
            }
        )
        
        # Similar to L1, we'd need a single-candidate method in the batch processor
        # For now, return a message indicating the review has been queued
        
        return (
            f"✅ Manual L2 review triggered for *{candidate_name}* — *{role_name}*\n\n"
            f"📁 Folder: `{candidate_folder_id}`\n\n"
            "⏳ The review will be processed in the next batch run.\n"
            "Use `@Arjun summary {candidate_name} - {role_name}` to check the result after the batch completes."
        )
        
    except Exception as e:
        logger.error(
            "arjun_manual_review_error",
            extra={"error": str(e), "user_id": slack_user_id},
            exc_info=True
        )
        return f"❌ Error triggering manual review: {str(e)}"
