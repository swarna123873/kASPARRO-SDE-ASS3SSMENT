"""
API integration tests for the POST /screen endpoint.
"""

import io
import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas import ExtractionStatus

client = TestClient(app)


def make_pdf_bytes(text: str) -> bytes:
    """Helper to create minimal valid PDF bytes."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(fitz.Point(72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_upload_single_valid_pdf():
    """Verify POST /screen processes a single valid PDF."""
    pdf_bytes = make_pdf_bytes("Alice Engineer\nPython Developer with LangChain projects")
    files = [("files", ("alice_resume.pdf", pdf_bytes, "application/pdf"))]

    response = client.post("/screen", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 1
    assert data["successful_files"] == 1
    assert data["failed_files"] == 0
    assert data["no_text_files"] == 0
    assert len(data["results"]) == 1

    file_res = data["results"][0]
    assert file_res["filename"] == "alice_resume.pdf"
    assert file_res["status"] == ExtractionStatus.SUCCESS.value
    assert file_res["page_count"] == 1
    assert "Alice Engineer" in file_res["extracted_text"]
    assert file_res["error_message"] is None


def test_upload_multiple_valid_pdfs():
    """Verify POST /screen handles multiple valid PDFs concurrently."""
    pdf_1 = make_pdf_bytes("Candidate One - Python FastAPI")
    pdf_2 = make_pdf_bytes("Candidate Two - AI Engineer")
    pdf_3 = make_pdf_bytes("Candidate Three - Backend Engineer")

    files = [
        ("files", ("candidate_1.pdf", pdf_1, "application/pdf")),
        ("files", ("candidate_2.pdf", pdf_2, "application/pdf")),
        ("files", ("candidate_3.pdf", pdf_3, "application/pdf")),
    ]

    response = client.post("/screen", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 3
    assert data["successful_files"] == 3
    assert data["failed_files"] == 0
    assert len(data["results"]) == 3

    filenames = [r["filename"] for r in data["results"]]
    assert filenames == ["candidate_1.pdf", "candidate_2.pdf", "candidate_3.pdf"]


def test_upload_mixed_valid_and_invalid_files():
    """Verify that an invalid file does not break the processing of valid files in the same batch."""
    valid_pdf = make_pdf_bytes("Valid Candidate Resume")
    corrupt_pdf = b"%PDF-1.4\nNot a real pdf stream structure"
    non_pdf = b"Plain text file content"

    files = [
        ("files", ("valid.pdf", valid_pdf, "application/pdf")),
        ("files", ("corrupt.pdf", corrupt_pdf, "application/pdf")),
        ("files", ("notes.txt", non_pdf, "text/plain")),
    ]

    response = client.post("/screen", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 3
    assert data["successful_files"] == 1
    assert data["failed_files"] == 2

    # Check valid file
    valid_res = next(r for r in data["results"] if r["filename"] == "valid.pdf")
    assert valid_res["status"] == ExtractionStatus.SUCCESS.value
    assert "Valid Candidate Resume" in valid_res["extracted_text"]

    # Check non-pdf extension file
    txt_res = next(r for r in data["results"] if r["filename"] == "notes.txt")
    assert txt_res["status"] == ExtractionStatus.FAILED.value
    assert "Only .pdf documents are supported" in txt_res["error_message"]

    # Check corrupt file
    corrupt_res = next(r for r in data["results"] if r["filename"] == "corrupt.pdf")
    assert corrupt_res["status"] == ExtractionStatus.FAILED.value
    assert corrupt_res["error_message"] is not None


def test_upload_empty_pdf_file():
    """Verify empty 0-byte file receives failed status."""
    files = [("files", ("empty.pdf", b"", "application/pdf"))]

    response = client.post("/screen", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 1
    assert data["failed_files"] == 1
    assert "empty (0 bytes)" in data["results"][0]["error_message"]


def test_upload_no_files_returns_400():
    """Verify POST /screen without files or empty form returns HTTP 400."""
    response = client.post("/screen")
    # Missing multipart form boundary / files field
    assert response.status_code == 422 or response.status_code == 400


def test_batch_counts_match_results_accurately():
    """Verify summary counts strictly equal results breakdown."""
    doc = fitz.open()
    doc.new_page()  # blank page -> no text
    blank_pdf = doc.tobytes()
    doc.close()

    valid_pdf = make_pdf_bytes("Some text")

    files = [
        ("files", ("valid.pdf", valid_pdf, "application/pdf")),
        ("files", ("blank.pdf", blank_pdf, "application/pdf")),
        ("files", ("invalid.txt", b"plain text", "text/plain")),
    ]

    response = client.post("/screen", files=files)
    assert response.status_code == 200
    data = response.json()

    assert data["total_files"] == len(data["results"])
    assert data["successful_files"] == 1
    assert data["no_text_files"] == 1
    assert data["failed_files"] == 1


def test_regression_health_endpoint():
    """Verify that Phase 1 GET /health remains fully functional."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
