"""Topic assignment tests. The model is stubbed."""

import pytest

from mindtrail.ingest.topic import TopicExtractor, parse_assignment
from mindtrail.llm import Completion


class StubLLM:
    def __init__(self, text):
        self._text = text
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=400):
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=5, model="stub")


VALID = '{"topic": "Vector Databases", "key_facts": ["fact one", "fact two"]}'


def test_plain_json_is_parsed():
    assignment = parse_assignment(VALID)

    assert assignment.topic == "Vector Databases"
    assert assignment.key_facts == ("fact one", "fact two")


def test_code_fences_are_tolerated():
    assert parse_assignment(f"```json\n{VALID}\n```").topic == "Vector Databases"


def test_surrounding_prose_is_tolerated():
    assert parse_assignment(f"Sure:\n{VALID}\nDone.").topic == "Vector Databases"


def test_empty_topic_raises():
    with pytest.raises(ValueError):
        parse_assignment('{"topic": "", "key_facts": ["f"]}')


def test_missing_topic_raises():
    with pytest.raises(ValueError):
        parse_assignment('{"key_facts": ["f"]}')


def test_blank_facts_are_dropped():
    data = '{"topic": "T", "key_facts": ["real", "", "  "]}'

    assert parse_assignment(data).key_facts == ("real",)


def test_facts_are_capped_at_five():
    many = '{"topic": "T", "key_facts": ["a","b","c","d","e","f","g"]}'

    assert len(parse_assignment(many).key_facts) == 5


def test_output_without_json_raises():
    with pytest.raises(ValueError):
        parse_assignment("I cannot do that.")


def test_no_existing_topics_prompts_for_a_first_one():
    llm = StubLLM(VALID)

    TopicExtractor(llm).extract("q", "a", [])

    assert "propose the first one" in llm.last_user_prompt


def test_existing_topics_are_shown_for_reuse():
    llm = StubLLM(VALID)

    TopicExtractor(llm).extract("q", "a", ["Vector Databases", "Docker"])

    assert "Vector Databases" in llm.last_user_prompt
    assert "Docker" in llm.last_user_prompt
