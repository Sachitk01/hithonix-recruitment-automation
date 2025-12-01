
"""
Slack Block Kit builders for recruitment pipeline notifications.
Provides composable functions to build rich, interactive Slack messages.
"""

from typing import Any, Dict, List, Optional

MAX_CANDIDATES_PER_GROUP = 15


def build_batch_summary_blocks(batch_summary: Any, stage: str) -> List[Dict[str, Any]]:
    """
    Build complete Slack Block Kit payload for a batch summary.
    
    Args:
        batch_summary: L1BatchSummary or L2BatchSummary object
        stage: "L1" or "L2"
    
    Returns:
        List of Slack blocks
    """
    blocks = []
    
    # Header
    blocks.extend(build_status_header(batch_summary, stage))
    
    # Divider
    blocks.append({"type": "divider"})
    
    # Summary stats
    blocks.extend(build_summary_stats(batch_summary, stage))
    
    # Divider
    blocks.append({"type": "divider"})
    
    # Candidate groups by outcome
    candidates = getattr(batch_summary, "candidates", [])
    if candidates:
        blocks.extend(build_candidate_groups(candidates, stage))
    
    # Footer
    blocks.extend(build_footer())
    
    return blocks


def build_status_header(batch_summary: Any, stage: str) -> List[Dict[str, Any]]:
    """Build header block with emoji and summary title."""
    total_seen = getattr(batch_summary, "total_seen", 0)
    
    if stage == "L1":
        emoji = "🟢"
        title = f"Riva L1 Batch Summary ({total_seen} candidates)"
    else:
        emoji = "🟣"
        title = f"Arjun L2 Batch Summary ({total_seen} candidates)"
    
    return [{
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"{emoji} {title}",
            "emoji": True
        }
    }]


def build_summary_stats(batch_summary: Any, stage: str) -> List[Dict[str, Any]]:
    """Build summary statistics section with fields."""
    evaluated = getattr(batch_summary, "evaluated", 0)
    errors = getattr(batch_summary, "errors", 0)
    
    fields = [
        {"type": "mrkdwn", "text": f"*Evaluated:*\n{evaluated}"}
    ]
    
    if stage == "L1":
        moved = getattr(batch_summary, "moved_to_l2", 0)
        rejected = getattr(batch_summary, "rejected_at_l1", 0)
        hold_manual = getattr(batch_summary, "needs_manual_review", 0)
        hold_data = getattr(batch_summary, "data_incomplete", 0)
        
        fields.append({"type": "mrkdwn", "text": f"*Moved to L2:*\n{moved}"})
        fields.append({"type": "mrkdwn", "text": f"*Rejected at L1:*\n{rejected}"})
        
        if hold_manual > 0:
            fields.append({"type": "mrkdwn", "text": f"*Hold (Manual Review):*\n{hold_manual}"})
        if hold_data > 0:
            fields.append({"type": "mrkdwn", "text": f"*Hold (Data Incomplete):*\n{hold_data}"})
    else:
        hires = getattr(batch_summary, "hires", 0)
        rejects = getattr(batch_summary, "rejects", 0)
        hold_manual = getattr(batch_summary, "needs_manual_review", 0)
        hold_data = getattr(batch_summary, "data_incomplete", 0)
        
        fields.append({"type": "mrkdwn", "text": f"*Advanced to Final:*\n{hires}"})
        fields.append({"type": "mrkdwn", "text": f"*Rejected at L2:*\n{rejects}"})
        
        if hold_manual > 0:
            fields.append({"type": "mrkdwn", "text": f"*Hold (Exec Review):*\n{hold_manual}"})
        if hold_data > 0:
            fields.append({"type": "mrkdwn", "text": f"*Hold (Data Incomplete):*\n{hold_data}"})
    
    if errors > 0:
        fields.append({"type": "mrkdwn", "text": f"*Errors:*\n{errors}"})
    
    return [{
        "type": "section",
        "fields": fields
    }]


