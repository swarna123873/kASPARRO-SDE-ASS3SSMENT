"""
Automated unit and integration tests for Phase 3 Candidate Extraction.
Covers deterministic heuristics (name, contact, skills, projects, education),
LLM adapter parsing, graceful fallbacks, and API integration.
"""

from unittest.mock import MagicMock
import fitz
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.candidate_extractor import (
    extract_candidate_name_heuristic,
    extract_deterministic_contact_info,
    deterministic_extract_candidate,
    extract_candidate_profile,
)
from backend.schemas import CandidateProfile, ExtractionStatus
from backend.llm_adapter import LLMAdapter

client = TestClient(app)

SAMPLE_RESUME_TEXT = """
Alex Morgan
alex.morgan@example.com | (555) 123-4567 | https://github.com/alexmorgan-dev

Education:
B.Tech in Computer Science - Stanford University 2024

Technical Skills:
Languages: Python, TypeScript, SQL, JavaScript
Frameworks & Tools: FastAPI, Docker, PostgreSQL, Git, Redis
AI & ML: LangChain, RAG, PyTorch, Vector Search, OpenAI

Technical Projects:
Autonomous AI Agent Pipeline
Built an agentic workflow using LangChain and FastAPI with vector search in ChromaDB.
Implemented semantic document ingestion and automated multi-step reasoning.

Full-Stack E-Commerce Service
Developed a RESTful backend using Python and PostgreSQL with Docker containerization.
"""


def create_sample_pdf_bytes(text: str) -> bytes:
    """Helper to generate an in-memory PDF from text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_extract_candidate_name_heuristic():
    """Verify name extraction heuristics accurately identify candidate names."""
    lines = ["RESUME", "Alex Morgan", "alex@example.com"]
    assert extract_candidate_name_heuristic(lines) == "Alex Morgan"

    lines_cv = ["CURRICULUM VITAE", "Jane Doe", "Contact: 555-0100"]
    assert extract_candidate_name_heuristic(lines_cv) == "Jane Doe"

    empty_lines = ["", "   ", "PAGE 1"]
    assert extract_candidate_name_heuristic(empty_lines) is None


def test_extract_deterministic_contact_info():
    """Verify regex extraction of email, phone, and GitHub URLs."""
    email, phone, github = extract_deterministic_contact_info(SAMPLE_RESUME_TEXT)
    assert email == "alex.morgan@example.com"
    assert phone == "(555) 123-4567"
    assert github == "https://github.com/alexmorgan-dev"

    # Test short GitHub format
    short_text = "Contact me at github.com/testuser or user@domain.org"
    em, ph, gh = extract_deterministic_contact_info(short_text)
    assert em == "user@domain.org"
    assert ph is None
    assert gh == "https://github.com/testuser"


def test_deterministic_extract_candidate():
    """Verify full deterministic profile extraction without LLM."""
    profile = deterministic_extract_candidate(SAMPLE_RESUME_TEXT)
    assert isinstance(profile, CandidateProfile)
    assert profile.candidate_name == "Alex Morgan"
    assert profile.email == "alex.morgan@example.com"
    assert profile.github_url == "https://github.com/alexmorgan-dev"

    # Languages
    assert "Python" in profile.programming_languages
    assert "Javascript" in profile.programming_languages or "Typescript" in profile.programming_languages

    # Skills & Tools
    assert any("Fastapi" in s or "FastAPI" in s for s in profile.technical_skills)
    assert any("Docker" in s for s in profile.technical_skills)

    # Frameworks & AI
    assert any("Langchain" in t or "LangChain" in t for t in profile.frameworks_and_tools)
    assert any("Rag" in t or "RAG" in t for t in profile.frameworks_and_tools)

    # Education & Projects
    assert len(profile.education) >= 1
    assert len(profile.projects) >= 1


def test_extract_candidate_profile_empty_text():
    """Verify safe fallback on empty or blank resume text."""
    profile = extract_candidate_profile("")
    assert profile.candidate_name == "Unknown"
    assert len(profile.extraction_warnings) > 0


def test_extract_candidate_profile_with_mock_llm():
    """Verify LLM extraction integrates properly when adapter is configured."""
    mock_adapter = MagicMock(spec=LLMAdapter)
    mock_adapter.is_configured.return_value = True
    mock_adapter.extract_candidate_data.return_value = {
        "candidate_name": "Alex Morgan",
        "email": "alex.morgan@example.com",
        "phone": "+1-555-123-4567",
        "education": ["B.Tech in Computer Science, Stanford University"],
        "programming_languages": ["Python", "TypeScript"],
        "technical_skills": ["FastAPI", "Docker", "PostgreSQL"],
        "frameworks_and_tools": ["LangChain", "PyTorch"],
        "projects": [
            {
                "name": "Autonomous AI Agent Pipeline",
                "description": "Agentic workflow with LangChain",
                "technologies": ["LangChain", "FastAPI", "ChromaDB"],
                "implementation_details": "Vector search with ChromaDB",
                "supporting_evidence": "Built an agentic workflow using LangChain and FastAPI",
            }
        ],
        "work_experience": [],
        "github_url": "https://github.com/alexmorgan-dev",
    }

    profile = extract_candidate_profile(SAMPLE_RESUME_TEXT, adapter=mock_adapter)
    assert profile.candidate_name == "Alex Morgan"
    assert profile.email == "alex.morgan@example.com"
    assert len(profile.projects) == 1
    assert profile.projects[0].name == "Autonomous AI Agent Pipeline"
    assert "LangChain" in profile.projects[0].technologies
    assert len(profile.extraction_warnings) == 0


def test_extract_candidate_profile_llm_exception_fallback():
    """Verify graceful fallback to deterministic parsing if LLM throws an exception."""
    mock_adapter = MagicMock(spec=LLMAdapter)
    mock_adapter.is_configured.return_value = True
    mock_adapter.extract_candidate_data.side_effect = RuntimeError("API rate limit or connection timeout")

    profile = extract_candidate_profile(SAMPLE_RESUME_TEXT, adapter=mock_adapter)
    assert profile.candidate_name == "Alex Morgan"
    assert profile.email == "alex.morgan@example.com"
    assert "Python" in profile.programming_languages
    assert len(profile.extraction_warnings) > 0


def test_screen_api_returns_structured_candidate_profile():
    """Integration test verifying POST /screen endpoint returns Phase 3 candidate profile."""
    pdf_bytes = create_sample_pdf_bytes(SAMPLE_RESUME_TEXT)
    response = client.post(
        "/screen",
        files=[("files", ("alex_morgan_resume.pdf", pdf_bytes, "application/pdf"))],
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 1
    assert data["successful_files"] == 1

    result = data["results"][0]
    assert result["filename"] == "alex_morgan_resume.pdf"
    assert result["status"] == ExtractionStatus.SUCCESS.value
    assert result["candidate_name"] == "Alex Morgan"
    assert result["candidate_profile"] is not None
    assert result["candidate_profile"]["email"] == "alex.morgan@example.com"
    assert "Python" in result["candidate_profile"]["programming_languages"]
    assert result["candidate_profile"]["github_url"] == "https://github.com/alexmorgan-dev"
