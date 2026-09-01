"""Prediction tests. Parsing is the part that can silently be wrong."""

import pytest

from mindtrail.memory.store import Entry
from mindtrail.predict.next_query import (
    NextQueryPredictor,
    format_trajectory,
    parse_predictions,
)
from mindtrail.llm import Completion


class StubLLM:
    def __init__(self, text):
        self._text = text
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=900):
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=10, model="stub")


def an_entry(query, created_at):
    return Entry(
        id=query, query=query, summary="s", sources=(), created_at=created_at
    )


VALID = '{"predictions":[{"question":"Q1","reasoning":"R1"},{"question":"Q2","reasoning":"R2"}]}'


def test_plain_json_is_parsed():
    predictions = parse_predictions(VALID)

    assert [p.question for p in predictions] == ["Q1", "Q2"]


def test_json_wrapped_in_code_fences_is_parsed():
    predictions = parse_predictions(f"```json\n{VALID}\n```")

    assert predictions[0].question == "Q1"


def test_json_with_surrounding_prose_is_parsed():
    predictions = parse_predictions(f"Here you go:\n{VALID}\nHope that helps.")

    assert predictions[0].question == "Q1"


def test_at_most_three_predictions_are_returned():
    many = '{"predictions":[' + ",".join(
        f'{{"question":"Q{i}","reasoning":"r"}}' for i in range(6)
    ) + "]}"

    assert len(parse_predictions(many)) == 3


def test_entries_without_a_question_are_dropped():
    mixed = '{"predictions":[{"question":"","reasoning":"r"},{"question":"Real","reasoning":"r"}]}'

    assert [p.question for p in parse_predictions(mixed)] == ["Real"]


def test_missing_reasoning_defaults_to_empty():
    assert parse_predictions('{"predictions":[{"question":"Q"}]}')[0].reasoning == ""


def test_output_without_json_raises():
    with pytest.raises(ValueError):
        parse_predictions("I cannot help with that.")


def test_empty_prediction_list_raises():
    with pytest.raises(ValueError):
        parse_predictions('{"predictions":[]}')


def test_trajectory_is_ordered_oldest_first():
    entries = [
        an_entry("newest", "2026-03-01"),
        an_entry("oldest", "2026-01-01"),
    ]

    assert format_trajectory(entries) == "1. oldest\n2. newest"


def test_predictor_sends_the_trajectory_to_the_model():
    llm = StubLLM(VALID)

    NextQueryPredictor(llm).predict([an_entry("my question", "2026-01-01")])

    assert "my question" in llm.last_user_prompt


def test_predicting_without_history_raises():
    with pytest.raises(ValueError):
        NextQueryPredictor(StubLLM(VALID)).predict([])
