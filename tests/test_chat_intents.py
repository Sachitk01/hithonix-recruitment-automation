from chat_intents import WorkIntentType, classify_work_intent


def test_classify_work_intent_candidate():
    intent = classify_work_intent("Can you review Priya summary?")
    assert intent == WorkIntentType.CANDIDATE_QUERY


def test_classify_work_intent_aggregate():
    intent = classify_work_intent("List everyone who moved to L2")
    assert intent == WorkIntentType.AGGREGATE_QUERY


def test_classify_work_intent_process():
    intent = classify_work_intent("Riva, what are you designed for?")
    assert intent == WorkIntentType.PROCESS_QUERY


def test_classify_work_intent_none():
    intent = classify_work_intent("How's the weather today?")
    assert intent == WorkIntentType.NONE
