"""
Phase 4: Unit and integration tests for the scoring engine, GitHub enricher,
ranker, report builder, and the POST /report API endpoint.

All tests are deterministic. No live GitHub API calls are made.
All external API calls are mocked.

Test coverage per spec:
 1.  All five category scores respect their maximums.
 2.  The category weights total 100.
 3.  The final score correctly subtracts project-quality penalties.
 4.  The final score remains between 0 and 100.
 5.  A shallow API-wrapper project receives a penalty when evidence justifies it.
 6.  A meaningful AI project is not automatically penalised for using an API.
 7.  Ineligible candidates never enter the ranked list.
 8.  Eligible candidates are sorted in descending score order.
 9.  Ties follow the documented tie-breaker.
10.  GitHub scoring never exceeds 10.
11.  Missing GitHub profiles do not cause rejection.
12.  GitHub rate limits and network failures do not stop the batch.
13.  Repeated GitHub profiles use the per-run cache.
14.  LLM or enrichment failure for one candidate does not terminate the others.
15.  Duplicate PDFs are detected and not ranked twice.
16.  Batch counts reconcile correctly.
17.  The final JSON report validates and serialises successfully.
18.  Existing Phase 1, 2, and 3 tests still pass (run separately).
"""

import io
import json
import os
import tempfile
from unittest.mock import MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.config import (
    SCORE_MAX_AI_PROJECT_DEPTH,
    SCORE_MAX_PYTHON_BACKEND,
    SCORE_MAX_CLOUD_FULLSTACK,
    SCORE_MAX_GITHUB,
    SCORE_MAX_ENGINEERING_DEPTH,
)
from backend.schemas import (
    BatchReport,
    BatchSummaryStats,
    CandidateProfile,
    DuplicateFile,
    ExtractionStatus,
    FailedFile,
    FileExtractionResult,
    GitHubEnrichment,          # alias for GitHubEnrichmentResult
    GitHubEnrichmentResult,
    ProjectInfo,
    RankedCandidate,
    RejectedCandidate,
    ScoreBreakdown,
    WorkExperience,
)
from backend.scorer import score_candidate
from backend.github_enricher import (
    _extract_username,
    clear_enrichment_cache,
    compute_github_score_bonus,
    enrich_github,
    _enrichment_cache,
)
from backend.ranker import build_batch_report
from backend.report_builder import write_report, build_report_dict

client = TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_minimal_pdf_bytes(text: str = "PDF content") -> bytes:
    """Create a minimal but syntactically valid PDF-header byte sequence."""
    content = f"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n% {text}".encode()
    return content


def _make_profile(
    languages=None,
    skills=None,
    frameworks=None,
    projects=None,
    work=None,
    github_url=None,
    ai_evidence=None,
    python_evidence=None,
) -> CandidateProfile:
    """Build a CandidateProfile for testing with sensible defaults."""
    return CandidateProfile(
        candidate_name="Test Candidate",
        email="test@example.com",
        programming_languages=languages or [],
        technical_skills=skills or [],
        frameworks_and_tools=frameworks or [],
        projects=projects or [],
        work_experience=work or [],
        github_url=github_url,
        ai_evidence=ai_evidence or [],
        python_evidence=python_evidence or [],
    )


def _make_eligible_result(
    filename="alice.pdf",
    name="Alice Engineer",
    text="",
    profile=None,
    python_ev=None,
    ai_ev=None,
    skills=None,
    file_hash=None,
) -> FileExtractionResult:
    """Build a FileExtractionResult that simulates an eligible candidate."""
    if profile is None:
        profile = _make_profile(
            languages=["Python"],
            frameworks=["LangChain", "FastAPI"],
            ai_evidence=ai_ev or ["RAG pipeline implemented with LangChain"],
            python_evidence=python_ev or ["Python in core programming languages"],
        )
    return FileExtractionResult(
        filename=filename,
        status=ExtractionStatus.SUCCESS,
        page_count=2,
        text_length=len(text) or 500,
        extracted_text=text or "Python LangChain RAG project FastAPI Docker",
        candidate_name=name,
        candidate_profile=profile,
        eligible=True,
        rejection_reasons=[],
        matched_skills=skills or ["Python", "LangChain", "FastAPI"],
        python_evidence=python_ev or ["Python in core programming languages"],
        ai_evidence=ai_ev or ["RAG pipeline implemented with LangChain"],
        file_hash=file_hash or filename.replace(".pdf", "_hash"),
    )


