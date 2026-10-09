"""
Candidate information extraction module.
Provides a hybrid extraction pipeline combining deterministic regex/heuristics
with semantic LLM extraction and graceful fallback handling.
"""

import re
import logging
from typing import List, Optional, Tuple

from backend.llm_adapter import LLMAdapter, llm_adapter
from backend.schemas import CandidateProfile, ProjectInfo, WorkExperience

logger = logging.getLogger(__name__)

# Regular expressions for contact and profiles
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", re.IGNORECASE)
PHONE_REGEX = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
GITHUB_REGEX = re.compile(r"https?://(?:www\.)?github\.com/[a-zA-Z0-9_-]+", re.IGNORECASE)

# Known technical dictionaries for deterministic keyword recognition
KNOWN_LANGUAGES = {
    "python", "javascript", "typescript", "java", "c++", "c#", "c",
    "go", "golang", "rust", "ruby", "php", "swift", "kotlin", "scala", "sql", "r", "html", "css"
}

KNOWN_AI_TERMS = {
    "langchain", "langgraph", "llamaindex", "google adk", "rag",
    "retrieval augmented generation", "agent", "agents", "agentic",
    "vector search", "embeddings", "openai", "gemini", "anthropic",
    "claude", "hugging face", "huggingface", "transformers", "pytorch",
    "tensorflow", "scikit-learn", "sklearn", "chromadb", "pinecone",
    "faiss", "weaviate", "qdrant", "fine-tuning", "llm", "llms",
    "machine learning", "deep learning", "nlp"
}

KNOWN_BACKEND_TOOLS = {
    "fastapi", "flask", "django", "express", "node.js", "nodejs",
    "docker", "kubernetes", "aws", "gcp", "azure", "postgresql",
    "postgres", "mysql", "mongodb", "redis", "graphql", "rest api", "git"
}


def extract_candidate_name_heuristic(lines: List[str]) -> Optional[str]:
    """
    Heuristically extract candidate name from the top non-empty lines of resume.
    Avoids common document headings.
    """
    ignore_words = {
        "resume", "curriculum", "vitae", "cv", "page", "contact",
        "email", "phone", "experience", "education", "skills", "projects"
    }

    for line in lines[:8]:
        cleaned = line.strip()
        if not cleaned:
            continue
        # If line is short and contains mostly alphabet characters
        words = cleaned.split()
        if 2 <= len(words) <= 4:
            lower_words = [w.lower().strip(":,|•-") for w in words]
            if not any(w in ignore_words for w in lower_words):
                if all(w.isalpha() or "." in w for w in words):
                    return cleaned
    return None


