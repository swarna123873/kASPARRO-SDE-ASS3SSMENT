"""
Candidate ranking module for the AI Resume Screening System (Phase 4).

Pipeline:
  1. Detect and quarantine duplicate files (SHA-256 content hash).
  2. Classify each file as failed/no-text, rejected (ineligible), or eligible.
  3. For eligible candidates: score → GitHub enrich → apply GitHub bonus.
  4. Sort eligible candidates by final score descending; assign sequential ranks.
  5. Produce the machine-readable BatchReport.
  6. Write results.json via report_builder (non-fatal if it fails).

Architectural rules:
  - Eligibility and ranking are strictly separate.
  - An ineligible candidate is NEVER ranked regardless of score.
  - A missing/failed GitHub profile does NOT cause rejection.
  - One candidate's error does NOT abort the rest of the batch.
  - Duplicate detection uses SHA-256 file content hash; different candidates
    with the same name/email are NOT merged.

Tie-break order (deterministic):
  1. total_score descending
  2. ai_project_depth descending
  3. python_backend descending
  4. candidate_name ascending (alphabetical)
"""

import hashlib
import logging
from typing import Dict, List, Optional

from backend.report_builder import write_report
from backend.schemas import (
    BatchReport,
    BatchSummaryStats,
    DuplicateFile,
    FailedFile,
    FileExtractionResult,
    GitHubEnrichmentResult,
    RankedCandidate,
    RejectedCandidate,
    ScoreBreakdown,
    ScoreCategoryDetail,
)
from backend.scorer import score_candidate
from backend.github_enricher import (
    clear_enrichment_cache,
    compute_github_score_bonus,
    enrich_github,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _safe_name(result: FileExtractionResult) -> str:
    """Return the best available candidate name."""
    if result.candidate_name:
        return result.candidate_name
    if result.candidate_profile and result.candidate_profile.candidate_name:
        return result.candidate_profile.candidate_name
    return "Unknown Candidate"


def _safe_email(result: FileExtractionResult) -> Optional[str]:
    if result.candidate_profile:
        return result.candidate_profile.email
    return None


def _safe_github_url(result: FileExtractionResult) -> Optional[str]:
    if result.candidate_profile:
        return result.candidate_profile.github_url
    return None


def _apply_github_bonus(
    breakdown: ScoreBreakdown,
    enrichment: GitHubEnrichmentResult,
) -> ScoreBreakdown:
    """
    Inject the GitHub score into a completed ScoreBreakdown and recalculate
    the total (still capped at 100 and floored at 0).
    """
    gh_pts, gh_ev = compute_github_score_bonus(enrichment)
    # Pre-penalty total + GitHub bonus, then re-apply penalty
    pre_penalty_base = (
        breakdown.ai_project_depth
        + breakdown.python_backend
        + breakdown.cloud_fullstack
        + gh_pts
        + breakdown.engineering_depth
    )
    new_total = max(0, min(100, pre_penalty_base - breakdown.project_quality_penalty))

    # Update the github evidence entry in score_evidence
    updated_evidence = []
    for se in breakdown.score_evidence:
        if se.category == "github":
            updated_evidence.append(
                ScoreCategoryDetail(
                    category="github",
                    points_awarded=gh_pts,
                    max_points=se.max_points,
                    explanation=f"GitHub activity: {gh_pts}/{se.max_points} pts",
                    evidence=gh_ev,
                    limitation=None,
                )
            )
        else:
            updated_evidence.append(se)

    return ScoreBreakdown(
        ai_project_depth=breakdown.ai_project_depth,
        ai_project_depth_evidence=breakdown.ai_project_depth_evidence,
        python_backend=breakdown.python_backend,
        python_backend_evidence=breakdown.python_backend_evidence,
        cloud_fullstack=breakdown.cloud_fullstack,
        cloud_fullstack_evidence=breakdown.cloud_fullstack_evidence,
        github=gh_pts,
        github_evidence=gh_ev,
        engineering_depth=breakdown.engineering_depth,
        engineering_depth_evidence=breakdown.engineering_depth_evidence,
        project_quality_penalty=breakdown.project_quality_penalty,
        project_quality_penalty_reasons=breakdown.project_quality_penalty_reasons,
        total_score=new_total,
        score_evidence=updated_evidence,
    )


def _derive_strengths(profile, breakdown: ScoreBreakdown) -> List[str]:
    """Derive a short list of candidate strengths from scores and evidence."""
    strengths: List[str] = []
    if breakdown.ai_project_depth >= 24:
        strengths.append("Strong AI/Agentic project depth")
    if breakdown.python_backend >= 20:
        strengths.append("Solid Python & backend engineering foundation")
    if breakdown.cloud_fullstack >= 10:
        strengths.append("Demonstrated cloud/deployment experience")
    if breakdown.github >= 7:
        strengths.append("Active public GitHub presence with relevant projects")
    if breakdown.engineering_depth >= 4:
        strengths.append("Good engineering depth: testing, architecture, or code quality signals")
    if not strengths:
        strengths.append("Meets baseline Python and AI eligibility requirements")
    return strengths


def _derive_concerns(profile, breakdown: ScoreBreakdown) -> List[str]:
    """Derive a short list of gaps or concerns from scores and evidence."""
    concerns: List[str] = []
    if breakdown.ai_project_depth < 16:
        concerns.append("Limited AI/Agentic project depth evidence")
    if breakdown.python_backend < 12:
        concerns.append("Limited Python & backend engineering evidence")
    if breakdown.cloud_fullstack == 0:
        concerns.append("No cloud, deployment, or full-stack evidence found")
    if breakdown.github == 0:
        concerns.append("No GitHub activity signal (profile missing or unavailable)")
    if breakdown.project_quality_penalty > 0:
        concerns.append(
            f"Project quality penalty applied ({breakdown.project_quality_penalty} pts)"
        )
    return concerns


def _github_summary_text(enrichment: Optional[GitHubEnrichmentResult]) -> str:
    """Return a one-line human-readable GitHub summary for the report."""
    if enrichment is None:
        return "GitHub enrichment not attempted."
    if enrichment.status == "success":
        return (
            f"GitHub @{enrichment.github_username}: "
            f"{enrichment.public_repos or 0} public repos, "
            f"{enrichment.followers or 0} followers. "
            f"{enrichment.recent_activity_summary}"
        )
    if enrichment.status == "no_github":
        return "No GitHub profile URL found in resume."
    if enrichment.status == "missing_profile":
        return f"GitHub profile '{enrichment.github_username}' not found (404)."
    if enrichment.status == "rate_limited":
        return "GitHub API rate limit exceeded; score contribution set to 0."
    return f"GitHub enrichment failed: {enrichment.error_message or 'unknown error'}"


# ──────────────────────────────────────────────────────────────────────────────
# Public API: build_batch_report
# ──────────────────────────────────────────────────────────────────────────────

def build_batch_report(
    results: List[FileExtractionResult],
    enrich_github_profiles: bool = True,
    write_json: bool = False,
) -> BatchReport:
    """
    Build the complete BatchReport from per-file extraction results.

    Args:
        results:                Output of the /screen or /report processing loop.
        enrich_github_profiles: Set False in tests to skip live GitHub calls.
        write_json:             If True, write results.json after building the
                                report (non-fatal failure).

    Returns:
        BatchReport with ranked eligible candidates, rejected candidates,
        failed/no-text files, duplicates, and batch summary statistics.
    """
    # Clear the per-run cache at the start of every batch
    if enrich_github_profiles:
        clear_enrichment_cache()

    ranked_list: List[RankedCandidate] = []
    rejected_list: List[RejectedCandidate] = []
    failed_list: List[FailedFile] = []
    duplicate_list: List[DuplicateFile] = []

    total_parsed = 0
    total_eligible = 0
    total_ineligible = 0
    total_failed = 0
    total_no_text = 0

    # ── Duplicate detection: SHA-256 per file ─────────────────────────────────
    # file_hash is populated in main.py before calling build_batch_report.
    seen_hashes: Dict[str, str] = {}  # hash → first filename seen

    for result in results:
        file_hash = result.file_hash

        # Detect byte-identical files
        if file_hash and file_hash in seen_hashes:
            original = seen_hashes[file_hash]
            duplicate_list.append(DuplicateFile(
                filename=result.filename,
                original_filename=original,
                file_hash=file_hash,
            ))
            logger.info(
                "Duplicate file detected: '%s' is identical to '%s' (hash %s).",
                result.filename, original, file_hash[:12],
            )
            continue  # do not process duplicate

        if file_hash:
            seen_hashes[file_hash] = result.filename

        # ── Failed / no-text files ─────────────────────────────────────────
        if result.status.value in ("failed", "no_text"):
            failed_list.append(FailedFile(
                filename=result.filename,
                status=result.status.value,
                failure_stage="pdf_parsing",
                error_message=result.error_message,
            ))
            if result.status.value == "failed":
                total_failed += 1
            else:
                total_no_text += 1
            continue

        total_parsed += 1

        # ── Ineligible candidates ─────────────────────────────────────────
        if result.eligible is False:
            total_ineligible += 1
            rejected_list.append(RejectedCandidate(
                filename=result.filename,
                candidate_name=_safe_name(result),
                eligible=False,
                email=_safe_email(result),
                rejection_reasons=result.rejection_reasons,
                matched_skills=result.matched_skills,
                python_evidence=result.python_evidence,
                ai_evidence=result.ai_evidence,
            ))
            continue

        # ── Eligible candidates: score → enrich → bonus ───────────────────
        if result.eligible is True and result.candidate_profile:
            total_eligible += 1
            profile = result.candidate_profile
            raw_text = result.extracted_text or ""

            # Step 1: Compute rubric score (GitHub = 0 at this point)
            try:
                breakdown: ScoreBreakdown = score_candidate(profile, raw_text)
            except Exception as exc:
                logger.warning(
                    "Scoring failed for '%s': %s — assigning zero score.",
                    result.filename, str(exc),
                )
                breakdown = ScoreBreakdown(total_score=0)

            # Step 2: GitHub enrichment & bonus
            github_enrichment: Optional[GitHubEnrichmentResult] = None
            if enrich_github_profiles:
                try:
                    github_enrichment = enrich_github(profile.github_url)
                    breakdown = _apply_github_bonus(breakdown, github_enrichment)
                except Exception as exc:
                    logger.warning(
                        "GitHub enrichment exception for '%s': %s",
                        result.filename, str(exc),
                    )
                    github_enrichment = GitHubEnrichmentResult(
                        status="failed",
                        error_message=str(exc),
                    )
            else:
                if profile.github_url:
                    github_enrichment = GitHubEnrichmentResult(status="skipped")
                else:
                    github_enrichment = GitHubEnrichmentResult(status="no_github")

            # Step 3: Derive narrative fields
            strengths = _derive_strengths(profile, breakdown)
            concerns = _derive_concerns(profile, breakdown)
            gh_summary = _github_summary_text(github_enrichment)

            ranked_list.append(RankedCandidate(
                rank=0,  # assigned after sorting
                filename=result.filename,
                candidate_name=_safe_name(result),
                eligible=True,
                email=_safe_email(result),
                github_url=_safe_github_url(result),
                total_score=breakdown.total_score,
                score_breakdown=breakdown,
                project_quality_penalty=breakdown.project_quality_penalty,
                matched_skills=result.matched_skills,
                project_summary=profile.project_summaries,
                github_summary=gh_summary,
                github_enrichment=github_enrichment,
                strengths=strengths,
                concerns=concerns,
                score_evidence=breakdown.score_evidence,
                python_evidence=result.python_evidence,
                ai_evidence=result.ai_evidence,
                project_summaries=profile.project_summaries,
            ))

    # ── Sort and assign ranks ──────────────────────────────────────────────────
    # Tie-break: 1. total_score desc  2. ai_project_depth desc
    #            3. python_backend desc  4. candidate_name asc
    ranked_list.sort(
        key=lambda c: (
            -c.total_score,
            -c.score_breakdown.ai_project_depth,
            -c.score_breakdown.python_backend,
            c.candidate_name.lower(),
        )
    )
    for idx, candidate in enumerate(ranked_list, start=1):
        ranked_list[idx - 1] = candidate.model_copy(update={"rank": idx})

    # ── Build summary statistics ───────────────────────────────────────────────
    scores = [c.total_score for c in ranked_list]
    total_failed_or_unreadable = total_failed + total_no_text

    summary = BatchSummaryStats(
        total_resumes=len(results),
        successfully_parsed=total_parsed,
        eligible=total_eligible,
        rejected=total_ineligible,
        failed_or_unreadable=total_failed_or_unreadable,
        duplicates=len(duplicate_list),
        highest_score=max(scores) if scores else None,
        lowest_score=min(scores) if scores else None,
        average_score=round(sum(scores) / len(scores), 1) if scores else None,
    )

    report = BatchReport(
        ranked_eligible_candidates=ranked_list,
        rejected_candidates=rejected_list,
        failed_resumes=failed_list,
        duplicates=duplicate_list,
        batch_summary=summary,
    )

    # ── Optional: write results.json ──────────────────────────────────────────
    if write_json:
        try:
            path = write_report(report)
            logger.info("results.json written to %s.", path)
        except Exception as exc:
            logger.error(
                "Non-fatal: could not write results.json — %s", str(exc)
            )

    return report
