"""Roadmap generation tests. The model is stubbed."""

import pytest

from mindtrail.advice.roadmap_gen import generate_roadmap, parse_proposal
from mindtrail.llm import Completion
from mindtrail.memory.store import Entry
from mindtrail.organize.roadmaps import RoadmapNode


class StubLLM:
    def __init__(self, text):
        self._text = text
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=1800):
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=5, model="stub")


VALID = (
    '{"nodes": ['
    '{"title": "Learn Agile", "detail": "Read the guide.", "depends_on": []},'
    '{"title": "Apply to APM", "detail": "Once ready.", "depends_on": ["Learn Agile"]}'
    "]}"
)


def a_node(title="X", status="proposed", note=""):
    return RoadmapNode(
        id=title, roadmap_id="r1", title=title, detail="", status=status,
        note=note, x=0, y=0, depends_on=(), created_at="t",
    )


def an_entry(query, summary="s", kind="research"):
    return Entry(id=query, query=query, summary=summary, sources=(), created_at="t", kind=kind)


def test_plain_json_is_parsed():
    nodes = parse_proposal(VALID)

    assert [n.title for n in nodes] == ["Learn Agile", "Apply to APM"]
    assert nodes[1].depends_on == ("Learn Agile",)


def test_code_fences_are_tolerated():
    assert len(parse_proposal(f"```json\n{VALID}\n```")) == 2


def test_capped_at_max_nodes():
    many = '{"nodes": [' + ",".join(f'{{"title": "t{i}"}}' for i in range(12)) + "]}"

    assert len(parse_proposal(many)) == 8


def test_entries_without_a_title_are_dropped():
    mixed = '{"nodes": [{"title": ""}, {"title": "Real"}]}'

    assert [n.title for n in parse_proposal(mixed)] == ["Real"]


def test_no_json_raises():
    with pytest.raises(ValueError):
        parse_proposal("nope")


def test_empty_list_raises():
    with pytest.raises(ValueError):
        parse_proposal('{"nodes": []}')


def test_blank_goal_is_rejected():
    with pytest.raises(ValueError):
        generate_roadmap(StubLLM(VALID), "   ")


def test_profile_is_included_when_present():
    llm = StubLLM(VALID)

    generate_roadmap(llm, "Become a PM", profile="CS student at UCI")

    assert "CS student at UCI" in llm.last_user_prompt


def test_profile_section_omitted_when_absent():
    llm = StubLLM(VALID)

    generate_roadmap(llm, "Become a PM")

    assert "USER PROFILE" not in llm.last_user_prompt


def test_accepted_nodes_are_shown_so_they_are_not_reproposed():
    llm = StubLLM(VALID)

    generate_roadmap(llm, "Goal", existing_nodes=[a_node("Learn Agile", "accepted")])

    assert "ACCEPTED" in llm.last_user_prompt
    assert "Learn Agile" in llm.last_user_prompt


def test_rejected_nodes_are_shown_too():
    llm = StubLLM(VALID)

    generate_roadmap(llm, "Goal", existing_nodes=[a_node("Get a cert", "rejected")])

    assert "REJECTED" in llm.last_user_prompt


def test_proposed_nodes_are_not_echoed_back():
    # Only decided nodes matter for planning around; still-proposed ones
    # are what generation is meant to replace.
    llm = StubLLM(VALID)

    generate_roadmap(llm, "Goal", existing_nodes=[a_node("Old idea", "proposed")])

    assert "Old idea" not in llm.last_user_prompt


def test_node_notes_are_passed_through():
    llm = StubLLM(VALID)

    generate_roadmap(
        llm, "Goal",
        existing_nodes=[a_node("X", "accepted", note="no certifications please")],
    )

    assert "no certifications please" in llm.last_user_prompt


def test_project_material_is_included():
    llm = StubLLM(VALID)

    generate_roadmap(llm, "Goal", project_entries=[an_entry("what is PM")])

    assert "what is PM" in llm.last_user_prompt


def test_advice_entries_are_excluded_from_material():
    llm = StubLLM(VALID)

    generate_roadmap(llm, "Goal", project_entries=[an_entry("Advice", kind="advice")])

    assert "PROJECT MATERIAL" not in llm.last_user_prompt