def extract_deterministic_contact_info(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract email, phone, and GitHub URL using regular expressions."""
    # Email
    email_match = EMAIL_REGEX.search(text)
    email = email_match.group(0) if email_match else None

    # Phone
    phone_match = PHONE_REGEX.search(text)
    phone = phone_match.group(0) if phone_match else None

    # GitHub
    github_match = GITHUB_REGEX.search(text)
    github_url = github_match.group(0) if github_match else None
    if not github_url:
        # Check for plain 'github.com/username'
        short_gh = re.search(r"\bgithub\.com/([a-zA-Z0-9_-]+)", text, re.IGNORECASE)
        if short_gh:
            github_url = f"https://github.com/{short_gh.group(1)}"

    return email, phone, github_url


def deterministic_extract_candidate(resume_text: str, filename: str = "") -> CandidateProfile:
    """
    Rule-based deterministic extraction engine when LLM is unavailable or unconfigured.
    Identifies contact details, languages, skills, and section blocks.
    """
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    name = extract_candidate_name_heuristic(lines)
    email, phone, github_url = extract_deterministic_contact_info(resume_text)

    # Detect skills and languages present in text
    lower_text = resume_text.lower()
    detected_languages = [
        lang.capitalize() for lang in KNOWN_LANGUAGES
        if re.search(rf"\b{re.escape(lang)}\b", lower_text)
    ]
    detected_skills = [
        skill.title() for skill in KNOWN_BACKEND_TOOLS
        if re.search(rf"\b{re.escape(skill)}\b", lower_text)
    ]
    detected_ai_tools = [
        ai.title() for ai in KNOWN_AI_TERMS
        if re.search(rf"\b{re.escape(ai)}\b", lower_text)
    ]

    # Heuristic project parsing from text
    projects: List[ProjectInfo] = []
    project_sections = re.findall(
        r"(?:project[s]?|technical projects)[\s\S]*?(?=(?:experience|education|skills|certifications|$))",
        resume_text,
        re.IGNORECASE,
    )

    if project_sections:
        proj_text = project_sections[0]
        # Split projects by bullet points or empty lines
        paragraphs = [p.strip() for p in proj_text.split("\n\n") if len(p.strip()) > 30]
        for idx, para in enumerate(paragraphs[:5], start=1):
            first_line = para.splitlines()[0]
            para_lower = para.lower()
            para_techs = [
                tech.title() for tech in (KNOWN_LANGUAGES | KNOWN_AI_TERMS | KNOWN_BACKEND_TOOLS)
                if re.search(rf"\b{re.escape(tech)}\b", para_lower)
            ]
            projects.append(
                ProjectInfo(
                    name=first_line[:80],
                    description=para[:300],
                    technologies=para_techs,
                    implementation_details=para[:400],
                    supporting_evidence=para[:300],
                )
            )

    # Detect education lines heuristically
    education: List[str] = []
    edu_matches = re.findall(
        r"(?:(?:bachelor|master|b\.?tech|m\.?tech|b\.?s\.|m\.?s\.|b\.?e\.|m\.?e\.|ph\.?d|bca|mca)[^\n,;]+(?:university|institute|college|school|technology|\d{4})?[^\n]*)",
        resume_text,
        re.IGNORECASE,
    )
    if edu_matches:
        for match in edu_matches[:3]:
            cleaned_edu = match.strip()
            if len(cleaned_edu) >= 5 and cleaned_edu not in education:
                education.append(cleaned_edu[:120])

    return CandidateProfile(
        candidate_name=name or "Candidate",
        email=email,
        phone=phone,
        education=education,
        programming_languages=detected_languages,
        technical_skills=detected_skills,
        frameworks_and_tools=detected_ai_tools,
        projects=projects,
        work_experience=[],
        github_url=github_url,
        extraction_warnings=["Extracted using deterministic rule-based parser (LLM unconfigured or fallback)."],
    )


def extract_candidate_profile(
    resume_text: str,
    filename: str = "",
    adapter: Optional[LLMAdapter] = None,
) -> CandidateProfile:
    """
    Extract structured candidate profile from resume text.
    Combines LLM semantic parsing with deterministic verification and fallback.
    """
    if not resume_text or not resume_text.strip():
        return CandidateProfile(
            candidate_name="Unknown",
            extraction_warnings=["Document contains no text for candidate extraction."],
        )

    llm = adapter or llm_adapter
    det_email, det_phone, det_github = extract_deterministic_contact_info(resume_text)

    # 1. Attempt LLM extraction if configured
    if llm.is_configured():
        try:
            llm_data = llm.extract_candidate_data(resume_text)
            if llm_data and isinstance(llm_data, dict):
                # Construct projects list safely
                raw_projects = llm_data.get("projects", [])
                parsed_projects: List[ProjectInfo] = []
                if isinstance(raw_projects, list):
                    for p in raw_projects:
                        if isinstance(p, dict) and p.get("name"):
                            parsed_projects.append(
                                ProjectInfo(
                                    name=str(p.get("name")),
                                    description=p.get("description"),
                                    technologies=p.get("technologies") or [],
                                    implementation_details=p.get("implementation_details"),
                                    supporting_evidence=p.get("supporting_evidence"),
                                )
                            )

                # Construct work experience list safely
                raw_exp = llm_data.get("work_experience", [])
                parsed_exp: List[WorkExperience] = []
                if isinstance(raw_exp, list):
                    for w in raw_exp:
                        if isinstance(w, dict):
                            parsed_exp.append(
                                WorkExperience(
                                    role=w.get("role"),
                                    organization=w.get("organization"),
                                    technologies=w.get("technologies") or [],
                                    responsibilities=w.get("responsibilities"),
                                    evidence=w.get("evidence"),
                                )
                            )

                # Prefer deterministic regex for contact info if LLM missed it
                final_email = llm_data.get("email") or det_email
                final_phone = llm_data.get("phone") or det_phone
                final_github = llm_data.get("github_url") or det_github

                return CandidateProfile(
                    candidate_name=llm_data.get("candidate_name") or extract_candidate_name_heuristic(resume_text.splitlines()),
                    email=final_email,
                    phone=final_phone,
                    education=llm_data.get("education") or [],
                    programming_languages=llm_data.get("programming_languages") or [],
                    technical_skills=llm_data.get("technical_skills") or [],
                    frameworks_and_tools=llm_data.get("frameworks_and_tools") or [],
                    projects=parsed_projects,
                    work_experience=parsed_exp,
                    github_url=final_github,
                    extraction_warnings=[],
                )
        except Exception as exc:
            logger.warning("LLM extraction encountered an error: %s. Using deterministic fallback.", str(exc))

    # 2. Fallback to deterministic extraction
    return deterministic_extract_candidate(resume_text, filename=filename)
