"""Per-project next-step highlights. The model is stubbed."""

import pytest

from mindtrail.advice.highlights import (
    generate_highlights,
    highlights_from_json,
    highlights_to_json,
    parse_highlights,
)
from mindtrail.llm import Completion
from mindtrail.memory.store import Entry


class StubLLM:
    def __init__(self, text):
        self._text = text
        self.last_user_prompt = None

    def complete(self, system, user, max_tokens=800):
        self.last_user_prompt = user
        return Completion(text=self._text, tokens=10, model="stub")


VALID = (
    '{"highlights": ['
    '{"headline": "Tighten the resume", "detail": "It still says CpE.", "source": "resume.pdf"},'
    '{"headline": "Apply to Dex", "detail": "Deadline is close.", "source": "PM vs eng chat"}'
    "]}"
)


def an_entry(query, summary="s", kind="research"):
    return Entry(id=query, query=query, summary=summary, sources=(), created_at="t", kind=kind)


def test_plain_json_is_parsed():
    highlights = parse_highlights(VALID)

    assert [h.headline for h in highlights] == ["Tighten the resume", "Apply to Dex"]
    assert highlights[0].source == "resume.pdf"


def test_code_fences_are_tolerated():
    assert len(parse_highlights(f"```json\n{VALID}\n```")) == 2


def test_surrounding_prose_is_tolerated():
    assert len(parse_highlights(f"Here you go:\n{VALID}\nDone.")) == 2


def test_highlights_are_capped_at_five():
    many = '{"highlights": [' + ",".join(
        f'{{"headline": "h{i}"}}' for i in range(9)
    ) + "]}"

    assert len(parse_highlights(many)) == 5


def test_entries_without_a_headline_are_dropped():
    mixed = '{"highlights": [{"headline": ""}, {"headline": "Real"}]}'

    assert [h.headline for h in parse_highlights(mixed)] == ["Real"]


def test_missing_detail_and_source_default_to_empty():
    only = parse_highlights('{"highlights": [{"headline": "H"}]}')[0]

    assert only.detail == "" and only.source == ""


def test_output_without_json_raises():
    with pytest.raises(ValueError):
        parse_highlights("I cannot help.")


def test_empty_list_raises():
    with pytest.raises(ValueError):
        parse_highlights('{"highlights": []}')


def test_generation_includes_project_instructions():
    llm = StubLLM(VALID)

    generate_highlights(llm, [an_entry("q")], instructions="never mention AI")

    assert "never mention AI" in llm.last_user_prompt


def test_generation_without_instructions_omits_the_section():
    llm = StubLLM(VALID)

    generate_highlights(llm, [an_entry("q")])

    assert "PROJECT INSTRUCTIONS" not in llm.last_user_prompt


def test_documents_are_labelled_so_sources_can_cite_them():
    llm = StubLLM(VALID)

    generate_highlights(llm, [an_entry("Document: resume.pdf", kind="document")])

    assert "[DOCUMENT]" in llm.last_user_prompt


def test_an_empty_project_raises_without_calling_the_model():
    llm = StubLLM(VALID)

    with pytest.raises(ValueError, match="nothing in this project"):
        generate_highlights(llm, [])

    assert llm.last_user_prompt is None


def test_previous_advice_is_not_fed_back_in():
    llm = StubLLM(VALID)

    with pytest.raises(ValueError):
        generate_highlights(llm, [an_entry("Advice", kind="advice")])


def test_highlights_round_trip_through_json():
    original = parse_highlights(VALID)

    restored = highlights_from_json(highlights_to_json(original))

    assert [h.headline for h in restored] == [h.headline for h in original]
    assert restored[0].source == original[0].source


def test_unparseable_stored_highlights_degrade_to_empty():
    # A corrupt cache should show nothing, not crash the project page.
    assert highlights_from_json("not json") == []


def test_empty_stored_highlights_are_empty():
    assert highlights_from_json("") == []


# --- priority ---------------------------------------------------------


def test_priority_is_parsed():
    data = '{"highlights": [{"headline": "H", "priority": "now"}]}'

    assert parse_highlights(data)[0].priority == "now"


def test_missing_priority_defaults_to_next():
    assert parse_highlights('{"highlights": [{"headline": "H"}]}')[0].priority == "next"


def test_unrecognised_priority_falls_back():
    data = '{"highlights": [{"headline": "H", "priority": "urgent!!"}]}'

    assert parse_highlights(data)[0].priority == "next"


def test_priority_casing_is_normalised():
    data = '{"highlights": [{"headline": "H", "priority": "NOW"}]}'

    assert parse_highlights(data)[0].priority == "now"


def test_highlights_are_ordered_most_pressing_first():
    data = (
        '{"highlights": ['
        '{"headline": "c", "priority": "later"},'
        '{"headline": "a", "priority": "now"},'
        '{"headline": "b", "priority": "next"}]}'
    )

    assert [h.headline for h in parse_highlights(data)] == ["a", "b", "c"]


def test_ordering_within_a_tier_is_preserved():
    data = (
        '{"highlights": ['
        '{"headline": "first", "priority": "next"},'
        '{"headline": "second", "priority": "next"}]}'
    )

    assert [h.headline for h in parse_highlights(data)] == ["first", "second"]


def test_priority_survives_the_json_round_trip():
    original = parse_highlights('{"highlights": [{"headline": "H", "priority": "now"}]}')

    assert highlights_from_json(highlights_to_json(original))[0].priority == "now"
