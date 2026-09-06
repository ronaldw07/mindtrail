"""Daily brief generation tests. The model is stubbed - this is the only
LLM call in the daily summary feature, and it must never fire on its own."""

import pytest

from mindtrail.advice.daily_brief import generate_daily_brief
from mindtrail.llm import Completion


class StubLLM:
    def __init__(self, text="focus on X today"):
        self._text = text
        self.last_user_prompt = None
        self.calls = 0

    def complete(self, system, user, max_tokens=900):
        self.calls += 1
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=9, model="stub")


def a_due_item(title="Apply", project_name="Career", due_date="2026-09-05"):
    return {
        "project_id": "p1", "project_name": project_name, "node_id": "n1",
        "title": title, "due_date": due_date, "is_recurring": False, "bucket": "today",
    }


def test_brief_is_generated_from_a_non_empty_summary():
    summary = {"empty": False, "due": [a_due_item()], "unblocked": [], "recurring": []}
    llm = StubLLM()

    brief = generate_daily_brief(llm, summary)

    assert brief.text == "focus on X today"
    assert llm.calls == 1


def test_empty_summary_raises_without_calling_the_model():
    summary = {"empty": True, "due": [], "unblocked": [], "recurring": []}
    llm = StubLLM()

    with pytest.raises(ValueError, match="nothing"):
        generate_daily_brief(llm, summary)

    assert llm.calls == 0


def test_due_unblocked_and_recurring_items_all_appear_in_the_prompt():
    summary = {
        "empty": False,
        "due": [a_due_item(title="Overdue task")],
        "unblocked": [
            {"project_id": "p1", "project_name": "Career", "node_id": "n2",
             "title": "Newly ready", "due_date": ""}
        ],
        "recurring": [
            {"project_id": "p1", "project_name": "Career", "node_id": "n3",
             "title": "Weekly review", "due_date": "2026-09-10", "is_recurring": True}
        ],
    }
    llm = StubLLM()

    generate_daily_brief(llm, summary)

    assert "Overdue task" in llm.last_user_prompt
    assert "Newly ready" in llm.last_user_prompt
    assert "Weekly review" in llm.last_user_prompt
