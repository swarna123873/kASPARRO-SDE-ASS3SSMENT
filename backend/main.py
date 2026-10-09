"""
Main FastAPI entry point for the AI Resume Screening System.
Provides core service endpoints including health check, batch PDF upload (/screen),
and the full Phase 4 ranked report (/report).
"""

import hashlib
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.candidate_extractor import extract_candidate_profile
from backend.eligibility import evaluate_candidate_eligibility
from backend.pdf_parser import extract_text_from_pdf_bytes
from backend.ranker import build_batch_report
from backend.schemas import (
    BatchReport,
    BatchScreenResponse,
    ExtractionStatus,
    FileExtractionResult,
)

# Initialize FastAPI application with informative metadata
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Automated, evidence-based resume screening backend for SDE Intern candidates.",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Explicit CORS configuration for local development and testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def _sha256(data: bytes) -> str:
    """Return the hex SHA-256 digest of *data*."""
    return hashlib.sha256(data).hexdigest()


async def _process_batch(
    files: List[UploadFile],
    include_text: bool = True,
) -> List[FileExtractionResult]:
    """
    Core per-file validation, text extraction, candidate profiling, and
    eligibility evaluation shared by both /screen and /report endpoints.

    Args:
        files:        Uploaded resume files.
        include_text: If False, the extracted_text field is omitted from the
                      result (saves memory for the /screen response).
    Returns:
        List of FileExtractionResult — one per uploaded file.
    """
    results: List[FileExtractionResult] = []

    for upload_file in files:
        filename = upload_file.filename or "unknown.pdf"

        # 1. Extension validation
        if not filename.lower().endswith(".pdf"):
            results.append(FileExtractionResult(
                filename=filename,
                status=ExtractionStatus.FAILED,
                page_count=None,
                text_length=0,
                extracted_text=None,
                error_message="Invalid file extension. Only .pdf documents are supported.",
            ))
            await upload_file.close()
            continue

        try:
            # 2. Read file content
            content = await upload_file.read()
            file_hash = _sha256(content)

            # 3. Empty file check
            if len(content) == 0:
                results.append(FileExtractionResult(
                    filename=filename,
                    status=ExtractionStatus.FAILED,
                    page_count=0,
                    text_length=0,
                    extracted_text=None,
                    error_message="Uploaded file is empty (0 bytes).",
                    file_hash=file_hash,
                ))
                continue

            # 4. File size check
            if len(content) > settings.max_file_size_bytes:
                max_mb = settings.max_file_size_bytes // (1024 * 1024)
                results.append(FileExtractionResult(
                    filename=filename,
                    status=ExtractionStatus.FAILED,
                    page_count=None,
                    text_length=0,
                    extracted_text=None,
                    error_message=f"File exceeds maximum size limit of {max_mb} MB.",
                    file_hash=file_hash,
                ))
                continue

            # 5. PDF magic bytes check
            if not content[:1024].lstrip().startswith(b"%PDF"):
                results.append(FileExtractionResult(
                    filename=filename,
                    status=ExtractionStatus.FAILED,
                    page_count=None,
                    text_length=0,
                    extracted_text=None,
                    error_message="File content signature does not match standard PDF header (%PDF).",
                    file_hash=file_hash,
                ))
                continue

            # 6. Text extraction
            parse_result = extract_text_from_pdf_bytes(content, filename=filename)

            # 7. Candidate profiling & eligibility (Phase 3+)
            candidate_profile = None
            candidate_name = None
            eligible = None
            rejection_reasons: List[str] = []
            matched_skills: List[str] = []
            python_evidence: List[str] = []
            ai_evidence: List[str] = []
            extraction_warnings: List[str] = []

            if parse_result.status == "success" and parse_result.extracted_text:
                candidate_profile = extract_candidate_profile(
                    parse_result.extracted_text, filename=filename
                )
                candidate_name = candidate_profile.candidate_name
                extraction_warnings = list(candidate_profile.extraction_warnings)

                eligibility = evaluate_candidate_eligibility(
                    candidate_profile, parse_result.extracted_text
                )
                eligible = eligibility.eligible
                rejection_reasons = eligibility.rejection_reasons
                matched_skills = eligibility.matched_skills
                python_evidence = eligibility.python_evidence
                ai_evidence = eligibility.ai_evidence

                # Sync enriched fields back to profile
                candidate_profile.matched_skills = matched_skills
                candidate_profile.python_evidence = python_evidence
                candidate_profile.ai_evidence = ai_evidence
                candidate_profile.project_summaries = [
                    f"{p.name}: {p.description or ''}"[:120]
                    for p in candidate_profile.projects if p.name
                ]

            results.append(FileExtractionResult(
                filename=filename,
                status=ExtractionStatus(parse_result.status),
                page_count=parse_result.page_count,
                text_length=parse_result.text_length,
                extracted_text=parse_result.extracted_text if include_text else None,
                error_message=parse_result.error_message,
                candidate_name=candidate_name,
                candidate_profile=candidate_profile,
                eligible=eligible,
                rejection_reasons=rejection_reasons,
                matched_skills=matched_skills,
                python_evidence=python_evidence,
                ai_evidence=ai_evidence,
                extraction_warnings=extraction_warnings,
                file_hash=file_hash,
            ))

        except Exception as exc:
            results.append(FileExtractionResult(
                filename=filename,
                status=ExtractionStatus.FAILED,
                page_count=None,
                text_length=0,
                extracted_text=None,
                error_message=f"Unexpected processing error: {str(exc)}",
            ))
        finally:
            await upload_file.close()

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", tags=["General"])
def read_root():
    """Root endpoint providing basic application metadata and navigation links."""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs_url": "/docs",
        "health_url": "/health",
        "screen_url": "/screen",
        "report_url": "/report",
        "message": "AI Resume Screening System backend is running.",
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint to verify backend operational readiness."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@app.post(
    "/screen",
    response_model=BatchScreenResponse,
    tags=["Screening"],
    summary="Batch PDF Upload & Eligibility Check",
    description=(
        "Upload up to 50 PDF resumes. Extracts text, profiles candidates, and "
        "evaluates hard eligibility rules (Python + AI). Does NOT rank or score."
    ),
)
async def upload_resumes(
    files: List[UploadFile] = File(
        ...,
        description="Batch of PDF resume files (maximum 50 files, 10MB each)",
    ),
) -> BatchScreenResponse:
    """Process an uploaded batch of PDF resume files and return eligibility results."""
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded. Please submit at least one PDF resume.",
        )
    if len(files) > settings.max_files_per_batch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Batch exceeds maximum limit of {settings.max_files_per_batch} files. "
                f"Received {len(files)} files."
            ),
        )

    results = await _process_batch(files, include_text=True)

    successful_count = sum(1 for r in results if r.status == ExtractionStatus.SUCCESS)
    no_text_count = sum(1 for r in results if r.status == ExtractionStatus.NO_TEXT)
    failed_count = sum(1 for r in results if r.status == ExtractionStatus.FAILED)
    eligible_count = sum(1 for r in results if r.eligible is True)
    ineligible_count = sum(1 for r in results if r.eligible is False)

    return BatchScreenResponse(
        total_files=len(results),
        successful_files=successful_count,
        no_text_files=no_text_count,
        failed_files=failed_count,
        eligible_candidates=eligible_count,
        ineligible_candidates=ineligible_count,
        results=results,
    )


