import json
import logging
from typing import Any, Dict, List, Optional

import requests

from slack_blocks import build_batch_summary_blocks

slack_logger = logging.getLogger("slack")


def _error_count(summary: Any) -> int:
    errors = getattr(summary, "errors", 0)
    if isinstance(errors, (list, tuple, set)):
        return len(errors)
    try:
        return int(errors or 0)
    except (TypeError, ValueError):
        return 0


class SlackClient:
    def __init__(
        self,
        *,
        name: str,
        bot_token: Optional[str],
        default_channel: Optional[str],
        signing_secret: Optional[str] = None,
    ) -> None:
        self.name = name
        self.bot_token = bot_token
        self.default_channel = default_channel
        self.signing_secret = signing_secret

        if not self.bot_token:
            slack_logger.error(
                "slack_bot_token_missing",
                extra={"bot": self.name},
            )

    # -------------------------------
    # Internal HTTP helper
    # -------------------------------
    def _send(self, endpoint: str, payload: dict, *, return_json: bool = False):
        if not self.bot_token:
            slack_logger.error("slack_token_unavailable", extra={"bot": self.name})
            return None if return_json else False

        url = f"https://slack.com/api/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }

        slack_logger.debug(
            "slack_request",
            extra={"bot": self.name, "endpoint": endpoint, "channel": payload.get("channel")},
        )

        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
        except requests.RequestException as exc:
            slack_logger.error(
                "slack_http_error",
                extra={"bot": self.name, "endpoint": endpoint, "error": str(exc)},
            )
            return None if return_json else False

        try:
            data = response.json()
        except Exception:
            slack_logger.error(
                "slack_non_json_response",
                extra={"bot": self.name, "endpoint": endpoint, "status": response.status_code},
            )
            return None if return_json else False

        if not data.get("ok"):
            slack_logger.error(
                "slack_api_error",
                extra={
                    "bot": self.name,
                    "endpoint": endpoint,
                    "error": data,
                },
            )
            return None if return_json else False

        return data if return_json else True

    def post_message(
        self,
        text: str,
        channel: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None,
    ) -> bool:
        target_channel = channel or self.default_channel
        if not target_channel:
            slack_logger.warning(
                "slack_channel_missing",
                extra={"bot": self.name},
            )
            return False

        payload = {
            "channel": target_channel,
            "text": text,  # Fallback text for notifications
        }
        
        if blocks:
            payload["blocks"] = blocks

        if thread_ts:
            payload["thread_ts"] = thread_ts

        return bool(self._send("chat.postMessage", payload))

    def post_message_get_ts(
        self,
        text: str,
        channel: Optional[str] = None,
        *,
        blocks: Optional[List[Dict[str, Any]]] = None,
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        target_channel = channel or self.default_channel
        if not target_channel:
            slack_logger.warning(
                "slack_channel_missing",
                extra={"bot": self.name},
            )
            return None

        payload = {
            "channel": target_channel,
            "text": text,
        }
        if blocks:
            payload["blocks"] = blocks
        if thread_ts:
            payload["thread_ts"] = thread_ts

        data = self._send("chat.postMessage", payload, return_json=True)
        if not data:
            return None
        return data.get("ts")

    def post_ephemeral(self, text: str, channel: str, user: str) -> bool:
        payload = {
            "channel": channel,
            "user": user,
            "text": text,
        }
        return bool(self._send("chat.postEphemeral", payload))

    def update_message(
        self,
        *,
        channel: str,
        ts: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        payload = {
            "channel": channel,
            "ts": ts,
            "text": text,
        }
        if blocks:
            payload["blocks"] = blocks

        return bool(self._send("chat.update", payload))

    def has_token(self) -> bool:
        return bool(self.bot_token)


class SlackNotifier:
    def __init__(
        self,
        *,
        riva_client: Optional[SlackClient] = None,
        arjun_client: Optional[SlackClient] = None,
    ) -> None:
        self.riva_client = riva_client
        self.arjun_client = arjun_client

    # -------------------------------
    # L1 Batch Notification
    # -------------------------------
    def notify_l1_batch(self, summary):
        # Build Block Kit payload
        blocks = build_batch_summary_blocks(summary, "L1")
        
        # Fallback text for notification preview
        error_total = _error_count(summary)
        fallback_text = (
            f"Riva L1 Batch Complete: {summary.evaluated} evaluated, "
            f"{summary.moved_to_l2} moved to L2, {error_total} errors"
        )
        
        if not self.riva_client:
            slack_logger.warning("slack_riva_client_missing")
            return
        
        self.riva_client.post_message(fallback_text, blocks=blocks)

    # -------------------------------
    # L2 Batch Notification
    # -------------------------------
    def notify_l2_batch(self, summary):
        # Build Block Kit payload
        blocks = build_batch_summary_blocks(summary, "L2")
        
        # Fallback text for notification preview
        error_total = _error_count(summary)
        fallback_text = (
            f"Arjun L2 Batch Complete: {summary.evaluated} evaluated, "
            f"{summary.hires} advanced to final, {error_total} errors"
        )
        
        if not self.arjun_client:
            slack_logger.warning("slack_arjun_client_missing")
            return
        
        self.arjun_client.post_message(fallback_text, blocks=blocks)

    # -------------------------------
    # Slack Test Method
    # -------------------------------
    def send_test_message(self, channel=None):
        if channel is None:
            if self.riva_client and self.riva_client.default_channel:
                channel = self.riva_client.default_channel
            elif self.arjun_client and self.arjun_client.default_channel:
                channel = self.arjun_client.default_channel

        client = self.riva_client or self.arjun_client
        if client and channel:
            client.post_message("🚀 Slack bot test successful! – Hithonix Recruiter Bot", channel)
        else:
            slack_logger.warning("slack_test_message_unable_to_send")

    def _format_candidate_breakdown(
        self,
        candidates,
        *,
        positive_decision: str,
        positive_label: str,
    ) -> str:
        if not candidates:
            return ""

        normalized = [candidate for candidate in candidates if candidate]
        positive = [
            c
            for c in normalized
            if (getattr(c, "decision", "") or "").lower() == positive_decision
        ]
        holds = [
            c
            for c in normalized
            if (getattr(c, "decision", "") or "").lower() == "hold"
        ]
        rejects = [
            c
            for c in normalized
            if (getattr(c, "decision", "") or "").lower() == "reject"
        ]

        sections = []
        if positive:
            sections.append(self._render_candidate_section("🟢", positive_label, positive, show_reason=False))
        if holds:
            sections.append(self._render_candidate_section("🟡", "Hold", holds, show_reason=True))
        if rejects:
            sections.append(self._render_candidate_section("🔴", "Rejected", rejects, show_reason=False))

        return "\n\n".join(section for section in sections if section)

    def _render_candidate_section(self, emoji: str, title: str, entries, *, show_reason: bool) -> str:
        lines = [f"{emoji} *{title}* (`{len(entries)}`)"]
        for entry in entries:
            bullet = f"• *{entry.candidate_name}* — {entry.role}"
            links = []
            if entry.folder_link:
                links.append(f"<{entry.folder_link}|📁>")
            if entry.feedback_link:
                links.append(f"<{entry.feedback_link}|📄>")
            if entry.dashboard_link:
                links.append(f"<{entry.dashboard_link}|📊>")
            if links:
                bullet = f"{bullet} {' '.join(links)}"
            lines.append(bullet)
            if show_reason:
                reason_text = self._format_hold_reason_text(entry)
                if reason_text:
                    lines.append(f"  _Reason: {reason_text}_")
        return "\n".join(lines)

    @staticmethod
    def _format_hold_reason_text(candidate) -> Optional[str]:
        reason_lookup = {
            "manual_review_required": "manual review required",
            "backup_for_l2_capacity": "backup pool for L2 capacity",
            "missing_noncritical_info": "missing non-critical info",
        }
        code = (getattr(candidate, "hold_reason", "") or "").lower()
        base = reason_lookup.get(code)
        detail = getattr(candidate, "reason", None)
        if base and detail:
            if base.lower() in detail.lower():
                return detail
            return f"{base} ({detail})"
        return detail or base
