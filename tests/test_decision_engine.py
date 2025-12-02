import pytest

from decision_engine import Intent, decide_intent, simple_rule_engine


def test_simple_rule_engine_detects_greeting():
    decision = simple_rule_engine("Hi Riva", "RIVA")
    assert decision is not None
    assert decision.intent == Intent.GREETING


def test_simple_rule_engine_l1_eval_detection():
    decision = simple_rule_engine("Please evaluate Priya", "riva")
    assert decision is not None
    assert decision.intent == Intent.L1_EVAL_SINGLE


def test_decide_intent_fallback_unknown_without_llm():
    decision = decide_intent("nonsense text", "riva", llm_client=None)
    assert decision.intent == Intent.UNKNOWN
    assert decision.confidence == 0.0