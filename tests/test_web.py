"""Static site generation tests. Pure string building, no network."""

from mindtrail.memory.store import UNCATEGORIZED, Entry
from mindtrail.web.generate import build_html


def an_entry(
    query,
    topic="",
    key_facts=(),
    summary="s",
    sources=(),
    created_at="2026-01-01",
    kind="research",
):
    return Entry(
        id=query,
        query=query,
        summary=summary,
        sources=sources,
        created_at=created_at,
        topic=topic,
        key_facts=key_facts,
        kind=kind,
    )


def test_empty_store_produces_a_valid_page_with_a_helpful_message():
    html = build_html([])

    assert "<html>" in html
    assert "mindtrail ask" in html


def test_entries_are_grouped_under_their_topic_heading():
    html = build_html([an_entry("q1", topic="Docker"), an_entry("q2", topic="Docker")])

    assert html.count('id="Docker"') == 1
    assert "q1" in html and "q2" in html


def test_untopiced_entries_land_in_uncategorized():
    html = build_html([an_entry("q1", topic="")])

    assert UNCATEGORIZED in html


def test_key_facts_are_rendered_as_list_items():
    html = build_html([an_entry("q1", topic="T", key_facts=("fact one", "fact two"))])

    assert "<li>fact one</li>" in html
    assert "<li>fact two</li>" in html


def test_sources_are_rendered_as_links():
    html = build_html([an_entry("q1", topic="T", sources=("http://a.com",))])

    assert '<a href="http://a.com"' in html


def test_entry_count_is_shown():
    html = build_html([an_entry("q1"), an_entry("q2")])

    assert "2 entries" in html


def test_html_in_fetched_content_is_escaped_not_executed():
    # Summaries and queries can contain arbitrary text pulled from the
    # web; unescaped it becomes live markup in the generated page.
    html = build_html([an_entry("q1", summary="<script>alert(1)</script>")])

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_topics_are_sorted_alphabetically_with_uncategorized_last():
    html = build_html(
        [an_entry("q1", topic="Zebra"), an_entry("q2", topic="Apple"), an_entry("q3")]
    )

    apple_pos = html.index('id="Apple"')
    zebra_pos = html.index('id="Zebra"')
    uncategorized_pos = html.index(f'id="{UNCATEGORIZED}"')
    assert apple_pos < zebra_pos < uncategorized_pos


def test_each_entry_carries_a_lowercase_search_blob():
    html = build_html([an_entry("What Is X", summary="Some Answer")])

    assert 'data-search="what is x some answer"' in html


def test_research_entries_show_no_kind_badge():
    html = build_html([an_entry("q1", kind="research")])

    assert '<span class="kind">' not in html


def test_notes_and_documents_show_a_kind_badge():
    html = build_html([an_entry("q1", kind="note"), an_entry("q2", kind="document")])

    assert '<span class="kind">note</span>' in html
    assert '<span class="kind">document</span>' in html


def test_the_most_recent_advice_entry_is_pinned_above_the_topics():
    html = build_html(
        [
            an_entry("Advice", topic="Advice", kind="advice", summary="stale plan text",
                      created_at="2026-01-01"),
            an_entry("Advice", topic="Advice", kind="advice", summary="fresh plan text",
                      created_at="2026-06-01"),
        ]
    )

    assert '<section class="advice">' in html
    assert "fresh plan text" in html
    assert "stale plan text" not in html


def test_advice_entries_do_not_appear_as_topic_cards():
    html = build_html([an_entry("Advice", topic="Advice", kind="advice", summary="plan")])

    # It should render once, inside the pinned advice box, not again as a
    # regular entry under an "Advice" topic section.
    assert html.count("plan") == 1
    assert 'id="Advice"' not in html


def test_no_advice_section_when_none_exists():
    html = build_html([an_entry("q1")])

    assert '<section class="advice">' not in html