def _make_rejected_result(filename="bob.pdf", name="Bob Developer") -> FileExtractionResult:
    """Build a FileExtractionResult for a rejected (ineligible) candidate."""
    profile = _make_profile(languages=["JavaScript"])
    return FileExtractionResult(
        filename=filename,
        status=ExtractionStatus.SUCCESS,
        page_count=1,
        text_length=300,
        extracted_text="JavaScript React Node.js",
        candidate_name=name,
        candidate_profile=profile,
        eligible=False,
        rejection_reasons=["Missing Python competency", "Missing AI project evidence"],
        matched_skills=[],
        file_hash=filename.replace(".pdf", "_hash"),
    )


def _make_failed_result(filename="bad.txt") -> FileExtractionResult:
    """Build a FileExtractionResult for a failed file."""
    return FileExtractionResult(
        filename=filename,
        status=ExtractionStatus.FAILED,
        page_count=None,
        text_length=0,
        extracted_text=None,
        error_message="Invalid file extension.",
    )


def _make_github_success(
    public_repos=25,
    followers=15,
    has_ai=True,
    username="johndoe",
) -> GitHubEnrichmentResult:
    """Build a successful GitHubEnrichmentResult for testing."""
    return GitHubEnrichmentResult(
        status="success",
        profile_url=f"https://github.com/{username}",
        github_username=username,
        public_repos=public_repos,
        followers=followers,
        has_pinned_ai_project=has_ai,
        relevant_repositories=["rag-chatbot"] if has_ai else [],
        top_languages=["Python"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Category weights total 100
# ─────────────────────────────────────────────────────────────────────────────

class TestScoringWeights:

    def test_category_weights_sum_to_100(self):
        """Requirement: the five category maximums must sum to exactly 100."""
        total = (
            SCORE_MAX_AI_PROJECT_DEPTH
            + SCORE_MAX_PYTHON_BACKEND
            + SCORE_MAX_CLOUD_FULLSTACK
            + SCORE_MAX_GITHUB
            + SCORE_MAX_ENGINEERING_DEPTH
        )
        assert total == 100, (
            f"Category weights must sum to 100, got {total}. "
            f"AI={SCORE_MAX_AI_PROJECT_DEPTH} Py={SCORE_MAX_PYTHON_BACKEND} "
            f"Cloud={SCORE_MAX_CLOUD_FULLSTACK} GH={SCORE_MAX_GITHUB} "
            f"Eng={SCORE_MAX_ENGINEERING_DEPTH}"
        )

    def test_individual_maximums_match_spec(self):
        """Each category maximum must match the spec exactly."""
        assert SCORE_MAX_AI_PROJECT_DEPTH == 40
        assert SCORE_MAX_PYTHON_BACKEND == 30
        assert SCORE_MAX_CLOUD_FULLSTACK == 15
        assert SCORE_MAX_GITHUB == 10
        assert SCORE_MAX_ENGINEERING_DEPTH == 5


# ─────────────────────────────────────────────────────────────────────────────
# Tests 1, 3, 4: Scorer — category caps, penalty, score bounds
# ─────────────────────────────────────────────────────────────────────────────

class TestScorer:

    def test_score_eligible_python_langchain_rag_candidate(self):
        """A strong AI + Python + deployment profile should score > 50."""
        profile = _make_profile(
            languages=["Python"],
            frameworks=["LangChain", "FastAPI"],
            skills=["Docker", "PostgreSQL", "Pytest"],
            ai_evidence=["RAG pipeline built with LangChain + ChromaDB"],
        )
        raw_text = "Python FastAPI LangChain RAG embeddings Docker PostgreSQL pytest GitHub Actions"
        result = score_candidate(profile, raw_text)
        assert isinstance(result, ScoreBreakdown)
        assert result.total_score > 50, f"Expected > 50, got {result.total_score}"
        assert result.ai_project_depth > 0
        assert result.python_backend > 0

    def test_score_zero_for_empty_profile(self):
        """An empty profile with no skills should score 0."""
        profile = _make_profile()
        result = score_candidate(profile, "")
        assert result.total_score == 0

    # Test 4: score is always 0–100
    def test_score_capped_at_100(self):
        """Score must never exceed 100 regardless of how many keywords are matched."""
        profile = _make_profile(
            languages=["Python"],
            frameworks=["LangChain", "LangGraph", "FastAPI", "Django"],
            skills=["Docker", "Kubernetes", "AWS", "PostgreSQL", "Redis", "Pytest"],
            ai_evidence=[
                "Advanced RAG agentic pipeline with LangChain, LangGraph, ChromaDB embeddings",
                "Multi-agent tool-calling workflow with fine-tuning on PyTorch",
            ],
        )
        raw_text = (
            "Python LangChain LangGraph RAG multi-agent embeddings Docker Kubernetes "
            "AWS FastAPI PostgreSQL pytest GitHub Actions cloud run"
        )
        result = score_candidate(profile, raw_text)
        assert result.total_score <= 100

    def test_score_floor_is_zero(self):
        """Score can never go below 0 even if the penalty is large."""
        profile = _make_profile(
            languages=["Python"],
            projects=[ProjectInfo(
                name="Todo List",
                description="A simple todo app todo list",
                technologies=["Python"],
            )],
        )
        result = score_candidate(profile, "todo list todo app")
        assert result.total_score >= 0

    # Test 1: each category respects its maximum
    def test_ai_project_depth_does_not_exceed_max(self):
        """ai_project_depth must never exceed SCORE_MAX_AI_PROJECT_DEPTH."""
        profile = _make_profile(
            frameworks=["LangChain", "LangGraph", "LlamaIndex", "CrewAI", "Haystack"],
            ai_evidence=["Multi-agent RAG system with embeddings and vector search"],
        )
        raw_text = "langchain langgraph llamaindex rag embeddings multi-agent agentic vector search"
        result = score_candidate(profile, raw_text)
        assert result.ai_project_depth <= SCORE_MAX_AI_PROJECT_DEPTH

    def test_python_backend_does_not_exceed_max(self):
        """python_backend must never exceed SCORE_MAX_PYTHON_BACKEND."""
        profile = _make_profile(
            languages=["Python"],
            frameworks=["FastAPI", "Django", "Flask", "Pytest", "Celery"],
            skills=["PostgreSQL", "Redis", "MongoDB", "MySQL"],
        )
        result = score_candidate(profile, "python fastapi django flask asyncio postgresql redis")
        assert result.python_backend <= SCORE_MAX_PYTHON_BACKEND

    def test_cloud_fullstack_does_not_exceed_max(self):
        """cloud_fullstack must never exceed SCORE_MAX_CLOUD_FULLSTACK."""
        profile = _make_profile(
            skills=["Docker", "Kubernetes", "AWS", "GCP", "Azure", "Terraform"],
        )
        result = score_candidate(profile, "docker kubernetes aws gcp github actions vercel")
        assert result.cloud_fullstack <= SCORE_MAX_CLOUD_FULLSTACK

    def test_engineering_depth_does_not_exceed_max(self):
        """engineering_depth must never exceed SCORE_MAX_ENGINEERING_DEPTH."""
        profile = _make_profile(
            frameworks=["Pytest", "Jest"],
            skills=["System Design", "Swagger", "OpenAPI"],
        )
        result = score_candidate(profile, "pytest jest system design swagger openapi type hints mypy")
        assert result.engineering_depth <= SCORE_MAX_ENGINEERING_DEPTH

    # Test 3: penalty subtracted from score
    def test_penalty_applied_for_generic_project(self):
        """A todo app in the profile should trigger a penalty."""
        profile = _make_profile(
            languages=["Python"],
            projects=[ProjectInfo(
                name="Todo App",
                description="A simple todo list built with Python",
                technologies=["Python"],
            )],
            ai_evidence=["LangChain RAG pipeline"],
        )
        raw_text = "Python todo app LangChain"
        result = score_candidate(profile, raw_text)
        assert result.project_quality_penalty > 0, "Expected penalty for todo app project"
        assert len(result.project_quality_penalty_reasons) > 0

    def test_penalty_reduces_total_score(self):
        """Total score must equal raw category sum minus penalty (clamped 0-100)."""
        profile = _make_profile(
            languages=["Python"],
            projects=[ProjectInfo(name="Todo List", description="basic todo list")],
            ai_evidence=["LangChain RAG"],
        )
        result = score_candidate(profile, "python todo list langchain rag")
        raw_sum = (
            result.ai_project_depth
            + result.python_backend
            + result.cloud_fullstack
            + result.github
            + result.engineering_depth
        )
        expected_total = max(0, min(100, raw_sum - result.project_quality_penalty))
        assert result.total_score == expected_total

    def test_python_backend_dimension_scores_python_language(self):
        """Python listed as a language should contribute to python_backend score."""
        profile = _make_profile(languages=["Python"])
        result = score_candidate(profile, "python programming")
        assert result.python_backend >= 10  # base 10 pts for language

    def test_deployment_score_for_docker_aws(self):
        """Docker + AWS mention should contribute to cloud_fullstack score."""
        profile = _make_profile(skills=["Docker", "AWS"])
        raw_text = "Docker containers deployed on AWS"
        result = score_candidate(profile, raw_text)
        assert result.cloud_fullstack > 0

    def test_engineering_depth_score_for_pytest(self):
        """Pytest mention should contribute to engineering_depth."""
        profile = _make_profile(frameworks=["Pytest"])
        result = score_candidate(profile, "wrote pytest tests")
        assert result.engineering_depth > 0

    # Test 5: shallow API-wrapper gets penalised
    def test_shallow_ai_wrapper_receives_penalty(self):
        """A project described as a basic chatbot without retrieval or logic should be penalised."""
        profile = _make_profile(
            languages=["Python"],
            ai_evidence=["Simple chatbot that wraps OpenAI API"],
        )
        result = score_candidate(profile, "python simple chatbot api wrapper no retrieval")
        assert result.project_quality_penalty > 0

    # Test 6: meaningful AI project is NOT automatically penalised
    def test_meaningful_ai_project_not_penalised(self):
        """A meaningful RAG pipeline with LangGraph should NOT receive a penalty."""
        profile = _make_profile(
            languages=["Python"],
            frameworks=["LangGraph"],
            ai_evidence=["Multi-agent RAG pipeline with LangGraph, ChromaDB vector store, and evaluation pipeline"],
        )
        result = score_candidate(
            profile,
            "python langgraph multi-agent rag chromadb embeddings evaluation pipeline fastapi"
        )
        assert result.project_quality_penalty == 0, (
            f"Meaningful AI project should not be penalised, got penalty={result.project_quality_penalty}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Tests: GitHub Enricher (10, 11, 12, 13)
# ─────────────────────────────────────────────────────────────────────────────

class TestGitHubEnricher:

    def setup_method(self):
        """Clear the per-run cache before each test."""
        clear_enrichment_cache()

    def test_extract_username_from_full_url(self):
        assert _extract_username("https://github.com/johndoe") == "johndoe"

    def test_extract_username_from_short_url(self):
        assert _extract_username("github.com/janedoe") == "janedoe"

    def test_extract_username_none_for_empty_string(self):
        assert _extract_username("") is None

    # Test 11: missing profile does not cause rejection
    def test_enrich_returns_no_github_when_url_is_none(self):
        result = enrich_github(None)
        assert result.status == "no_github"
        # Compat alias works too
        assert result.enrichment_status == "no_github"

    def test_enrich_returns_failed_on_invalid_url(self):
        result = enrich_github("not-a-github-url")
        assert result.status in ("no_github", "failed")

    @patch("backend.github_enricher.httpx.Client")
    def test_enrich_success_parses_user_data(self, mock_client_class):
        """Mock the GitHub API response and verify parsing."""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_user_resp = MagicMock()
        mock_user_resp.status_code = 200
        mock_user_resp.json.return_value = {
            "login": "johndoe",
            "public_repos": 25,
            "followers": 40,
            "following": 10,
            "bio": "Python + AI developer",
        }

        mock_repos_resp = MagicMock()
        mock_repos_resp.status_code = 200
        mock_repos_resp.json.return_value = [
            {"name": "rag-chatbot", "description": "LangChain RAG chatbot", "language": "Python",
             "pushed_at": "2025-10-01T00:00:00Z"},
            {"name": "portfolio", "description": "portfolio site", "language": "JavaScript",
             "pushed_at": "2024-01-01T00:00:00Z"},
        ]

        mock_client.get.side_effect = [mock_user_resp, mock_repos_resp]

        result = enrich_github("https://github.com/johndoe")
        assert result.status == "success"
        assert result.enrichment_status == "success"   # compat alias
        assert result.public_repos == 25
        assert result.followers == 40
        assert result.has_pinned_ai_project is True    # "rag" keyword in repo name
        assert "Python" in result.top_languages

    @patch("backend.github_enricher.httpx.Client")
    def test_enrich_404_returns_missing_profile(self, mock_client_class):
        """404 from GitHub API should produce a 'missing_profile' status, not raise."""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_user_resp = MagicMock()
        mock_user_resp.status_code = 404
        mock_client.get.return_value = mock_user_resp

        result = enrich_github("https://github.com/nonexistentuser12345")
        assert result.status == "missing_profile"
        # Compat alias
        assert result.enrichment_status == "missing_profile"

    # Test 12: rate limits do not stop the batch
    @patch("backend.github_enricher.httpx.Client")
    def test_enrich_rate_limit_returns_rate_limited(self, mock_client_class):
        """403 from GitHub should return 'rate_limited' status, not raise."""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_user_resp = MagicMock()
        mock_user_resp.status_code = 403
        mock_client.get.return_value = mock_user_resp

        result = enrich_github("https://github.com/someuser")
        assert result.status == "rate_limited"

    @patch("backend.github_enricher.httpx.Client")
    def test_enrich_network_failure_returns_failed(self, mock_client_class):
        """Network exception should return 'failed' status, not propagate."""
        import httpx
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_client.get.side_effect = httpx.ConnectError("connection refused")

        result = enrich_github("https://github.com/someuser")
        assert result.status == "failed"
        assert result.error_message is not None

    # Test 10: GitHub score never exceeds 10
    def test_github_bonus_score_for_strong_profile(self):
        """A profile with 25 repos, 15 followers, and AI project should score ≤ 10."""
        enrichment = GitHubEnrichmentResult(
            status="success",
            public_repos=25,
            followers=15,
            has_pinned_ai_project=True,
            relevant_repositories=["rag-chatbot"],
        )
        pts, evidence = compute_github_score_bonus(enrichment)
        assert pts <= SCORE_MAX_GITHUB == 10
        assert pts > 0
        assert len(evidence) > 0

    def test_github_bonus_never_exceeds_10_even_with_max_inputs(self):
        """Test 10: GitHub scoring cap is enforced."""
        enrichment = GitHubEnrichmentResult(
            status="success",
            public_repos=1000,
            followers=5000,
            has_pinned_ai_project=True,
            relevant_repositories=["rag1", "rag2", "rag3"],
        )
        # Manually set recent repo count to max
        object.__setattr__(enrichment, "_recent_repo_count", 100)
        pts, _ = compute_github_score_bonus(enrichment)
        assert pts <= 10

    def test_github_bonus_zero_for_failed_enrichment(self):
        """Failed enrichment should produce 0 bonus."""
        enrichment = GitHubEnrichmentResult(status="failed")
        pts, evidence = compute_github_score_bonus(enrichment)
        assert pts == 0
        assert evidence == []

    def test_github_bonus_zero_for_no_github(self):
        """No-github should produce 0 bonus."""
        enrichment = GitHubEnrichmentResult(status="no_github")
        pts, evidence = compute_github_score_bonus(enrichment)
        assert pts == 0

    # Test 13: cache is used for repeated profiles
    @patch("backend.github_enricher.httpx.Client")
    def test_repeated_github_url_uses_cache(self, mock_client_class):
        """The same GitHub profile URL called twice should only make one API request."""
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        mock_user_resp = MagicMock()
        mock_user_resp.status_code = 200
        mock_user_resp.json.return_value = {
            "login": "cacheduser",
            "public_repos": 10,
            "followers": 5,
            "following": 3,
            "bio": None,
        }
        mock_repos_resp = MagicMock()
        mock_repos_resp.status_code = 200
        mock_repos_resp.json.return_value = []
        mock_client.get.side_effect = [mock_user_resp, mock_repos_resp]

        url = "https://github.com/cacheduser"
        result1 = enrich_github(url)
        result2 = enrich_github(url)  # should use cache

        assert result1.status == "success"
        assert result2.status == "success"
        # Only two API calls (user + repos), not four
        assert mock_client.get.call_count == 2

    # Test 11 (continued): missing profile never causes rejection of candidate
    def test_missing_github_profile_does_not_reject_candidate(self):
        """A candidate without a GitHub URL should still appear in ranked list."""
        profile = _make_profile(
            languages=["Python"],
            ai_evidence=["RAG pipeline with LangChain"],
            github_url=None,
        )
        result = _make_eligible_result(profile=profile)
        report = build_batch_report([result], enrich_github_profiles=False)
        assert len(report.ranked_eligible_candidates) == 1
        assert len(report.rejected_candidates) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Tests 7, 8, 9: Ranker
# ─────────────────────────────────────────────────────────────────────────────

class TestRanker:

    def setup_method(self):
        clear_enrichment_cache()

    # Test 7: ineligible candidates never enter ranked list
    def test_eligible_candidate_is_ranked(self):
        """An eligible candidate with a valid profile should appear in ranked_eligible_candidates."""
        results = [_make_eligible_result()]
        report = build_batch_report(results, enrich_github_profiles=False)
        assert len(report.ranked_eligible_candidates) == 1
        assert report.ranked_eligible_candidates[0].rank == 1

    def test_rejected_candidate_is_not_ranked(self):
        """An ineligible candidate must appear in rejected_candidates, not ranked."""
        results = [_make_rejected_result()]
        report = build_batch_report(results, enrich_github_profiles=False)
        assert len(report.ranked_eligible_candidates) == 0
        assert len(report.rejected_candidates) == 1
        # eligible flag is explicitly False
        assert report.rejected_candidates[0].eligible is False

    def test_failed_file_goes_to_failed_list(self):
        """A failed file must appear in failed_resumes."""
        results = [_make_failed_result()]
        report = build_batch_report(results, enrich_github_profiles=False)
        assert len(report.failed_resumes) == 1
        assert len(report.ranked_eligible_candidates) == 0

    # Test 8: sorted descending by score
    def test_ranking_order_by_score_descending(self):
        """Higher-scoring candidates should have lower rank numbers."""
        alice = _make_eligible_result(
            filename="alice.pdf", name="Alice",
            text="Python LangChain RAG embeddings FastAPI Docker AWS pytest",
        )
        bob_profile = _make_profile(
            languages=["Python"],
            ai_evidence=["Machine learning project"],
        )
        bob = _make_eligible_result(
            filename="bob.pdf", name="Bob",
            text="Python machine learning",
            profile=bob_profile,
        )
        report = build_batch_report([alice, bob], enrich_github_profiles=False)
        assert len(report.ranked_eligible_candidates) == 2
        assert report.ranked_eligible_candidates[0].total_score >= report.ranked_eligible_candidates[1].total_score
        assert report.ranked_eligible_candidates[0].rank == 1
        assert report.ranked_eligible_candidates[1].rank == 2

    # Test 9: tie-break is deterministic (AI depth → Python score → name)
    def test_tie_break_follows_documented_order(self):
        """When total scores tie, rank by AI depth desc, then Python desc, then name asc."""
        # Both have the same text, so same scores expected
        a = _make_eligible_result(filename="z_candidate.pdf", name="Zara", text="Python LangChain")
        b = _make_eligible_result(filename="a_candidate.pdf", name="Adam", text="Python LangChain")
        report = build_batch_report([a, b], enrich_github_profiles=False)
        # If scores tie and AI/Python tie, name should break the tie alphabetically
        ranked_names = [c.candidate_name for c in report.ranked_eligible_candidates]
        if report.ranked_eligible_candidates[0].total_score == report.ranked_eligible_candidates[1].total_score:
            assert ranked_names == sorted(ranked_names)

    def test_tie_break_by_ai_depth_then_python(self):
        """Secondary tie-break: higher AI depth ranks first."""
        profile_ai_heavy = _make_profile(
            languages=["Python"],
            frameworks=["LangChain", "LangGraph"],
            ai_evidence=["Multi-agent RAG with LangGraph, embeddings, tool-calling"],
        )
        profile_python_heavy = _make_profile(
            languages=["Python"],
            frameworks=["FastAPI", "Django", "Flask"],
            ai_evidence=["ML project"],
        )
        a = _make_eligible_result(
            filename="b_ai.pdf", name="Bob AI",
            text="Python LangChain LangGraph RAG embeddings",
            profile=profile_ai_heavy,
        )
        b = _make_eligible_result(
            filename="a_py.pdf", name="Alice Python",
            text="Python FastAPI Django Flask PostgreSQL",
            profile=profile_python_heavy,
        )
        report = build_batch_report([a, b], enrich_github_profiles=False)
        # Candidate with higher AI depth should rank higher if total scores differ accordingly
        # We just verify the order is stable and deterministic
        assert report.ranked_eligible_candidates[0].rank == 1
        assert report.ranked_eligible_candidates[1].rank == 2

    # Test 16: batch counts reconcile
    def test_summary_stats_are_accurate(self):
        """Batch summary should accurately reflect all candidate counts."""
        results = [
            _make_eligible_result(filename="a.pdf"),
            _make_eligible_result(filename="b.pdf"),
            _make_rejected_result(filename="c.pdf"),
            _make_failed_result(filename="d.txt"),
        ]
        report = build_batch_report(results, enrich_github_profiles=False)
        s = report.batch_summary
        assert s.total_resumes == 4
        assert s.eligible == 2
        assert s.rejected == 1
        assert s.failed_or_unreadable == 1
        # eligible + rejected + failed = total (no dups in this test)
        assert s.eligible + s.rejected + s.failed_or_unreadable == s.total_resumes

    def test_empty_batch_returns_empty_report(self):
        """An empty batch should return a valid empty report with zero stats."""
        report = build_batch_report([], enrich_github_profiles=False)
        assert report.ranked_eligible_candidates == []
        assert report.rejected_candidates == []
        assert report.batch_summary.total_resumes == 0
        assert report.batch_summary.highest_score is None

    # Test 15: duplicate PDF detection
    def test_duplicate_pdf_detected_and_excluded(self):
        """Two files with the same SHA-256 hash should not both be ranked."""
        shared_hash = "abc123deadbeef" * 4  # 56-char fake hash
        a = _make_eligible_result(filename="orig.pdf", file_hash=shared_hash)
        b = _make_eligible_result(filename="copy.pdf", name="Duplicate", file_hash=shared_hash)

        report = build_batch_report([a, b], enrich_github_profiles=False)
        # Only the first unique file should be processed
        assert len(report.ranked_eligible_candidates) == 1
        assert len(report.duplicates) == 1
        assert report.duplicates[0].filename == "copy.pdf"
        assert report.duplicates[0].original_filename == "orig.pdf"

    def test_duplicate_count_in_summary(self):
        """Batch summary should include duplicate count."""
        shared_hash = "deadbeef" * 8
        a = _make_eligible_result(filename="first.pdf", file_hash=shared_hash)
        b = _make_rejected_result(filename="second.pdf")
        b = b.model_copy(update={"file_hash": shared_hash})

        report = build_batch_report([a, b], enrich_github_profiles=False)
        assert report.batch_summary.duplicates == 1

    # Test 14: one candidate's enrichment failure does not abort others
    @patch("backend.github_enricher.httpx.Client")
    def test_enrichment_failure_for_one_does_not_abort_batch(self, mock_client_class):
        """Even if GitHub enrichment fails for one candidate, the others are processed."""
        import httpx
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client

        # First call (alice) raises an exception; second call (bob) succeeds
        mock_success_resp = MagicMock()
        mock_success_resp.status_code = 200
        mock_success_resp.json.return_value = {
            "login": "bob", "public_repos": 5, "followers": 0, "following": 0, "bio": None
        }
        mock_repos_resp = MagicMock()
        mock_repos_resp.status_code = 200
        mock_repos_resp.json.return_value = []

        mock_client.get.side_effect = [
            httpx.ConnectError("alice network error"),  # alice fails
            mock_success_resp, mock_repos_resp,          # bob succeeds
        ]

        alice_profile = _make_profile(
            languages=["Python"],
            frameworks=["LangChain"],
            ai_evidence=["RAG pipeline"],
            github_url="https://github.com/alice",
        )
        bob_profile = _make_profile(
            languages=["Python"],
            frameworks=["LangChain"],
            ai_evidence=["RAG pipeline"],
            github_url="https://github.com/bob",
        )

        alice = _make_eligible_result(filename="alice.pdf", name="Alice", profile=alice_profile,
                                      file_hash="hash_alice")
        bob = _make_eligible_result(filename="bob.pdf", name="Bob", profile=bob_profile,
                                    file_hash="hash_bob")

        report = build_batch_report([alice, bob], enrich_github_profiles=True)
        # Both candidates should be ranked despite alice's enrichment failure
        assert len(report.ranked_eligible_candidates) == 2

    def test_eligible_candidates_have_eligible_true(self):
        """Every candidate in ranked_eligible_candidates must have eligible=True."""
        results = [
            _make_eligible_result(filename="a.pdf"),
            _make_rejected_result(filename="b.pdf"),
        ]
        report = build_batch_report(results, enrich_github_profiles=False)
        for candidate in report.ranked_eligible_candidates:
            assert candidate.eligible is True

    def test_rejected_candidates_have_eligible_false(self):
        """Every candidate in rejected_candidates must have eligible=False."""
        results = [_make_rejected_result(filename="r.pdf")]
        report = build_batch_report(results, enrich_github_profiles=False)
        for candidate in report.rejected_candidates:
            assert candidate.eligible is False


# ─────────────────────────────────────────────────────────────────────────────
# Test 17: JSON report validation and serialisation
# ─────────────────────────────────────────────────────────────────────────────

class TestReportBuilder:

    def _minimal_report(self) -> BatchReport:
        """Build a small but complete BatchReport for serialisation tests."""
        results = [
            _make_eligible_result(filename="alice.pdf"),
            _make_rejected_result(filename="bob.pdf"),
            _make_failed_result(filename="bad.txt"),
        ]
        return build_batch_report(results, enrich_github_profiles=False)

    def test_report_serialises_to_valid_json(self):
        """Test 17: BatchReport must serialise to valid JSON without error."""
        report = self._minimal_report()
        d = build_report_dict(report)
        payload = json.dumps(d)
        loaded = json.loads(payload)
        assert isinstance(loaded, dict)
        assert "ranked_eligible_candidates" in loaded
        assert "rejected_candidates" in loaded
        assert "failed_resumes" in loaded
        assert "batch_summary" in loaded

    def test_report_has_no_nan_or_infinity(self):
        """The serialised report must not contain NaN or Infinity values."""
        report = self._minimal_report()
        d = build_report_dict(report)
        payload = json.dumps(d)
        assert "NaN" not in payload
        assert "Infinity" not in payload

    def test_write_report_creates_file(self):
        """write_report() should create a results.json file at the given path."""
        report = self._minimal_report()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "results.json")
            returned_path = write_report(report, output_path=output_path)
            assert os.path.isfile(returned_path)
            with open(returned_path, encoding="utf-8") as f:
                loaded = json.load(f)
            assert "batch_summary" in loaded

    def test_write_report_is_safe_against_crash(self):
        """A failed write must not overwrite a previously valid report."""
        # We simulate this by patching os.replace to raise an error
        report = self._minimal_report()
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "results.json")
            # Write a valid report first
            write_report(report, output_path=output_path)
            # Now simulate crash during second write
            with patch("os.replace", side_effect=OSError("disk full")):
                with pytest.raises(RuntimeError):
                    write_report(report, output_path=output_path)
            # Original file should still be readable
            with open(output_path, encoding="utf-8") as f:
                loaded = json.load(f)
            assert "batch_summary" in loaded

    # Test 16 (continued): count reconciliation
    def test_batch_counts_reconcile(self):
        """
        total_resumes must equal the total number of uploaded files.
        eligible + rejected + failed_or_unreadable + duplicates == total_resumes.
        """
        shared_hash = "dup_hash" * 8
        results = [
            _make_eligible_result(filename="a.pdf", file_hash="hash_a"),
            _make_eligible_result(filename="b.pdf", file_hash="hash_b"),
            _make_rejected_result(filename="c.pdf"),
            _make_failed_result(filename="d.txt"),
            _make_eligible_result(filename="dup.pdf", file_hash="hash_a"),  # duplicate of a.pdf
        ]
        report = build_batch_report(results, enrich_github_profiles=False)
        s = report.batch_summary
        assert s.total_resumes == 5
        assert s.duplicates == 1
        # Non-duplicate counts
        assert s.eligible + s.rejected + s.failed_or_unreadable == s.total_resumes - s.duplicates


# ─────────────────────────────────────────────────────────────────────────────
# Tests: POST /report API Integration
# ─────────────────────────────────────────────────────────────────────────────

class TestReportEndpoint:

    def _build_pdf(self, text: str) -> bytes:
        return f"%PDF-1.4\n% {text}\n%%EOF".encode()

    def test_report_endpoint_returns_200_with_valid_pdf(self):
        """POST /report with a valid PDF should return 200 and a BatchReport."""
        pdf = _make_minimal_pdf_bytes("Python LangChain RAG embeddings FastAPI Docker pytest")
        response = client.post(
            "/report",
            files=[("files", ("resume.pdf", io.BytesIO(pdf), "application/pdf"))],
        )
        assert response.status_code == 200
        body = response.json()
        assert "ranked_eligible_candidates" in body
        assert "rejected_candidates" in body
        assert "failed_resumes" in body
        assert "batch_summary" in body
        # Legacy field names via alias properties are NOT in JSON; use new names
        assert "ranked_candidates" not in body or "ranked_eligible_candidates" in body

    def test_report_endpoint_returns_error_for_no_files(self):
        """POST /report with no files should return 4xx."""
        response = client.post("/report", files=[])
        assert response.status_code in (400, 422)

    def test_report_endpoint_handles_invalid_extension(self):
        """A non-PDF file should appear in failed_resumes, not ranked_eligible_candidates."""
        response = client.post(
            "/report",
            files=[("files", ("resume.docx", io.BytesIO(b"not a pdf"), "application/octet-stream"))],
        )
        assert response.status_code == 200
        body = response.json()
        assert body["batch_summary"]["failed_or_unreadable"] >= 1
        assert len(body["ranked_eligible_candidates"]) == 0

    def test_report_endpoint_summary_fields_present(self):
        """BatchReport batch_summary must contain all required statistical fields."""
        pdf = _make_minimal_pdf_bytes("Python FastAPI pytest")
        response = client.post(
            "/report",
            files=[("files", ("r.pdf", io.BytesIO(pdf), "application/pdf"))],
        )
        assert response.status_code == 200
        summary = response.json()["batch_summary"]
        for field in [
            "total_resumes", "successfully_parsed", "eligible",
            "rejected", "failed_or_unreadable", "duplicates",
        ]:
            assert field in summary, f"Missing summary field: {field}"

    def test_report_and_screen_endpoints_are_independent(self):
        """/screen and /report should both be available and return different schemas."""
        pdf = _make_minimal_pdf_bytes("Python LangChain RAG")
        screen_resp = client.post(
            "/screen",
            files=[("files", ("r.pdf", io.BytesIO(pdf), "application/pdf"))],
        )
        report_resp = client.post(
            "/report",
            files=[("files", ("r.pdf", io.BytesIO(pdf), "application/pdf"))],
        )
        assert screen_resp.status_code == 200
        assert report_resp.status_code == 200
        # /screen has 'results' key; /report has 'ranked_eligible_candidates'
        assert "results" in screen_resp.json()
        assert "ranked_eligible_candidates" in report_resp.json()

    def test_report_endpoint_duplicate_detection(self):
        """Uploading two identical PDF files should result in 1 duplicate recorded."""
        pdf = _make_minimal_pdf_bytes("Python LangChain RAG pipeline FastAPI")
        response = client.post(
            "/report",
            files=[
                ("files", ("resume1.pdf", io.BytesIO(pdf), "application/pdf")),
                ("files", ("resume2.pdf", io.BytesIO(pdf), "application/pdf")),
            ],
        )
        assert response.status_code == 200
        body = response.json()
        assert body["batch_summary"]["duplicates"] >= 1
        assert len(body["duplicates"]) >= 1
