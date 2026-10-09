"""
Deterministic eligibility rules engine for SDE Intern screening.
Evaluates mandatory prerequisites:
1. Python Evidence: Python as a genuine skill, project technology, or work technology.
2. AI/Agentic Project Evidence: Meaningful implementation of AI, LLM, RAG, or agentic systems.

Decisions are strictly deterministic, transparent, and explainable with evidence citations.
"""

import re
from typing import List, Set, Tuple
from backend.schemas import CandidateProfile, EligibilityResult, ProjectInfo, WorkExperience

# Technical dictionaries for skill matching and evidence detection
AI_CORE_FRAMEWORKS = {
    "langchain", "langgraph", "llamaindex", "google adk", "crewai",
    "autogen", "haystack", "semantic kernel", "transformers", "huggingface",
    "hugging face", "pytorch", "tensorflow", "scikit-learn", "sklearn"
}

AI_CONCEPTS_AND_TOOLS = {
    "rag", "retrieval augmented generation", "retrieval-augmented generation",
    "agent", "agents", "agentic", "tool-calling", "tool calling", "multi-agent",
    "vector search", "embeddings", "embedding", "semantic search",
    "chromadb", "pinecone", "faiss", "weaviate", "qdrant", "milvus",
    "fine-tuning", "finetuning", "prompt engineering", "openai", "gemini",
    "anthropic", "claude", "llm", "llms", "large language model",
    "large language models", "deep learning", "nlp", "computer vision"
}

PYTHON_KEYWORDS = {"python", "fastapi", "flask", "django", "pytest", "numpy", "pandas"}


def _extract_text_citations(text: str, keywords: Set[str], max_citations: int = 3) -> List[str]:
    """Extract clean sentences or lines from text that match target keywords."""
    if not text:
        return []

    citations = []
    # Split text by sentence or line
    sentences = re.split(r"[.\n;•]+", text)
    for sent in sentences:
        cleaned = sent.strip()
        if len(cleaned) < 15 or len(cleaned) > 250:
            continue
        cleaned_lower = cleaned.lower()
        if any(re.search(rf"\b{re.escape(kw)}\b", cleaned_lower) for kw in keywords):
            if cleaned not in citations:
                citations.append(cleaned)
                if len(citations) >= max_citations:
                    break
    return citations


def evaluate_python_evidence(
    profile: CandidateProfile,
    raw_text: str = "",
) -> Tuple[bool, List[str]]:
    """
    Verify credible Python evidence across programming languages, skills,
    projects, work experience, and resume text.
    """
    evidence: List[str] = []

    # 1. Check programming languages list
    languages_lower = [lang.lower() for lang in profile.programming_languages]
    if "python" in languages_lower:
        evidence.append("Python identified in candidate's core programming languages.")

    # 2. Check projects for Python usage
    for proj in profile.projects:
        proj_techs_lower = [t.lower() for t in proj.technologies]
        proj_details = (proj.implementation_details or "") + " " + (proj.description or "")
        if "python" in proj_techs_lower or re.search(r"\bpython\b", proj_details, re.IGNORECASE):
            citation = proj.supporting_evidence or proj.description or proj.name
            evidence.append(f"Python utilized in project '{proj.name}': {citation[:160]}")

    # 3. Check work experience for Python usage
    for exp in profile.work_experience:
        exp_techs_lower = [t.lower() for t in exp.technologies]
        exp_resp = (exp.responsibilities or "") + " " + (exp.evidence or "")
        if "python" in exp_techs_lower or re.search(r"\bpython\b", exp_resp, re.IGNORECASE):
            evidence.append(f"Python applied in experience at '{exp.organization or exp.role or 'organization'}'.")

    # 4. Fallback search in raw text if structured fields are sparse
    if not evidence and raw_text:
        text_citations = _extract_text_citations(raw_text, {"python"})
        for cit in text_citations:
            evidence.append(f"Python referenced in resume: \"{cit}\"")

    has_python = len(evidence) > 0
    if not has_python:
        evidence = ["No verifiable Python programming experience, projects, or skill citations found in resume."]

    return has_python, evidence


