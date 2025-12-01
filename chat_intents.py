"""Intent classification helpers for chat handlers."""

from enum import Enum, auto


class WorkIntentType(Enum):
    """Work intent buckets for chat prompts."""

    NONE = auto()
    CANDIDATE_QUERY = auto()
    AGGREGATE_QUERY = auto()
    PROCESS_QUERY = auto()


def normalize_text(text: str) -> str:
    """Lowercase and collapse whitespace for quick matching."""
    if not text:
        return ""
    return " ".join(text.lower().strip().split())


def classify_work_intent(text: str) -> WorkIntentType:
    """Classify chat text into work vs non-work categories."""

    t = normalize_text(text)
    if not t:
        return WorkIntentType.NONE

    candidate_keywords = [
        "evaluate",
        "evaluation",
        "summary",
        "status",
        "why did you reject",
        "why reject",
        "why did you move",
        "move to l1",
        "move to l2",
        "on hold",
        "shortlist",
        "review",
        "profile of",
        "feedback for",
    ]

    aggregate_keywords = [
        "list",
        "show",
        "who all",
        "how many",
        "all candidates",
        "all who moved",
        "everyone moved",
        "count of",
        "number of",
        "pipeline for",
    ]

    process_keywords = [
        "what are you designed for",
        "what do you do",
        "what is your role",
        "how do you evaluate",
        "how does l1 work",
        "how does l2 work",
        "how do you decide",
        "what is your process",
        "criteria",
        "scoring rubric",
    ]

    if any(keyword in t for keyword in candidate_keywords):
        return WorkIntentType.CANDIDATE_QUERY

    if any(keyword in t for keyword in aggregate_keywords):
        return WorkIntentType.AGGREGATE_QUERY

    mentions_assistant = "riva" in t or "arjun" in t
    open_question = "do you" in t or "what is" in t
    if any(keyword in t for keyword in process_keywords) or (mentions_assistant and open_question):
        return WorkIntentType.PROCESS_QUERY

    return WorkIntentType.NONE
