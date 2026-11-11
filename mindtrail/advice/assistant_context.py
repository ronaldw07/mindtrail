"""What the journey assistant reads beyond the journey itself: the few
saved documents and notes that bear on this message, and files sent with
it. Kept small - only what's relevant is added, never everything."""

from __future__ import annotations

DOC_RESULTS = 3
DOC_CHARS = 1200          # of each document or note
MAX_ATTACHMENTS = 5
ATTACH_CHARS = 6000


def document_notes(store, query: str, k: int = DOC_RESULTS) -> str:
    """The saved documents and notes that best match `query`, for the
    model to use if they help. '' if nothing is saved or found."""
    if store is None or not query.strip():
        return ""
    try:
        entries = store.search(query, k=k)
    except Exception:  # noqa: BLE001 - search is a nicety; the chat still answers without it
        return ""
    if not entries:
        return ""
    lines = ["\n\nFROM THEIR SAVED DOCUMENTS AND NOTES (matched to this message; use only what's "
             "relevant, and name specifics like their real projects or courses):"]
    for e in entries:
        text = " ".join(e.summary.split())[:DOC_CHARS]
        lines.append(f"- [{e.query}] {text}")
    return "\n".join(lines)


def with_attachments(message: str, attachments) -> tuple[str, str]:
    """(what the model reads, what the chat saves) for a message sent with
    files: the model gets each file's text, the chat keeps their names."""
    files = [a for a in (attachments if isinstance(attachments, list) else [])
             if isinstance(a, dict) and str(a.get("text", "")).strip()][:MAX_ATTACHMENTS]
    if not files:
        return message, message
    names = [" ".join(str(a.get("name", "file")).split())[:80] for a in files]
    asked = message or "Here's what I sent."
    model = asked + "\n\nFILES THEY SENT (read these):\n" + "\n\n".join(
        f"--- {n} ---\n{str(a['text']).strip()[:ATTACH_CHARS]}" for n, a in zip(names, files))
    saved = asked + "\n" + "\n".join("📎 " + n for n in names)
    return model, saved