def evaluate_ai_evidence(
    profile: CandidateProfile,
    raw_text: str = "",
) -> Tuple[bool, List[str]]:
    """
    Verify meaningful AI/LLM/RAG/agentic project, framework, or implementation evidence.
    Distinguishes actual implementation/projects from isolated, unsupported keywords.
    """
    evidence: List[str] = []
    all_ai_keywords = AI_CORE_FRAMEWORKS | AI_CONCEPTS_AND_TOOLS

    # 1. Inspect structured projects for AI technologies or workflows
    for proj in profile.projects:
        proj_techs_lower = [t.lower() for t in proj.technologies]
        proj_text = f"{proj.name} {proj.description or ''} {proj.implementation_details or ''} {proj.supporting_evidence or ''}"
        proj_text_lower = proj_text.lower()

        matched_ai_techs = [
            kw.title() for kw in all_ai_keywords
            if any(kw == t for t in proj_techs_lower) or re.search(rf"\b{re.escape(kw)}\b", proj_text_lower)
        ]

        if matched_ai_techs:
            summary = proj.supporting_evidence or proj.description or proj.implementation_details or proj.name
            evidence.append(
                f"AI/Agentic project implementation '{proj.name}' utilizing ({', '.join(matched_ai_techs[:4])}): {summary[:180]}"
            )

    # 2. Inspect work/internship experience for AI implementation
    for exp in profile.work_experience:
        exp_techs_lower = [t.lower() for t in exp.technologies]
        exp_text = f"{exp.role or ''} {exp.organization or ''} {exp.responsibilities or ''} {exp.evidence or ''}".lower()

        matched_ai_exp = [
            kw.title() for kw in all_ai_keywords
            if any(kw == t for t in exp_techs_lower) or re.search(rf"\b{re.escape(kw)}\b", exp_text)
        ]

        if matched_ai_exp:
            evidence.append(
                f"AI engineering experience at '{exp.organization or exp.role or 'organization'}' with ({', '.join(matched_ai_exp[:4])})."
            )

    # 3. Check for meaningful AI implementation in raw resume text if projects were not separated
    if not evidence and raw_text:
        # Search for multi-word or strong workflow context
        ai_workflow_patterns = {
            "rag", "langchain", "langgraph", "llamaindex", "google adk",
            "vector search", "agentic", "tool-calling", "multi-agent",
            "embeddings", "chromadb", "pinecone", "faiss", "transformers", "pytorch"
        }
        text_citations = _extract_text_citations(raw_text, ai_workflow_patterns)
        for cit in text_citations:
            evidence.append(f"AI/LLM workflow evidence in resume: \"{cit}\"")

    has_ai = len(evidence) > 0
    if not has_ai:
        evidence = ["No verifiable evidence of AI, LLM, RAG, or agentic project implementations found in resume."]

    return has_ai, evidence


def collect_matched_skills(profile: CandidateProfile, raw_text: str = "") -> List[str]:
    """Collect verified technical and AI skills matching target role requirements."""
    matched = set()

    # Combine languages, technical skills, and frameworks
    all_candidate_skills = (
        profile.programming_languages + profile.technical_skills + profile.frameworks_and_tools
    )
    for p in profile.projects:
        all_candidate_skills.extend(p.technologies)

    target_domain_skills = (
        PYTHON_KEYWORDS | AI_CORE_FRAMEWORKS | AI_CONCEPTS_AND_TOOLS |
        {"docker", "kubernetes", "aws", "gcp", "azure", "postgresql", "sql", "redis", "git", "rest api"}
    )

    for skill in all_candidate_skills:
        skill_clean = skill.strip()
        if skill_clean.lower() in target_domain_skills and len(skill_clean) > 1:
            matched.add(skill_clean)

    # If raw text available, scan for standard skill names
    if raw_text:
        raw_lower = raw_text.lower()
        for target in target_domain_skills:
            if re.search(rf"\b{re.escape(target)}\b", raw_lower):
                matched.add(target.title() if len(target) > 3 else target.upper())

    return sorted(list(matched))


def evaluate_candidate_eligibility(
    profile: CandidateProfile,
    raw_text: str = "",
) -> EligibilityResult:
    """
    Apply mandatory hard eligibility rules:
    - Condition 1: Credible Python evidence
    - Condition 2: Meaningful AI / LLM / RAG / Agentic project evidence

    A candidate is eligible ONLY if BOTH conditions pass.
    Non-rejection safeguards:
    - Missing GitHub, phone, email, or education details NEVER cause rejection.
    - Other languages (Java, JS, etc.) do NOT cause rejection if Python + AI are satisfied.
    """
    has_python, python_evidence = evaluate_python_evidence(profile, raw_text)
    has_ai, ai_evidence = evaluate_ai_evidence(profile, raw_text)
    matched_skills = collect_matched_skills(profile, raw_text)

    rejection_reasons: List[str] = []

    if not has_python:
        rejection_reasons.append(
            "Missing verifiable Python programming competency or practical implementation evidence."
        )

    if not has_ai:
        rejection_reasons.append(
            "Missing verifiable evidence of a meaningful AI, LLM, RAG, or agentic project implementation."
        )

    is_eligible = has_python and has_ai

    return EligibilityResult(
        eligible=is_eligible,
        rejection_reasons=rejection_reasons,
        matched_skills=matched_skills,
        python_evidence=python_evidence,
        ai_evidence=ai_evidence,
    )
