"""
PDF text extraction module using PyMuPDF (fitz).
Provides safe, resilient parsing of PDF bytes without throwing unhandled exceptions.
"""

from dataclasses import dataclass
from typing import Optional
import logging
import pymupdf as fitz

logger = logging.getLogger(__name__)


@dataclass
class PDFParseResult:
    """
    Standard result returned by the PDF parser.
    status: 'success' | 'no_text' | 'failed'
    """
    status: str
    page_count: Optional[int] = None
    text_length: int = 0
    extracted_text: Optional[str] = None
    error_message: Optional[str] = None


def extract_text_from_pdf_bytes(pdf_bytes: bytes, filename: str = "document.pdf") -> PDFParseResult:
    """
    Extract readable text and document metadata from raw PDF bytes.

    Args:
        pdf_bytes: Raw binary content of the PDF.
        filename: Optional filename for logging context.

    Returns:
        PDFParseResult with extraction status, page count, and extracted text.
    """
    if not pdf_bytes:
        return PDFParseResult(
            status="failed",
            page_count=0,
            text_length=0,
            error_message="The PDF file is empty (0 bytes).",
        )

    doc: Optional[fitz.Document] = None
    try:
        # Open PDF document from memory stream
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        # Handle encrypted / password-protected files
        if doc.is_encrypted:
            # Attempt to authenticate with empty password
            if not doc.authenticate(""):
                return PDFParseResult(
                    status="failed",
                    page_count=len(doc),
                    text_length=0,
                    error_message="The PDF file is password protected or encrypted.",
                )

        page_count = len(doc)
        if page_count == 0:
            return PDFParseResult(
                status="no_text",
                page_count=0,
                text_length=0,
                extracted_text="",
                error_message="The PDF document has 0 pages.",
            )

        # Extract text page-by-page preserving document reading order
        page_texts = []
        for page_index in range(page_count):
            page = doc[page_index]
            text = page.get_text("text")
            if text and text.strip():
                page_texts.append(text.strip())

        combined_text = "\n\n".join(page_texts).strip()
        text_length = len(combined_text)

        if text_length > 0:
            return PDFParseResult(
                status="success",
                page_count=page_count,
                text_length=text_length,
                extracted_text=combined_text,
            )
        else:
            # Valid PDF structure with pages, but no extractable text found (e.g. image-only / scanned)
            return PDFParseResult(
                status="no_text",
                page_count=page_count,
                text_length=0,
                extracted_text="",
                error_message="No extractable text found in PDF (document may be scanned or image-based).",
            )

    except Exception as exc:
        logger.warning("Failed to parse PDF '%s': %s", filename, str(exc))
        return PDFParseResult(
            status="failed",
            page_count=None,
            text_length=0,
            error_message="Corrupted or invalid PDF format that could not be parsed.",
        )
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass
