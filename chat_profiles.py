"""Profile helpers for chat process explanations."""

from typing import Any, Dict, List


def build_profile_text(profile: Dict[str, Any]) -> str:
    mission = profile.get("mission", "")
    scope = profile.get("scope", "")
    signals = profile.get("signals", [])
    outputs = profile.get("outputs", [])

    def format_block(title: str, values: List[str]) -> str:
        if not values:
            return f"{title}: None"
        bullets = "\n".join(f"- {value}" for value in values)
        return f"{title}:\n{bullets}"

    return (
        f"Mission: {mission}\n"
        f"Scope: {scope}\n\n"
        f"{format_block('Signals monitored', signals)}\n\n"
        f"{format_block('Possible outputs', outputs)}"
    )
