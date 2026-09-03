"""Roadmap chat: the model proposes actions, never applies them. Stubbed."""

import pytest

from mindtrail.advice.roadmap_chat import chat_about_roadmap, parse_chat_response
from mindtrail.llm import Completion
from mindtrail.organize.roadmaps import RoadmapNode


class StubLLM:
    def __init__(self, text):
        self._text = text
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=900):
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=5, model="stub")


def a_node(node_id="n1", title="X", status="proposed", note=""):
    return RoadmapNode(
        id=node_id, roadmap_id="r1", title=title, detail="", status=status,
        note=note, x=0, y=0, depends_on=(), created_at="t",
    )


PLAIN_REPLY = '{"reply": "Sure, happy to help.", "actions": []}'


def test_plain_reply_with_no_actions():
    result = parse_chat_response(PLAIN_REPLY, {})

    assert result.reply == "Sure, happy to help."
    assert result.actions == ()


def test_code_fences_are_tolerated():
    result = parse_chat_response(f"```json\n{PLAIN_REPLY}\n```", {})

    assert result.reply == "Sure, happy to help."


def test_no_json_raises():
    with pytest.raises(ValueError):
        parse_chat_response("nope", {})


def test_empty_reply_raises():
    with pytest.raises(ValueError):
        parse_chat_response('{"reply": "", "actions": []}', {})


def test_add_node_action_is_parsed():
    text = (
        '{"reply": "I\'ll propose a step.", '
        '"actions": [{"type": "add_node", "title": "Learn SQL", "detail": "d"}]}'
    )

    result = parse_chat_response(text, {})

    assert result.actions[0].type == "add_node"
    assert result.actions[0].title == "Learn SQL"
    assert 'Learn SQL' in result.actions[0].label


def test_update_status_action_needs_a_real_node_id():
    text = (
        '{"reply": "Marking it done.", '
        '"actions": [{"type": "update_status", "node_id": "n1", "status": "done"}]}'
    )

    result = parse_chat_response(text, {"n1": "Real step"})

    assert result.actions[0].status == "done"
    assert "Real step" in result.actions[0].label


def test_action_referencing_an_unknown_node_id_is_dropped():
    text = (
        '{"reply": "Marking it done.", '
        '"actions": [{"type": "update_status", "node_id": "ghost", "status": "done"}]}'
    )

    result = parse_chat_response(text, {"n1": "Real step"})

    assert result.actions == ()


def test_invalid_status_is_dropped():
    text = (
        '{"reply": "ok", '
        '"actions": [{"type": "update_status", "node_id": "n1", "status": "bogus"}]}'
    )

    result = parse_chat_response(text, {"n1": "Real step"})

    assert result.actions == ()


def test_unknown_action_type_is_dropped():
    text = '{"reply": "ok", "actions": [{"type": "delete_everything"}]}'

    result = parse_chat_response(text, {})

    assert result.actions == ()


def test_tidy_action_needs_no_node_id():
    text = '{"reply": "I can clean that up.", "actions": [{"type": "tidy"}]}'

    result = parse_chat_response(text, {})

    assert result.actions[0].type == "tidy"
    assert "Tidy" in result.actions[0].label


def test_actions_are_capped():
    many = ",".join(
        '{"type": "add_node", "title": "t%d"}' % i for i in range(10)
    )
    text = '{"reply": "ok", "actions": [' + many + "]}"

    result = parse_chat_response(text, {})

    assert len(result.actions) == 5


def test_blank_message_is_rejected():
    with pytest.raises(ValueError):
        chat_about_roadmap(StubLLM(PLAIN_REPLY), "Goal", [], "", [], "   ")


def test_current_nodes_are_included_in_the_prompt():
    llm = StubLLM(PLAIN_REPLY)

    chat_about_roadmap(
        llm, "Goal", [a_node(title="Learn Agile", status="accepted")], "", [], "hi"
    )

    assert "Learn Agile" in llm.last_user_prompt
    assert "n1" in llm.last_user_prompt


def test_profile_is_included_when_present():
    llm = StubLLM(PLAIN_REPLY)

    chat_about_roadmap(llm, "Goal", [], "CS student at UCI", [], "hi")

    assert "CS student at UCI" in llm.last_user_prompt


def test_history_is_included_in_the_prompt():
    llm = StubLLM(PLAIN_REPLY)

    chat_about_roadmap(
        llm, "Goal", [], "", [{"role": "user", "content": "earlier question"}], "hi"
    )

    assert "earlier question" in llm.last_user_prompt


def test_current_message_is_included_in_the_prompt():
    llm = StubLLM(PLAIN_REPLY)

    chat_about_roadmap(llm, "Goal", [], "", [], "what should I do next")

    assert "what should I do next" in llm.last_user_prompt
