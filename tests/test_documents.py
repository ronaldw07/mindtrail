"""PDF extraction tests. pypdf itself is mocked; no real PDF needed."""

from unittest.mock import MagicMock, patch

import pytest

from mindtrail.ingest.documents import DocumentError, extract_pdf_text


def test_missing_file_raises(tmp_path):
    with pytest.raises(DocumentError, match="not found"):
        extract_pdf_text(tmp_path / "nope.pdf")


def test_non_pdf_extension_is_rejected(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")

    with pytest.raises(DocumentError, match="only PDF"):
        extract_pdf_text(txt)


def _stub_reader(page_texts):
    reader = MagicMock()
    pages = []
    for text in page_texts:
        page = MagicMock()
        page.extract_text.return_value = text
        pages.append(page)
    reader.pages = pages
    return reader


def test_pages_are_joined_with_a_blank_line(tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-fake")

    with patch("mindtrail.ingest.documents.PdfReader", return_value=_stub_reader(
        ["Page one text", "Page two text"]
    )):
        result = extract_pdf_text(pdf)

    assert result == "Page one text\n\nPage two text"


def test_blank_pages_are_dropped(tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-fake")

    with patch("mindtrail.ingest.documents.PdfReader", return_value=_stub_reader(
        ["Real content", "", "   "]
    )):
        result = extract_pdf_text(pdf)

    assert result == "Real content"


def test_a_scanned_pdf_with_no_text_raises(tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-fake")

    with patch("mindtrail.ingest.documents.PdfReader", return_value=_stub_reader(["", ""])):
        with pytest.raises(DocumentError, match="scanned image"):
            extract_pdf_text(pdf)


def test_result_is_truncated_to_max_chars(tmp_path):
    pdf = tmp_path / "long.pdf"
    pdf.write_bytes(b"%PDF-fake")

    with patch(
        "mindtrail.ingest.documents.PdfReader",
        return_value=_stub_reader(["x" * 5000]),
    ):
        result = extract_pdf_text(pdf, max_chars=100)

    assert len(result) == 100
