"""
Unit tests for the PDF text extraction module (backend/pdf_parser.py).
Uses programmatically generated synthetic PDF fixtures via PyMuPDF.
"""

import pymupdf as fitz
import pytest

from backend.pdf_parser import extract_text_from_pdf_bytes


def create_synthetic_pdf(pages_text: list[str]) -> bytes:
    """Helper to generate an in-memory PDF with known text on each page."""
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        if text:
            # Insert text at coordinate (50, 72)
            page.insert_text(fitz.Point(50, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_extract_valid_single_page_pdf():
    """Verify text extraction from a 1-page PDF."""
    sample_text = "John Doe\nPython Software Engineer\nBuilt LLM agent with LangChain."
    pdf_bytes = create_synthetic_pdf([sample_text])

    result = extract_text_from_pdf_bytes(pdf_bytes, filename="resume_john.pdf")

    assert result.status == "success"
    assert result.page_count == 1
    assert "John Doe" in result.extracted_text
    assert "Python Software Engineer" in result.extracted_text
    assert result.text_length > 0
    assert result.error_message is None


def test_extract_valid_multi_page_pdf():
    """Verify text extraction from a 3-page PDF in order."""
    page_1 = "Page 1: Jane Smith - Education & Summary"
    page_2 = "Page 2: Jane Smith - Python & FastAPI Experience"
    page_3 = "Page 3: Jane Smith - RAG Project Details"

    pdf_bytes = create_synthetic_pdf([page_1, page_2, page_3])

    result = extract_text_from_pdf_bytes(pdf_bytes, filename="resume_jane.pdf")

    assert result.status == "success"
    assert result.page_count == 3
    assert "Page 1" in result.extracted_text
    assert "Page 2" in result.extracted_text
    assert "Page 3" in result.extracted_text
    assert result.text_length > 0


def test_extract_pdf_with_no_text():
    """Verify that a valid PDF with blank/image-only pages returns 'no_text'."""
    # Create a 2-page blank PDF
    pdf_bytes = create_synthetic_pdf(["", ""])

    result = extract_text_from_pdf_bytes(pdf_bytes, filename="scanned_resume.pdf")

    assert result.status == "no_text"
    assert result.page_count == 2
    assert result.text_length == 0
    assert result.extracted_text == ""
    assert "No extractable text" in result.error_message


def test_extract_corrupted_pdf_bytes():
    """Verify that arbitrary corrupted bytes return 'failed' gracefully."""
    corrupt_bytes = b"%PDF-1.4\nSome random corrupted non-pdf binary content here\x00\xff"

    result = extract_text_from_pdf_bytes(corrupt_bytes, filename="corrupted.pdf")

    assert result.status == "failed"
    assert result.extracted_text is None
    assert "Corrupted or invalid" in result.error_message


def test_extract_empty_bytes():
    """Verify that 0-byte input returns 'failed' immediately."""
    result = extract_text_from_pdf_bytes(b"", filename="empty.pdf")

    assert result.status == "failed"
    assert result.page_count == 0
    assert result.text_length == 0
    assert "empty (0 bytes)" in result.error_message
