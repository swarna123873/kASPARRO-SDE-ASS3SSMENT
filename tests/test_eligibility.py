"""
Comprehensive automated tests for Phase 3 Deterministic Eligibility Rules Engine.
Validates all requirements from Milestone 3.7:
1. Python + AI candidate is eligible.
2. JS/React-only candidate is rejected.
3. Python without AI candidate is rejected.
4. AI without Python candidate is rejected.
5. Missing both requirements receives both rejection reasons.
6. Java/React candidate with qualifying Python + AI is accepted.
7. Missing email/phone/GitHub does NOT disqualify a candidate.
8. Isolated keyword mentions without project/implementation context.
9. Malformed LLM response handled safely.
10. LLM timeout or failure does not abort batch.
11. Failed PDF does not prevent other resumes from processing.
12. Batch counts (eligible & ineligible) are strictly consistent.
"""

from unittest.mock import MagicMock
import fitz
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas import CandidateProfile, ProjectInfo, WorkExperience, ExtractionStatus
from backend.eligibility import (
    evaluate_candidate_eligibility,
    evaluate_python_evidence,
    evaluate_ai_evidence,
)
from backend.candidate_extractor import extract_candidate_profile
from backend.llm_adapter import LLMAdapter

client = TestClient(app)


def make_pdf_bytes(text: str) -> bytes:
    """Create a minimal in-memory PDF with the provided text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=10)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# -----------------------------------------------------------------------------
# 1. Candidate with credible Python and meaningful AI-project evidence is ELIGIBLE
# -----------------------------------------------------------------------------
def test_eligible_candidate_with_python_and_ai():
    profile = CandidateProfile(
        candidate_name="Alice AI Developer",
        email="alice@example.com",
        programming_languages=["Python", "SQL"],
        technical_skills=["FastAPI", "Docker", "PostgreSQL"],
        frameworks_and_tools=["LangChain", "ChromaDB", "PyTorch"],
        projects=[
            ProjectInfo(
                name="RAG Document Assistant",
                description="Built an agentic document search pipeline with LangChain and vector embeddings in ChromaDB.",
                technologies=["Python", "LangChain", "FastAPI", "ChromaDB"],
                implementation_details="Integrated semantic vector retrieval and automated multi-step LLM reasoning.",
                supporting_evidence="Engineered an end-to-end RAG question answering system using Python and LangChain.",
            )
        ],
    )
    result = evaluate_candidate_eligibility(profile)
    assert result.eligible is True
    assert len(result.rejection_reasons) == 0
    assert len(result.python_evidence) > 0
    assert len(result.ai_evidence) > 0


# -----------------------------------------------------------------------------
# 2. JavaScript / React-only candidate is REJECTED
# -----------------------------------------------------------------------------
def test_javascript_react_only_candidate_rejected():
    profile = CandidateProfile(
        candidate_name="Bob Frontend Dev",
        email="bob@example.com",
        programming_languages=["JavaScript", "TypeScript", "HTML", "CSS"],
        technical_skills=["React", "Redux", "Tailwind CSS", "Node.js"],
        projects=[
            ProjectInfo(
                name="Portfolio Dashboard",
                description="Created a responsive web dashboard using React and Tailwind CSS.",
                technologies=["React", "JavaScript", "CSS"],
                implementation_details="Single page app with state management.",
                supporting_evidence="Designed interactive web client in React.",
            )
        ],
    )
    result = evaluate_candidate_eligibility(profile)
    assert result.eligible is False
    assert any("Python" in r for r in result.rejection_reasons)
    assert any("AI" in r or "LLM" in r or "RAG" in r for r in result.rejection_reasons)


# -----------------------------------------------------------------------------
# 3. Python candidate WITHOUT qualifying AI/agentic evidence is REJECTED
# -----------------------------------------------------------------------------
def test_python_only_without_ai_rejected():
    profile = CandidateProfile(
        candidate_name="Charlie Backend Dev",
        email="charlie@example.com",
        programming_languages=["Python", "SQL"],
        technical_skills=["Django", "PostgreSQL", "Redis"],
        projects=[
            ProjectInfo(
                name="Inventory Management System",
                description="Built an inventory tracking REST API using Django and PostgreSQL.",
                technologies=["Python", "Django", "PostgreSQL"],
                implementation_details="Database migrations, relational queries, and CRUD endpoints.",
                supporting_evidence="Developed inventory backend services in Python.",
            )
        ],
    )
    result = evaluate_candidate_eligibility(profile)
    assert result.eligible is False
    assert not any("Python" in r for r in result.rejection_reasons)
    assert any("AI" in r or "LLM" in r or "RAG" in r for r in result.rejection_reasons)


# -----------------------------------------------------------------------------
# 4. AI-project candidate WITHOUT credible Python evidence is REJECTED
# -----------------------------------------------------------------------------
def test_ai_without_python_rejected():
    profile = CandidateProfile(
        candidate_name="David JS AI Dev",
        email="david@example.com",
        programming_languages=["JavaScript", "TypeScript"],
        technical_skills=["Node.js", "Express"],
        frameworks_and_tools=["LangChain.js", "OpenAI API"],
        projects=[
            ProjectInfo(
                name="Chat Assistant in Node",
                description="Implemented a conversational agent using LangChain.js and OpenAI in Node.js.",
                technologies=["JavaScript", "Node.js", "LangChain", "OpenAI"],
                implementation_details="Used LangChain JS SDK with Express backend.",
                supporting_evidence="Developed chatbot service in TypeScript and LangChain.js.",
            )
        ],
    )
    result = evaluate_candidate_eligibility(profile)
    assert result.eligible is False
    assert any("Python" in r for r in result.rejection_reasons)
    assert not any("AI" in r for r in result.rejection_reasons)


# -----------------------------------------------------------------------------
# 5. Candidate missing BOTH requirements receives BOTH rejection reasons
# -----------------------------------------------------------------------------
def test_missing_both_requirements_receives_both_rejection_reasons():
    profile = CandidateProfile(
        candidate_name="Eve SysAdmin",
        email="eve@example.com",
        programming_languages=["Bash", "C"],
        technical_skills=["Linux", "Networking", "Docker"],
        projects=[],
    )
    result = evaluate_candidate_eligibility(profile)
    assert result.eligible is False
    assert len(result.rejection_reasons) == 2
    assert any("Python" in r for r in result.rejection_reasons)
    assert any("AI" in r or "LLM" in r or "RAG" in r for r in result.rejection_reasons)


# -----------------------------------------------------------------------------
# 6. Java/React candidate WITH qualifying Python and AI experience is ACCEPTED
# -----------------------------------------------------------------------------
def test_polyglot_java_react_with_python_and_ai_accepted():
    profile = CandidateProfile(
        candidate_name="Frank FullStack",
        email="frank@example.com",
        programming_languages=["Java", "JavaScript", "Python"],
        technical_skills=["Spring Boot", "React", "FastAPI"],
        frameworks_and_tools=["LangGraph", "LlamaIndex", "Docker"],
        projects=[
            ProjectInfo(
                name="Agentic Research Assistant",
                description="Built a multi-agent autonomous workflow with LangGraph and Python backend.",
                technologies=["Python", "LangGraph", "FastAPI", "React"],
                implementation_details="Tool-calling agent with memory and React UI.",
                supporting_evidence="Engineered multi-agent framework in Python using LangGraph.",
            )
        ],
    )
    result = evaluate_candidate_eligibility(profile)
    assert result.eligible is True
    assert len(result.rejection_reasons) == 0


# -----------------------------------------------------------------------------
# 7. Missing email/phone/GitHub does NOT disqualify a candidate
# -----------------------------------------------------------------------------
def test_missing_contact_and_github_does_not_disqualify():
    profile = CandidateProfile(
        candidate_name="Grace Minimalist",
        email=None,
        phone=None,
        github_url=None,
        education=[],
        programming_languages=["Python"],
        projects=[
            ProjectInfo(
                name="Vector RAG Search Engine",
                description="Implemented semantic retrieval with LangChain and vector embeddings in ChromaDB.",
                technologies=["Python", "LangChain", "Vector Search", "ChromaDB"],
                implementation_details="Custom embedding pipeline and semantic search.",
                supporting_evidence="Created RAG pipeline in Python.",
            )
        ],
    )
    result = evaluate_candidate_eligibility(profile)
    assert result.eligible is True
    assert len(result.rejection_reasons) == 0


# -----------------------------------------------------------------------------
# 8. Isolated keyword mention without project/implementation context
# -----------------------------------------------------------------------------
def test_isolated_keyword_in_skills_without_project_does_not_pass_ai():
    # If a resume only lists "AI" in a skill block without any project or context
    profile = CandidateProfile(
        candidate_name="Harry Keyword",
        email="harry@example.com",
        programming_languages=["Python"],
        technical_skills=["Python"],
        projects=[
            ProjectInfo(
                name="Simple Calculator",
                description="Built a basic command-line arithmetic calculator in Python.",
                technologies=["Python"],
            )
        ],
    )
    # Resume text has no AI projects, only an isolated word like "interested in AI"
    result = evaluate_candidate_eligibility(profile, raw_text="Experienced with Python. Interested in AI.")
    assert result.eligible is False
    assert any("AI" in r or "LLM" in r or "RAG" in r for r in result.rejection_reasons)


# -----------------------------------------------------------------------------
# 9. Malformed LLM response is handled safely
# -----------------------------------------------------------------------------
def test_malformed_llm_response_handled_gracefully():
    mock_adapter = MagicMock(spec=LLMAdapter)
    mock_adapter.is_configured.return_value = True
    # LLM returns invalid data type
    mock_adapter.extract_candidate_data.return_value = "Not a valid dictionary"

    text = "John Doe\njohn@example.com\nPython, FastAPI, LangChain RAG pipeline"
    profile = extract_candidate_profile(text, adapter=mock_adapter)
    assert profile.candidate_name is not None
    assert "Python" in profile.programming_languages


# -----------------------------------------------------------------------------
# 10. LLM timeout or failure does not abort batch
# -----------------------------------------------------------------------------
def test_llm_timeout_does_not_abort_batch():
    mock_adapter = MagicMock(spec=LLMAdapter)
    mock_adapter.is_configured.return_value = True
    mock_adapter.extract_candidate_data.side_effect = TimeoutError("LLM Gateway Timed Out")

    text = "Jane Doe\njane@example.com\nPython, LangChain, RAG with Vector Search"
    profile = extract_candidate_profile(text, adapter=mock_adapter)
    # Fallback still successfully extracts candidate
    assert profile.candidate_name is not None
    assert "Python" in profile.programming_languages
    assert any("Langchain" in t or "LangChain" in t for t in profile.frameworks_and_tools)


# -----------------------------------------------------------------------------
# 11 & 12. Batch API consistency & Mixed Batch Processing
# -----------------------------------------------------------------------------
def test_batch_api_eligibility_and_counts_consistency():
    valid_eligible_text = """
    Sarah Connor
    sarah@example.com | https://github.com/sarahconnor
    Skills: Python, FastAPI, Docker
    Projects:
    Autonomous RAG Agent
    Built an agentic search pipeline with LangChain and vector search in ChromaDB using Python.
    """
    valid_ineligible_text = """
    Tom WebDev
    tom@example.com
    Skills: React, JavaScript, HTML, CSS
    Projects:
    Web Portfolio
    Personal portfolio website using React and CSS.
    """
    pdf_eligible = make_pdf_bytes(valid_eligible_text)
    pdf_ineligible = make_pdf_bytes(valid_ineligible_text)
    corrupted_pdf = b"NOT_A_PDF_CONTENT"

    response = client.post(
        "/screen",
        files=[
            ("files", ("candidate_eligible.pdf", pdf_eligible, "application/pdf")),
            ("files", ("candidate_ineligible.pdf", pdf_ineligible, "application/pdf")),
            ("files", ("corrupt.pdf", corrupted_pdf, "application/pdf")),
        ],
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 3
    assert data["successful_files"] == 2
    assert data["failed_files"] == 1
    assert data["eligible_candidates"] == 1
    assert data["ineligible_candidates"] == 1

    # Check candidate details
    res_map = {r["filename"]: r for r in data["results"]}

    # Eligible file
    assert res_map["candidate_eligible.pdf"]["status"] == ExtractionStatus.SUCCESS.value
    assert res_map["candidate_eligible.pdf"]["eligible"] is True
    assert len(res_map["candidate_eligible.pdf"]["rejection_reasons"]) == 0
    assert len(res_map["candidate_eligible.pdf"]["python_evidence"]) > 0
    assert len(res_map["candidate_eligible.pdf"]["ai_evidence"]) > 0

    # Ineligible file
    assert res_map["candidate_ineligible.pdf"]["status"] == ExtractionStatus.SUCCESS.value
    assert res_map["candidate_ineligible.pdf"]["eligible"] is False
    assert len(res_map["candidate_ineligible.pdf"]["rejection_reasons"]) >= 1

    # Corrupt file
    assert res_map["corrupt.pdf"]["status"] == ExtractionStatus.FAILED.value
    assert res_map["corrupt.pdf"]["eligible"] is None
