# memory_config.py
"""
Configuration for the Talent Intelligence Memory Layer.
"""

import os
from typing import Literal

# Memory feature flags
MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "true").lower() == "true"
MEMORY_SCOPE = os.getenv("MEMORY_SCOPE", "full")  # candidate_only | role_only | full
MEMORY_DB_URL = os.getenv("MEMORY_DB_URL", "sqlite:///./talent_memory.db")

# Validation
VALID_SCOPES = {"candidate_only", "role_only", "full"}
if MEMORY_SCOPE not in VALID_SCOPES:
    raise ValueError(f"MEMORY_SCOPE must be one of {VALID_SCOPES}, got {MEMORY_SCOPE}")


def is_memory_enabled() -> bool:
    """Check if memory is enabled."""
    return MEMORY_ENABLED


def should_use_candidate_memory() -> bool:
    """Check if candidate memory should be used."""
    return MEMORY_ENABLED and MEMORY_SCOPE in {"candidate_only", "full"}


def should_use_role_memory() -> bool:
    """Check if role memory should be used."""
    return MEMORY_ENABLED and MEMORY_SCOPE in {"role_only", "full"}
