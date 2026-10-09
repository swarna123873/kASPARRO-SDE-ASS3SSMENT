"""
Data models and response schemas for the AI Resume Screening System.
Includes candidate profile extraction, project evidence, eligibility, scoring,
GitHub enrichment, ranked results, and batch report schemas.

Phase 4 note
------------
Score-category field names follow the spec keys exactly:
  ai_project_depth, python_backend, cloud_fullstack, github, engineering_depth

The ScoreBreakdown.total_score is always computed as:
  max(0, min(100, sum(category_scores) - project_quality_penalty))
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ExtractionStatus(str, Enum):
    """Extraction status values for an uploaded file."""
    SUCCESS = "success"
    NO_TEXT = "no_text"
    FAILED = "failed"


class ProjectInfo(BaseModel):
    """Structured representation of a candidate project."""
    name: str = Field(..., description="Project title or name")
    description: Optional[str] = Field(None, description="Brief summary of the project")
    technologies: List[str] = Field(default_factory=list, description="Technologies and libraries used")
    implementation_details: Optional[str] = Field(None, description="Key architecture, workflows, or technical details")
    supporting_evidence: Optional[str] = Field(None, description="Direct text evidence from resume")


class WorkExperience(BaseModel):
    """Structured representation of candidate professional or internship experience."""
    role: Optional[str] = Field(None, description="Job or internship title")
    organization: Optional[str] = Field(None, description="Company or organization name")
    technologies: List[str] = Field(default_factory=list, description="Technologies utilized in this role")
    responsibilities: Optional[str] = Field(None, description="Key responsibilities and achievements")
    evidence: Optional[str] = Field(None, description="Direct text evidence from resume")


class CandidateProfile(BaseModel):
    """Comprehensive structured profile extracted from a candidate resume."""
    candidate_name: Optional[str] = Field(None, description="Extracted candidate full name")
    email: Optional[str] = Field(None, description="Contact email address")
    phone: Optional[str] = Field(None, description="Contact phone number")
    education: List[str] = Field(default_factory=list, description="Degrees, universities, or academic qualifications")
    programming_languages: List[str] = Field(default_factory=list, description="Identified programming languages")
    technical_skills: List[str] = Field(default_factory=list, description="General technical and domain skills")
    frameworks_and_tools: List[str] = Field(default_factory=list, description="Libraries, frameworks, and developer tools")
    projects: List[ProjectInfo] = Field(default_factory=list, description="Extracted technical projects")
    project_summaries: List[str] = Field(default_factory=list, description="Summarized highlights of key technical projects")
    work_experience: List[WorkExperience] = Field(default_factory=list, description="Work or internship history")
    github_url: Optional[str] = Field(None, description="Public GitHub profile URL")
    matched_skills: List[str] = Field(default_factory=list, description="Verified relevant skills matching job requirements")
    python_evidence: List[str] = Field(default_factory=list, description="Evidence citations for Python proficiency")
    ai_evidence: List[str] = Field(default_factory=list, description="Evidence citations for AI/agentic project implementation")
    extraction_warnings: List[str] = Field(default_factory=list, description="Non-fatal warnings encountered during extraction")


class EligibilityResult(BaseModel):
    """Deterministic eligibility check outcome based on hard filtering rules."""
    eligible: bool = Field(..., description="True if candidate satisfies BOTH Python and AI conditions")
    rejection_reasons: List[str] = Field(default_factory=list, description="Explanations if candidate is rejected")
    matched_skills: List[str] = Field(default_factory=list, description="Skills verified with resume evidence")
    python_evidence: List[str] = Field(default_factory=list, description="Verifiable Python evidence citations")
    ai_evidence: List[str] = Field(default_factory=list, description="Verifiable AI / LLM / RAG / Agentic citations")


class FileExtractionResult(BaseModel):
    """Per-file extraction, parsing, and screening result schema."""
    filename: str = Field(..., description="Original name of the uploaded PDF file")
    status: ExtractionStatus = Field(..., description="Outcome of parsing: success, no_text, or failed")
    page_count: Optional[int] = Field(None, description="Number of pages detected in the PDF")
    text_length: int = Field(0, description="Total characters of extracted text")
    extracted_text: Optional[str] = Field(None, description="Cleaned text extracted from the document")
    error_message: Optional[str] = Field(None, description="Diagnostic reason for no_text or failed status")

    # Phase 3: Candidate extraction and eligibility
    candidate_name: Optional[str] = Field(None, description="Extracted candidate name")
    candidate_profile: Optional[CandidateProfile] = Field(None, description="Structured candidate profile")
    eligible: Optional[bool] = Field(None, description="Hard eligibility status (null if file failed parsing)")
    rejection_reasons: List[str] = Field(default_factory=list, description="Specific rejection reasons if ineligible")
    matched_skills: List[str] = Field(default_factory=list, description="Verified relevant skills")
    python_evidence: List[str] = Field(default_factory=list, description="Evidence supporting Python competency")
    ai_evidence: List[str] = Field(default_factory=list, description="Evidence supporting AI/agentic project implementation")
    extraction_warnings: List[str] = Field(default_factory=list, description="Warnings generated during extraction")

    # Phase 4: duplicate detection
    file_hash: Optional[str] = Field(None, description="SHA-256 hash of file content for duplicate detection")


class BatchScreenResponse(BaseModel):
    """Batch screening response schema containing summary counts and per-file results."""
    total_files: int = Field(..., description="Total number of files submitted in the batch")
    successful_files: int = Field(..., description="Count of files with successfully extracted text")
    no_text_files: int = Field(..., description="Count of valid files with no extractable text")
    failed_files: int = Field(..., description="Count of invalid, corrupted, or unreadable files")
    eligible_candidates: int = Field(0, description="Count of candidates who satisfied all hard eligibility rules")
    ineligible_candidates: int = Field(0, description="Count of candidates rejected by hard eligibility rules")
    results: List[FileExtractionResult] = Field(..., description="Detailed result for each uploaded file")


# ============================================================================
# Phase 4: Scoring, GitHub Enrichment, and Ranking Schemas
# ============================================================================

class ScoreCategoryDetail(BaseModel):
    """
    A single scored rubric category with points, explanation, and evidence.
    Used inside ScoreEvidence for explainable reporting.
    """
    category: str = Field(..., description="Rubric category key (e.g. 'ai_project_depth')")
    points_awarded: int = Field(..., description="Points awarded in this category")
    max_points: int = Field(..., description="Maximum points available in this category")
    explanation: str = Field("", description="Short explanation of the score awarded")
    evidence: List[str] = Field(default_factory=list, description="Supporting evidence citations")
    limitation: Optional[str] = Field(None, description="Relevant uncertainty or missing-data caveat")


class ScoreBreakdown(BaseModel):
    """
    Explainable 100-point rubric score broken into five weighted dimensions.

    Category keys (spec-mandated):
      ai_project_depth    — max 40 pts
      python_backend      — max 30 pts
      cloud_fullstack     — max 15 pts
      github              — max 10 pts  (populated after GitHub enrichment)
      engineering_depth   — max  5 pts
    Penalty: 5-15 pts for a shallow API-wrapper project (when evidence supports it).
    total_score = max(0, min(100, sum(categories) - project_quality_penalty))
    """

    # ── Category scores ────────────────────────────────────────────────────
    ai_project_depth: int = Field(0, ge=0, le=40, description="AI/Agentic/RAG project depth score (max 40)")
    ai_project_depth_evidence: List[str] = Field(default_factory=list)

    python_backend: int = Field(0, ge=0, le=30, description="Python & backend engineering score (max 30)")
    python_backend_evidence: List[str] = Field(default_factory=list)

    cloud_fullstack: int = Field(0, ge=0, le=15, description="Cloud / deployment / full-stack score (max 15)")
    cloud_fullstack_evidence: List[str] = Field(default_factory=list)

    github: int = Field(0, ge=0, le=10, description="GitHub activity score (max 10)")
    github_evidence: List[str] = Field(default_factory=list)

    engineering_depth: int = Field(0, ge=0, le=5, description="Engineering depth signals score (max 5)")
    engineering_depth_evidence: List[str] = Field(default_factory=list)

    # ── Penalty ────────────────────────────────────────────────────────────
    project_quality_penalty: int = Field(0, ge=0, description="Penalty for shallow/API-wrapper projects")
    project_quality_penalty_reasons: List[str] = Field(default_factory=list)

    # ── Final score ────────────────────────────────────────────────────────
    total_score: int = Field(0, ge=0, le=100, description="Final score out of 100 after penalties")

    # ── Per-category evidence objects (optional rich reporting) ────────────
    score_evidence: List[ScoreCategoryDetail] = Field(
        default_factory=list,
        description="Detailed per-category evidence for the final report"
    )

    # ──────────────────────────────────────────────────────────────────────
    # Backward-compat aliases kept so existing tests that reference the
    # old field names (deployment_cloud, engineering_fundamentals, penalty,
    # penalty_reasons, github_activity, *_evidence variants) do not break.
    # These are read-only computed properties.
    # ──────────────────────────────────────────────────────────────────────

    @property
    def deployment_cloud(self) -> int:
        return self.cloud_fullstack

    @property
    def deployment_cloud_evidence(self) -> List[str]:
        return self.cloud_fullstack_evidence

    @property
    def engineering_fundamentals(self) -> int:
        return self.engineering_depth

    @property
    def engineering_fundamentals_evidence(self) -> List[str]:
        return self.engineering_depth_evidence

    @property
    def github_activity(self) -> int:
        return self.github

    @property
    def github_activity_evidence(self) -> List[str]:
        return self.github_evidence

    @property
    def penalty(self) -> int:
        return self.project_quality_penalty

    @property
    def penalty_reasons(self) -> List[str]:
        return self.project_quality_penalty_reasons

    @property
    def ai_project_evidence(self) -> List[str]:
        return self.ai_project_depth_evidence

    @property
    def python_backend_evidence_compat(self) -> List[str]:
        return self.python_backend_evidence


class GitHubEnrichmentResult(BaseModel):
    """
    Structured public GitHub enrichment result (spec-compliant field names).

    Status values:
      success         — data fetched from GitHub API successfully
      missing_profile — URL found but GitHub returned 404
      rate_limited    — GitHub API responded with 403/429 (rate limit)
      failed          — network error, timeout, or unexpected API failure
      no_github       — no GitHub URL found in the resume
      skipped         — enrichment disabled via ENRICH_GITHUB_PROFILES=false
    """
    status: str = Field("no_github", description="Enrichment outcome status")
    profile_url: Optional[str] = Field(None, description="Canonical GitHub profile URL")
    score: int = Field(0, ge=0, le=10, description="GitHub activity score contribution (0-10)")
    recent_activity_summary: str = Field("", description="Summary of recent public activity signals")
    repository_summary: str = Field("", description="Summary of maintained public repositories")
    relevant_repositories: List[str] = Field(default_factory=list, description="Names of AI/Python-relevant public repos")
    error_message: Optional[str] = Field(None, description="Diagnostic message when status != success")

    # Extended internal fields (used by ranker/ranker tests)
    github_username: Optional[str] = Field(None, description="Extracted GitHub username")
    public_repos: Optional[int] = Field(None, description="Total public repository count")
    followers: Optional[int] = Field(None, description="Follower count")
    following: Optional[int] = Field(None, description="Following count")
    bio: Optional[str] = Field(None, description="Profile bio")
    top_languages: List[str] = Field(default_factory=list, description="Detected top languages from public repos")
    has_pinned_ai_project: bool = Field(False, description="Whether user has an AI-related public project")

    # Internal score-computation helper (set by enricher, not serialised)
    _recent_repo_count: int = 0

    # ── Backward-compat aliases ────────────────────────────────────────────
    @property
    def enrichment_status(self) -> str:
        """Backward-compat alias for status (old field name used in tests)."""
        return self.status

    @property
    def enrichment_error(self) -> Optional[str]:
        """Backward-compat alias for error_message."""
        return self.error_message


# Keep the old alias so tests that import GitHubEnrichment still work
GitHubEnrichment = GitHubEnrichmentResult


class RankedCandidate(BaseModel):
    """A single eligible candidate with score, rank, and full evidence report."""
    rank: int = Field(..., description="Final rank position (1 = highest scorer)")
    filename: str = Field(..., description="Source resume filename")
    candidate_name: str = Field(..., description="Extracted candidate name")
    eligible: bool = Field(True, description="Always True for ranked candidates")
    email: Optional[str] = Field(None, description="Candidate email")
    github_url: Optional[str] = Field(None, description="Candidate GitHub profile URL")
    total_score: int = Field(..., description="Final 100-point score")
    score_breakdown: ScoreBreakdown = Field(..., description="Explainable dimension-by-dimension score")
    project_quality_penalty: int = Field(0, description="Quality penalty applied")
    matched_skills: List[str] = Field(default_factory=list, description="Verified relevant skills")
    project_summary: List[str] = Field(default_factory=list, description="Key project highlights")
    github_summary: str = Field("", description="Human-readable GitHub summary")
    github_enrichment: Optional[GitHubEnrichmentResult] = Field(None, description="GitHub public profile data")
    strengths: List[str] = Field(default_factory=list, description="Candidate strengths")
    concerns: List[str] = Field(default_factory=list, description="Candidate concerns or gaps")
    score_evidence: List[ScoreCategoryDetail] = Field(default_factory=list, description="Per-category evidence")
    python_evidence: List[str] = Field(default_factory=list, description="Python competency evidence citations")
    ai_evidence: List[str] = Field(default_factory=list, description="AI/agentic evidence citations")
    project_summaries: List[str] = Field(default_factory=list, description="Key project highlights (alias)")


class RejectedCandidate(BaseModel):
    """A candidate rejected by the hard eligibility rules (not ranked)."""
    filename: str = Field(..., description="Source resume filename")
    candidate_name: str = Field(..., description="Extracted candidate name")
    eligible: bool = Field(False, description="Always False for rejected candidates")
    email: Optional[str] = Field(None, description="Candidate email")
    rejection_reasons: List[str] = Field(..., description="Specific hard eligibility failure reasons")
    matched_skills: List[str] = Field(default_factory=list, description="Skills detected (insufficient for eligibility)")
    python_evidence: List[str] = Field(default_factory=list, description="Python evidence found (if any)")
    ai_evidence: List[str] = Field(default_factory=list, description="AI evidence found (if any)")


class FailedFile(BaseModel):
    """A file that failed to parse or had no extractable text."""
    filename: str = Field(..., description="Source resume filename")
    status: str = Field(..., description="failed, no_text, or processing_error")
    failure_stage: Optional[str] = Field(None, description="Stage at which processing failed")
    error_message: Optional[str] = Field(None, description="Diagnostic error reason")


class DuplicateFile(BaseModel):
    """A file that is a byte-for-byte duplicate of another uploaded file."""
    filename: str = Field(..., description="Duplicate file name")
    original_filename: str = Field(..., description="The first file with the same content")
    file_hash: str = Field(..., description="SHA-256 content hash shared by both files")


class BatchSummaryStats(BaseModel):
    """
    Aggregate statistics for the entire screening batch.

    Count reconciliation rules:
      total_resumes == total number of uploaded files (including duplicates)
      successfully_parsed == unique, successfully parsed resumes
      eligible + rejected == number of parsed resumes that received eligibility decisions
      failed_or_unreadable == files that could not be parsed (failed + no_text)
      duplicates == files identified as byte-identical to an already-seen file
    """
    total_resumes: int = Field(..., description="Total files submitted (including duplicates)")
    successfully_parsed: int = Field(..., description="Unique files successfully parsed")
    eligible: int = Field(..., description="Candidates passing hard eligibility")
    rejected: int = Field(..., description="Candidates failing hard eligibility")
    failed_or_unreadable: int = Field(..., description="Files that failed parsing or had no text")
    duplicates: int = Field(0, description="Files detected as byte-identical duplicates")
    highest_score: Optional[int] = Field(None, description="Highest score among eligible candidates")
    lowest_score: Optional[int] = Field(None, description="Lowest score among eligible candidates")
    average_score: Optional[float] = Field(None, description="Mean score among eligible candidates")

    # ── Backward-compat aliases ────────────────────────────────────────────
    @property
    def total_submitted(self) -> int:
        return self.total_resumes

    @property
    def total_parsed(self) -> int:
        return self.successfully_parsed

    @property
    def total_eligible(self) -> int:
        return self.eligible

    @property
    def total_ineligible(self) -> int:
        return self.rejected

    @property
    def total_failed(self) -> int:
        return self.failed_or_unreadable

    @property
    def total_no_text(self) -> int:
        # Best approximation; use failed_or_unreadable for combined count
        return 0


class BatchReport(BaseModel):
    """
    Complete, machine-readable Phase 4 report.

    Contains:
      ranked_eligible_candidates — sorted by score descending, eligible only
      rejected_candidates        — ineligible candidates with rejection reasons
      failed_resumes             — files that could not be processed
      duplicates                 — byte-identical duplicate files
      batch_summary              — aggregate statistics

    JSON output path: results.json (project root)
    """
    ranked_eligible_candidates: List[RankedCandidate] = Field(
        default_factory=list,
        description="Eligible candidates sorted by descending score (rank 1 = best)"
    )
    rejected_candidates: List[RejectedCandidate] = Field(
        default_factory=list,
        description="Candidates failing hard eligibility rules (not ranked)"
    )
    failed_resumes: List[FailedFile] = Field(
        default_factory=list,
        description="Files that could not be processed"
    )
    duplicates: List[DuplicateFile] = Field(
        default_factory=list,
        description="Byte-identical duplicate files (not processed again)"
    )
    batch_summary: BatchSummaryStats = Field(..., description="Batch-level aggregate statistics")

    # ── Backward-compat aliases so existing tests using old field names pass ─
    @property
    def ranked_candidates(self) -> List[RankedCandidate]:
        return self.ranked_eligible_candidates

    @property
    def failed_files(self) -> List[FailedFile]:
        return self.failed_resumes

    @property
    def summary(self) -> BatchSummaryStats:
        return self.batch_summary
