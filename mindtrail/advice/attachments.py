"""Files sent to the assistant, turned into text it can read: a PDF's
text, a text file as is, a screenshot described by a model that can see.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from mindtrail.ingest.documents import extract_pdf_text

MAX_BYTES = 15 * 1024 * 1024
MAX_CHARS = 6000          # what one attachment adds to a message
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp",
               "gif": "image/gif"}
TEXT_TYPES = ("txt", "md", "csv", "json")
DESCRIBE_PROMPT = (
    "Someone shared this screenshot or photo with their planning assistant. Write out "
    "everything useful in it as plain text: all readable text (exactly), what's shown, "
    "and any numbers, dates or names. No commentary."
)


def kind_of(name: str) -> str:
    """image | pdf | text, or '' for a file this can't read."""
    ext = Path(name).suffix.lower().lstrip(".")
    return "image" if ext in IMAGE_TYPES else "pdf" if ext == "pdf" else "text" if ext in TEXT_TYPES else ""


def decode(data_b64: str) -> bytes:
    try:
        data = base64.b64decode(data_b64, validate=True)
    except ValueError as exc:
        raise ValueError("that file didn't arrive intact - try again") from exc
    if not data:
        raise ValueError("that file is empty")
    if len(data) > MAX_BYTES:
        raise ValueError(f"that file is over {MAX_BYTES // (1024 * 1024)} MB")
    return data


def read_attachment(llm, name: str, data: bytes) -> str:
    """The file's content as text, cut to MAX_CHARS."""
    kind = kind_of(name)
    if kind == "image":
        mime = IMAGE_TYPES[Path(name).suffix.lower().lstrip(".")]
        text = llm.describe_image(DESCRIBE_PROMPT, data, mime)
    elif kind == "pdf":
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / Path(name).name
            path.write_bytes(data)
            text = extract_pdf_text(path)
    elif kind == "text":
        text = data.decode("utf-8", errors="replace")
    else:
        raise ValueError("send a screenshot or photo, a PDF, or a text file")
    return text.strip()[:MAX_CHARS]
