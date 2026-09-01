"""Extract text from PDF documents for storage in memory.

Local extraction only, not vision. This account's Groq models were tested
directly against a vision-shaped request and returned a plain 400 - there
is no multimodal model available here, so scanned/photographed documents
cannot be read. Typed PDFs (a resume exported from Word or Google Docs,
for example) extract cleanly with no API call and no cost.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_CHARS = 12000


class DocumentError(RuntimeError):
    """Raised when a document could not be read or had no extractable text."""


def extract_pdf_text(path: str | Path, max_chars: int = MAX_CHARS) -> str:
    """Return the text of a PDF, truncated to max_chars.

    Truncation matters here for the same reason it does for fetched web
    pages: a long document would otherwise dominate the free tier's
    tokens-per-minute budget on its own.
    """
    p = Path(path)
    if not p.exists():
        raise DocumentError(f"file not found: {p}")
    if p.suffix.lower() != ".pdf":
        raise DocumentError(f"only PDF files are supported, got: {p.suffix or '(no extension)'}")

    try:
        reader = PdfReader(str(p))
        pages = [page.extract_text() or "" for page in reader.pages]
    except (PdfReadError, OSError) as exc:
        raise DocumentError(f"could not read {p.name}: {exc}") from exc

    text = "\n\n".join(t for t in pages if t.strip())
    if not text.strip():
        raise DocumentError(
            f"{p.name} has no extractable text - likely a scanned image "
            "rather than a typed document, which this project cannot parse"
        )
    return text[:max_chars]
