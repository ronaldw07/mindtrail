"""Files sent to the journey assistant: read into text for the next
message, and PDFs and text files kept in memory so later chats can find
them too."""

from __future__ import annotations

from pathlib import Path

from mindtrail.advice import attachments
from mindtrail.ingest.documents import DocumentError
from mindtrail.llm import LLMError


def handle_attach(store, llm, body: dict) -> dict:
    """{name, data: base64} -> {name, kind, text, saved}."""
    name = Path(str(body.get("name", "")).strip()).name
    kind = attachments.kind_of(name)
    try:
        if not kind:
            raise ValueError("send a screenshot or photo, a PDF, or a text file")
        text = attachments.read_attachment(llm, name, attachments.decode(str(body.get("data", ""))))
    except (ValueError, LLMError, DocumentError) as exc:
        return {"error": str(exc)}
    if not text:
        return {"error": "couldn't find anything to read in that file"}
    saved = False
    if kind != "image" and store is not None:
        store.add(f"Document: {name}", text, [name], kind="document")
        saved = True
    return {"name": name, "kind": kind, "text": text, "saved": saved}
