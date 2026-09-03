"""Profile chat: the model proposes a full replacement, never applies it.
Stubbed."""

import pytest

from mindtrail.advice.profile_chat import chat_about_profile, parse_chat_response
from mindtrail.llm import Completion


class StubLLM:
    def __init__(self, text):
        self._text = text
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=700):
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=5, model="stub")


PLAIN_REPLY = '{"reply": "Tell me more about your background.", "actions": []}'


def test_plain_reply_with_no_actions():
    result = parse_chat_response(PLAIN_REPLY)

    assert result.reply == "Tell me more about your background."
    assert result.actions == ()


def test_no_json_raises():
    with pytest.raises(ValueError):
        parse_chat_response("nope")


def test_empty_reply_raises():
    with pytest.raises(ValueError):
        parse_chat_response('{"reply": "", "actions": []}')


def test_update_profile_action_is_parsed():
    text = (
        '{"reply": "Here is a draft.", "actions": [{"type": "update_profile", '
        '"content": "CS student at UCI, targeting PM roles"}]}'
    )

    result = parse_chat_response(text)

    assert result.actions[0].content == "CS student at UCI, targeting PM roles"
    assert result.actions[0].label


def test_action_with_blank_content_is_dropped():
    text = '{"reply": "ok", "actions": [{"type": "update_profile", "content": "  "}]}'

    result = parse_chat_response(text)

    assert result.actions == ()


def test_unknown_action_type_is_dropped():
    text = '{"reply": "ok", "actions": [{"type": "delete_everything"}]}'

    result = parse_chat_response(text)

    assert result.actions == ()


def test_only_the_first_action_is_kept():
    text = (
        '{"reply": "ok", "actions": ['
        '{"type": "update_profile", "content": "first"}, '
        '{"type": "update_profile", "content": "second"}]}'
    )

    result = parse_chat_response(text)

    assert len(result.actions) == 1
    assert result.actions[0].content == "first"


def test_blank_message_is_rejected():
    with pytest.raises(ValueError):
        chat_about_profile(StubLLM(PLAIN_REPLY), "", [], "   ")


def test_current_content_is_in_the_prompt():
    llm = StubLLM(PLAIN_REPLY)

    chat_about_profile(llm, "CS student at UCI", [], "hi")

    assert "CS student at UCI" in llm.last_user_prompt


def test_history_is_included_in_the_prompt():
    llm = StubLLM(PLAIN_REPLY)

    chat_about_profile(llm, "", [{"role": "user", "content": "earlier question"}], "hi")

    assert "earlier question" in llm.last_user_prompt


def test_current_message_is_included_in_the_prompt():
    llm = StubLLM(PLAIN_REPLY)

    chat_about_profile(llm, "", [], "what should I add")

    assert "what should I add" in llm.last_user_prompt
