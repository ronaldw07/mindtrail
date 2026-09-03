"""Project chat: the model proposes a rename/instructions change, never
applies it. Stubbed."""

import pytest

from mindtrail.advice.project_chat import chat_about_project, parse_chat_response
from mindtrail.llm import Completion


class StubLLM:
    def __init__(self, text):
        self._text = text
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=700):
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=5, model="stub")


PLAIN_REPLY = '{"reply": "Sure, happy to help.", "actions": []}'


def test_plain_reply_with_no_actions():
    result = parse_chat_response(PLAIN_REPLY)

    assert result.reply == "Sure, happy to help."
    assert result.actions == ()


def test_no_json_raises():
    with pytest.raises(ValueError):
        parse_chat_response("nope")


def test_empty_reply_raises():
    with pytest.raises(ValueError):
        parse_chat_response('{"reply": "", "actions": []}')


def test_rename_only_action():
    text = (
        '{"reply": "I\'ll propose a rename.", '
        '"actions": [{"type": "update_project", "name": "Career Search"}]}'
    )

    result = parse_chat_response(text)

    assert result.actions[0].name == "Career Search"
    assert result.actions[0].instructions is None
    assert "rename" in result.actions[0].label


def test_instructions_only_action():
    text = (
        '{"reply": "ok", "actions": [{"type": "update_project", '
        '"instructions": "cite only primary sources"}]}'
    )

    result = parse_chat_response(text)

    assert result.actions[0].name is None
    assert result.actions[0].instructions == "cite only primary sources"


def test_action_with_neither_field_is_dropped():
    text = '{"reply": "ok", "actions": [{"type": "update_project"}]}'

    result = parse_chat_response(text)

    assert result.actions == ()


def test_unknown_action_type_is_dropped():
    text = '{"reply": "ok", "actions": [{"type": "delete_everything"}]}'

    result = parse_chat_response(text)

    assert result.actions == ()


def test_blank_message_is_rejected():
    with pytest.raises(ValueError):
        chat_about_project(StubLLM(PLAIN_REPLY), "Career", "", "", [], "   ")


def test_project_name_and_instructions_are_in_the_prompt():
    llm = StubLLM(PLAIN_REPLY)

    chat_about_project(llm, "Career", "be concise", "", [], "hi")

    assert "Career" in llm.last_user_prompt
    assert "be concise" in llm.last_user_prompt


def test_profile_is_included_when_present():
    llm = StubLLM(PLAIN_REPLY)

    chat_about_project(llm, "Career", "", "CS student at UCI", [], "hi")

    assert "CS student at UCI" in llm.last_user_prompt


def test_history_is_included_in_the_prompt():
    llm = StubLLM(PLAIN_REPLY)

    chat_about_project(
        llm, "Career", "", "", [{"role": "user", "content": "earlier question"}], "hi"
    )

    assert "earlier question" in llm.last_user_prompt
