"""Judge parsing tests. The model is stubbed."""

import pytest

from eval.judge import PredictionJudge, format_case, parse_judgement
from mindtrail.llm import Completion


class StubLLM:
    def __init__(self, text):
        self._text = text
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=400):
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=10, model="stub")


def test_hit_is_parsed():
    verdict = parse_judgement('{"hit": true, "which": 2, "reason": "same ask"}')

    assert verdict.is_hit
    assert verdict.matched_index == 2
    assert verdict.reason == "same ask"


def test_miss_is_parsed():
    assert not parse_judgement('{"hit": false, "which": 0, "reason": "r"}').is_hit


def test_code_fences_are_tolerated():
    assert parse_judgement('```json\n{"hit": true}\n```').is_hit


def test_surrounding_prose_is_tolerated():
    assert parse_judgement('Verdict: {"hit": true} done').is_hit


def test_missing_which_defaults_to_zero():
    assert parse_judgement('{"hit": true}').matched_index == 0


def test_null_which_is_treated_as_zero():
    assert parse_judgement('{"hit": false, "which": null}').matched_index == 0


def test_output_without_json_raises():
    with pytest.raises(ValueError):
        parse_judgement("I cannot grade this.")


def test_output_missing_hit_raises():
    with pytest.raises(ValueError):
        parse_judgement('{"reason": "no verdict"}')


def test_empty_predictions_are_a_miss_without_calling_the_model():
    llm = StubLLM('{"hit": true}')

    verdict = PredictionJudge(llm).judge("actual", [])

    assert not verdict.is_hit
    assert llm.last_user_prompt is None


def test_case_contains_actual_and_numbered_predictions():
    case = format_case("the real question", ["first guess", "second guess"])

    assert "the real question" in case
    assert "1. first guess" in case
    assert "2. second guess" in case