def build_candidate_groups(candidates: List[Any], stage: str) -> List[Dict[str, Any]]:
    """Build grouped candidate sections by outcome."""
    blocks = []
    
    # Group candidates by decision
    groups = {}
    for candidate in candidates:
        decision = (getattr(candidate, "decision", "") or "").lower()
        if decision not in groups:
            groups[decision] = []
        groups[decision].append(candidate)
    
    if stage == "L1":
        # Order: Moved to L2 → Holds → Rejected
        outcome_configs = [
            ("move_to_l2", "🟢", "Moved to L2"),
            ("hold", "🟡", "Hold – Manual Review"),
            ("reject", "🔴", "Rejected at L1"),
        ]
    else:
        # Order: Advanced → Holds → Rejected
        outcome_configs = [
            ("shortlist", "🟢", "Advanced to Final"),
            ("hold", "🟡", "Hold – Exec Review"),
            ("reject", "🔴", "Rejected at L2"),
        ]
    
    for decision_key, emoji, title in outcome_configs:
        if decision_key in groups and groups[decision_key]:
            blocks.extend(
                build_candidate_group_section(
                    title, emoji, groups[decision_key], decision_key
                )
            )
    
    return blocks


def build_candidate_group_section(
    title: str,
    emoji: str,
    candidates: List[Any],
    outcome: str
) -> List[Dict[str, Any]]:
    """Build a section for a group of candidates with the same outcome."""
    blocks = []
    count = len(candidates)
    
    # Section header
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"{emoji} *{title}* ({count})"
        }
    })
    
    # Candidate rows (limit to MAX_CANDIDATES_PER_GROUP)
    shown_candidates = candidates[:MAX_CANDIDATES_PER_GROUP]
    for candidate in shown_candidates:
        blocks.extend(build_candidate_row(candidate, outcome))
    
    # Show "...and X more" if truncated
    if count > MAX_CANDIDATES_PER_GROUP:
        remaining = count - MAX_CANDIDATES_PER_GROUP
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"_...and {remaining} more candidates_"
            }]
        })
    
    # Add spacing between groups
    blocks.append({"type": "divider"})
    
    return blocks


def build_candidate_row(candidate: Any, outcome: str) -> List[Dict[str, Any]]:
    """Build blocks for a single candidate."""
    blocks = []
    
    name = getattr(candidate, "candidate_name", "Unknown")
    role = getattr(candidate, "role", "")
    
    # Build links
    links = []
    folder_link = getattr(candidate, "folder_link", None)
    if folder_link:
        links.append(f"<{folder_link}|📁 Folder>")
    
    feedback_link = getattr(candidate, "feedback_link", None)
    if feedback_link:
        links.append(f"<{feedback_link}|📄 Docs>")
    
    dashboard_link = getattr(candidate, "dashboard_link", None)
    if dashboard_link:
        links.append(f"<{dashboard_link}|📊 Dashboard>")
    
    # Main candidate line
    text_parts = [f"*{name}*"]
    if role:
        text_parts.append(f"— {role}")
    if links:
        text_parts.append(" • ".join(links))
    
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": " ".join(text_parts)
        }
    })
    
    # Show reason for holds
    if outcome == "hold":
        reason = getattr(candidate, "reason", None)
        hold_reason = getattr(candidate, "hold_reason", None)
        
        reason_text = _format_hold_reason(reason, hold_reason)
        if reason_text:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"_Reason: {reason_text}_"
                }]
            })
    
    return blocks


def build_footer() -> List[Dict[str, Any]]:
    """Build footer with attribution."""
    return [{
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": "Generated by Hithonix Recruitment Automation"
        }]
    }]


def _format_hold_reason(reason: Optional[str], hold_reason: Optional[str]) -> Optional[str]:
    """Format hold reason text."""
    reason_lookup = {
        "manual_review_required": "manual review required",
        "backup_for_l2_capacity": "backup pool for L2 capacity",
        "missing_noncritical_info": "missing non-critical info",
    }
    
    code = (hold_reason or "").lower()
    base = reason_lookup.get(code)
    
    if base and reason:
        if base.lower() in reason.lower():
            return reason
        return f"{base} ({reason})"
    
    return reason or base
