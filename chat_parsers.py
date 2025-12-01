"""Shared chat parsing helpers for candidate and role extraction."""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Optional, Tuple

NOISE_PREFIXES = [
    "hey riva",
    "hi riva",
    "hello riva",
    "riva",
    "hey arjun",
    "hi arjun",
    "hello arjun",
    "arjun",
    "can you",
    "can u",
    "please",
    "plz",
]


def build_role_lookup(role_names: Iterable[str]) -> Mapping[str, str]:
    """Create a lowercase lookup for role mentions."""
    return {role.lower(): role for role in role_names}


def try_extract_candidate_and_role_from_text(
    text: str,
    role_lookup: Mapping[str, str],
    command_prefixes: Tuple[str, ...],
) -> Tuple[Optional[str], Optional[str]]:
    if not text:
        return None, None

    raw = text.replace("—", "-").replace("–", "-")
    raw = re.sub(r"[?,]", " ", raw)
    raw = " ".join(raw.split())
    stripped = _strip_bot_noise(raw)

    pattern = re.compile(
        r"(?:evaluate|review|check|assess)\s+(?P<name>.+?)\s+(?:of|for)\s+(?P<role>.+)$",
        re.IGNORECASE,
    )
    pattern_match = pattern.search(stripped)
    if pattern_match:
        candidate = pattern_match.group("name").strip(" .-")
        role = pattern_match.group("role").strip(" .-")
        canonical_role = _normalize_role(role, role_lookup)
        if candidate and canonical_role:
            return candidate, canonical_role

    sanitized = stripped
    sanitized = re.sub(r"[?,]", " ", sanitized)
    sanitized = " ".join(sanitized.split())
    fragment = sanitized
    fragment_lower = fragment.lower()

    for prefix in command_prefixes:
        prefix_with_space = f"{prefix} "
        prefix_lower = prefix_with_space.lower()
        if fragment_lower.startswith(prefix_lower):
            fragment = fragment[len(prefix_with_space):].lstrip()
            fragment_lower = fragment_lower[len(prefix_lower):].lstrip()
            break

    # "name of role"
    of_index = fragment_lower.find(" of ")
    if of_index != -1:
        candidate_part = fragment[:of_index]
        role_part = fragment[of_index + len(" of ") :]
        candidate = candidate_part.strip(" -:")
        role = _normalize_role(role_part, role_lookup)
        if candidate and role:
            return candidate, role

    # "name for role"
    for_index = fragment_lower.find(" for ")
    if for_index != -1:
        candidate_part = fragment[:for_index]
        role_part = fragment[for_index + len(" for ") :]
        candidate = candidate_part.strip(" -:")
        role = _normalize_role(role_part, role_lookup)
        if candidate and role:
            return candidate, role

    # "name - role"
    dash_index = fragment.find(" - ")
    if dash_index != -1:
        candidate_part = fragment[:dash_index]
        role_part = fragment[dash_index + len(" - ") :]
        candidate = candidate_part.strip()
        role = _normalize_role(role_part, role_lookup)
        if candidate and role:
            return candidate, role

    words = fragment.split()
    if len(words) >= 2:
        for split_index in range(len(words) - 1, 0, -1):
            candidate_words = words[:split_index]
            role_words = words[split_index:]
            role = _normalize_role(" ".join(role_words), role_lookup)
            candidate = " ".join(candidate_words).strip()
            if role and candidate:
                return candidate, role

    return None, None


def _strip_bot_noise(text: str) -> str:
    if not text:
        return ""

    working = text.strip()
    while working:
        lowered = working.lower()
        matched = False
        for prefix in NOISE_PREFIXES:
            if lowered.startswith(prefix):
                working = working[len(prefix):].lstrip()
                matched = True
                break
        if not matched:
            break
    return working


def try_extract_role_from_text(text: str, role_lookup: Mapping[str, str]) -> Optional[str]:
    if not text:
        return None
    lowered = text.lower()
    for role_lower, canonical in role_lookup.items():
        if role_lower in lowered:
            return canonical
    return None


def _normalize_role(role_text: str, role_lookup: Mapping[str, str]) -> Optional[str]:
    cleaned = " ".join(role_text.replace("role", "").strip().split())
    if not cleaned:
        return None
    cleaned_lower = cleaned.lower()
    if cleaned_lower in role_lookup:
        return role_lookup[cleaned_lower]

    for role_lower, canonical in role_lookup.items():
        if cleaned_lower.endswith(role_lower) or role_lower.endswith(cleaned_lower):
            return canonical
    return None
