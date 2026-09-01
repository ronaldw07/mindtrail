"""Generate a static HTML page grouping research by topic.

A static file rather than a running server: nothing to keep alive, no
port to manage, and it opens in a regular browser like any local file.
"""

from __future__ import annotations

from collections import defaultdict
from html import escape

from mindtrail.memory.store import UNCATEGORIZED, Entry

_STYLE = """
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 860px;
         margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
  h1 { margin-bottom: 0.25rem; }
  .subtitle { color: #767676; margin-top: 0; }
  #search { width: 100%; padding: 0.6rem; font-size: 1rem; box-sizing: border-box;
            margin: 1rem 0 2rem; border: 1px solid #ccc; border-radius: 6px; }
  .topic { margin-bottom: 2.5rem; }
  .topic h2 { border-bottom: 2px solid currentColor; padding-bottom: 0.3rem; }
  .entry { margin: 1rem 0; padding: 1rem; border: 1px solid #d0d0d0;
           border-radius: 8px; }
  .entry .question { font-weight: 600; }
  .entry .date { color: #767676; font-size: 0.85rem; }
  .entry ul.facts { margin: 0.6rem 0; padding-left: 1.2rem; }
  .entry details { margin-top: 0.6rem; }
  .entry .sources { margin-top: 0.6rem; font-size: 0.9rem; }
  .entry .sources a { display: block; }
  .hidden { display: none; }
"""

_SCRIPT = """
  const box = document.getElementById('search');
  box.addEventListener('input', () => {
    const q = box.value.toLowerCase();
    document.querySelectorAll('.entry').forEach(el => {
      el.classList.toggle('hidden', q && !el.dataset.search.includes(q));
    });
    document.querySelectorAll('.topic').forEach(section => {
      const anyVisible = section.querySelector('.entry:not(.hidden)');
      section.classList.toggle('hidden', !anyVisible);
    });
  });
"""


def _group_by_topic(entries: list[Entry]) -> dict[str, list[Entry]]:
    groups: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        groups[entry.topic or UNCATEGORIZED].append(entry)
    return groups


def _render_entry(entry: Entry) -> str:
    facts = "".join(f"<li>{escape(f)}</li>" for f in entry.key_facts)
    facts_html = f'<ul class="facts">{facts}</ul>' if facts else ""

    sources = "".join(
        f'<a href="{escape(u)}" target="_blank" rel="noopener">{escape(u)}</a>'
        for u in entry.sources
    )
    sources_html = f'<div class="sources">{sources}</div>' if sources else ""

    search_blob = escape(f"{entry.query} {entry.summary}".lower(), quote=True)

    return f"""
    <div class="entry" data-search="{search_blob}">
      <div class="question">{escape(entry.query)}</div>
      <div class="date">{escape(entry.created_at[:10])}</div>
      {facts_html}
      <details><summary>full answer</summary><p>{escape(entry.summary)}</p></details>
      {sources_html}
    </div>"""


def _render_topic(topic: str, entries: list[Entry]) -> str:
    ordered = sorted(entries, key=lambda e: e.created_at, reverse=True)
    body = "".join(_render_entry(e) for e in ordered)
    return f"""
  <section class="topic" id="{escape(topic.replace(' ', '-'))}">
    <h2>{escape(topic)} <small>({len(entries)})</small></h2>
    {body}
  </section>"""


def build_html(entries: list[Entry]) -> str:
    """Render the full page. Empty input still produces a valid page."""
    if not entries:
        body = "<p>Nothing researched yet. Run <code>mindtrail ask</code> first.</p>"
    else:
        groups = _group_by_topic(entries)
        ordered_topics = sorted(
            groups, key=lambda t: (t == UNCATEGORIZED, t.lower())
        )
        body = "".join(_render_topic(t, groups[t]) for t in ordered_topics)

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>mindtrail</title>
  <style>{_STYLE}</style>
</head>
<body>
  <h1>mindtrail</h1>
  <p class="subtitle">{len(entries)} researched question(s)</p>
  <input id="search" type="search" placeholder="filter by keyword...">
  {body}
  <script>{_SCRIPT}</script>
</body>
</html>"""