@app.post(
    "/report",
    response_model=BatchReport,
    tags=["Screening"],
    summary="Batch PDF Screening + Ranked Report",
    description=(
        "Upload up to 50 PDF resumes. Returns a complete ranked report with "
        "100-point scores, optional GitHub enrichment, rejected candidates, "
        "failed files, duplicate detection, and batch-level statistics. "
        "Also writes results.json to the project root."
    ),
)
async def upload_resumes_ranked(
    files: List[UploadFile] = File(
        ...,
        description="Batch of PDF resume files (maximum 50 files, 10MB each)",
    ),
) -> BatchReport:
    """
    Full Phase 4 pipeline:
    1. Validate and parse each PDF.
    2. Detect byte-identical duplicates (SHA-256).
    3. Extract structured candidate profiles.
    4. Apply hard eligibility rules (Python + AI).
    5. Score eligible candidates on the 100-point rubric.
    6. Optionally enrich with public GitHub profile data.
    7. Rank by score and return a machine-readable report.
    8. Write results.json to the project root.
    """
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files uploaded. Please submit at least one PDF resume.",
        )
    if len(files) > settings.max_files_per_batch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Batch exceeds maximum limit of {settings.max_files_per_batch} files. "
                f"Received {len(files)} files."
            ),
        )

    results = await _process_batch(files, include_text=True)

    return build_batch_report(
        results,
        enrich_github_profiles=settings.enrich_github_profiles,
        write_json=True,
    )
