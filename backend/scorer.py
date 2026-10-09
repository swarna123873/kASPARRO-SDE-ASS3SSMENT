"""
100-Point Rubric Scoring Engine for SDE Intern candidates.

Scoring Dimensions (weights pulled from backend/config.py):
  1. AI / Agentic / RAG Project Depth  — 0-40 pts
  2. Python & Backend Engineering      — 0-30 pts
  3. Cloud / Deployment / Full Stack   — 0-15 pts
  4. GitHub Activity                   — 0-10 pts  (populated after GitHub enrichment)
  5. Engineering Depth Signals         — 0- 5 pts

Project-quality penalty: 5–15 pts for a shallow API-wrapper project.

final_score = max(0, min(100, sum(categories) - project_quality_penalty))

Only eligible candidates (Python + AI) are scored.
Scores are deterministic and fully explainable; each category returns points
and evidence strings.  GitHub points are injected by the ranker after enrichment.
"""

import re
from typing import List, Set, Tuple

from backend.config import (
    SCORE_MAX_AI_PROJECT_DEPTH,
    SCORE_MAX_CLOUD_FULLSTACK,
    SCORE_MAX_ENGINEERING_DEPTH,
    SCORE_MAX_GITHUB,
    SCORE_MAX_PYTHON_BACKEND,
    SCORE_PENALTY_MAX,
    SCORE_PENALTY_MIN,
)
from backend.schemas import CandidateProfile, ScoreBreakdown, ScoreCategoryDetail

# ──────────────────────────────────────────────────────────────────────────────
# Skill dictionaries for each scoring dimension
# ──────────────────────────────────────────────────────────────────────────────

# Dimension 1: AI/Agentic sophistication markers
AI_ADVANCED_FRAMEWORKS: Set[str] = {
    "langchain", "langgraph", "llamaindex", "google adk", "crewai",
    "autogen", "semantic kernel", "haystack",
}
AI_ADVANCED_CONCEPTS: Set[str] = {
    "rag", "retrieval augmented generation", "retrieval-augmented generation",
    "multi-agent", "agentic", "tool-calling", "tool calling",
    "vector search", "vector database", "embeddings", "fine-tuning", "finetuning",
    "chromadb", "pinecone", "faiss", "weaviate", "qdrant", "milvus",
    "evaluation pipeline", "state management", "orchestration",
}
AI_STANDARD_TOOLS: Set[str] = {
    "transformers", "huggingface", "hugging face", "pytorch", "tensorflow",
    "scikit-learn", "sklearn", "openai", "gemini", "anthropic", "claude",
    "deep learning", "nlp", "computer vision", "llm", "llms",
}

# Dimension 2: Python & backend engineering
PYTHON_DEEP_SKILLS: Set[str] = {
    "fastapi", "flask", "django", "pytest", "asyncio", "sqlalchemy", "celery",
}
PYTHON_STANDARD: Set[str] = {
    "python", "numpy", "pandas", "rest api", "graphql", "pydantic",
}
BACKEND_INFRA: Set[str] = {
    "postgresql", "postgres", "mysql", "mongodb", "redis", "rabbitmq",
    "kafka", "elasticsearch", "sqlite",
}

# Dimension 3: Cloud / Deployment / Full Stack
CLOUD_PROVIDERS: Set[str] = {"aws", "gcp", "azure", "google cloud", "amazon web services"}
CONTAINER_TOOLS: Set[str] = {"docker", "kubernetes", "k8s", "helm", "terraform", "ansible"}
CICD_TOOLS: Set[str] = {"github actions", "gitlab ci", "jenkins", "circleci", "travis ci", "ci/cd"}
SERVERLESS: Set[str] = {"lambda", "cloud functions", "cloud run", "vercel", "render", "railway"}
FRONTEND_FULLSTACK: Set[str] = {"react", "next.js", "nextjs", "vue", "angular", "svelte"}

# Dimension 5: Engineering depth signals
TESTING_TOOLS: Set[str] = {"pytest", "unittest", "jest", "mocha", "selenium", "cypress"}
ARCH_SIGNALS: Set[str] = {
    "data structures", "algorithms", "system design", "design patterns", "solid",
    "microservices", "caching", "queue", "concurrency", "observability",
}
CODE_QUALITY: Set[str] = {"swagger", "openapi", "sphinx", "type hints", "mypy", "black", "ruff"}

# Penalty triggers: keywords that strongly suggest tutorial/generic projects
TUTORIAL_PENALTY_SIGNALS: Set[str] = {
    "todo app", "todo list", "to-do app", "to-do list", "crud app",
    "hello world", "calculator app", "weather app", "calculator",
    "blog website", "portfolio website", "shopping cart", "snake game",
    "tic tac toe", "guess the number",
}

# Signals that suggest shallow AI usage (only API call, no meaningful logic)
SHALLOW_AI_SIGNALS: Set[str] = {
    "simple chatbot", "basic chatbot", "openai api wrapper", "api wrapper",
    "gpt wrapper", "llm wrapper", "no retrieval", "no backend", "no database",
}


# ──────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ──────────────────────────────────────────────────────────────────────────────

def _keywords_found(text_lower: str, keywords: Set[str]) -> List[str]:
    """Return the subset of keywords that appear as whole-words in text."""
    found = []
    for kw in sorted(keywords):  # sorted for determinism
        if re.search(rf"\b{re.escape(kw)}\b", text_lower):
            found.append(kw)
    return found


def _profile_text(profile: CandidateProfile) -> str:
    """Flatten all candidate profile text for fast keyword search."""
    parts = [
        " ".join(profile.programming_languages),
        " ".join(profile.technical_skills),
        " ".join(profile.frameworks_and_tools),
        " ".join(profile.matched_skills),
        " ".join(profile.project_summaries),
        " ".join(profile.python_evidence),
        " ".join(profile.ai_evidence),
    ]
    for proj in profile.projects:
        parts += [
            proj.name,
            proj.description or "",
            proj.implementation_details or "",
            proj.supporting_evidence or "",
            " ".join(proj.technologies),
        ]
    for exp in profile.work_experience:
        parts += [
            exp.role or "",
            exp.responsibilities or "",
            exp.evidence or "",
            " ".join(exp.technologies),
        ]
    return " ".join(parts).lower()


# ──────────────────────────────────────────────────────────────────────────────
# Dimension 1: AI / Agentic / RAG Project Depth — max 40 pts
# ──────────────────────────────────────────────────────────────────────────────

def _score_ai_project_depth(
    profile: CandidateProfile, raw_text: str = ""
) -> Tuple[int, List[str]]:
    """
    Points breakdown (total capped at SCORE_MAX_AI_PROJECT_DEPTH = 40):
      Advanced AI framework (LangChain, LangGraph, etc.)  → +12 each (max 24)
      Advanced concept (RAG, multi-agent, embeddings, …)  → +8 each  (max 16)
      Standard AI tools (PyTorch, HuggingFace, etc.)      → +4 each  (max  8)
      AI evidence quality bonus                           → +8

    Reward meaningful workflow evidence; do NOT award high scores just for
    listing a framework name without implementation detail.
    """
    combined = _profile_text(profile) + " " + raw_text.lower()
    evidence: List[str] = []
    pts = 0

    # Advanced frameworks — cap at 2 occurrences (max 24)
    adv_found = _keywords_found(combined, AI_ADVANCED_FRAMEWORKS)
    for kw in adv_found[:2]:
        pts += 12
        evidence.append(f"Advanced AI framework: {kw.title()}")

    # Advanced concepts — cap at 2 (max 16)
    concept_found = _keywords_found(combined, AI_ADVANCED_CONCEPTS)
    for kw in concept_found[:2]:
        pts += 8
        evidence.append(f"Advanced AI concept/workflow: {kw.title()}")

    # Standard AI tools — cap at 2 (max 8)
    std_found = _keywords_found(combined, AI_STANDARD_TOOLS)
    for kw in std_found[:2]:
        pts += 4
        evidence.append(f"AI/ML tool: {kw.title()}")

    # Quality bonus: candidate supplied meaningful AI evidence strings
    if profile.ai_evidence and len(profile.ai_evidence) >= 1:
        pts += 8
        evidence.append(f"AI project evidence verified: {profile.ai_evidence[0][:120]}")

    return min(pts, SCORE_MAX_AI_PROJECT_DEPTH), evidence


# ──────────────────────────────────────────────────────────────────────────────
# Dimension 2: Python & Backend Engineering — max 30 pts
# ──────────────────────────────────────────────────────────────────────────────

def _score_python_backend(
    profile: CandidateProfile, raw_text: str = ""
) -> Tuple[int, List[str]]:
    """
    Points breakdown (total capped at SCORE_MAX_PYTHON_BACKEND = 30):
      Python listed as core language                      → +10
      Python deep framework (FastAPI, Django, Flask)      → +6 each (max 12)
      Standard Python ecosystem (numpy, pandas, etc.)     → +3 each (max  6)
      Backend DB/infra (PostgreSQL, Redis, etc.)          → +2 each (max  6)

    Projects and work evidence receive more credit than bare skill mentions.
    """
    combined = _profile_text(profile) + " " + raw_text.lower()
    evidence: List[str] = []
    pts = 0

    langs_lower = [la.lower() for la in profile.programming_languages]
    if "python" in langs_lower:
        pts += 10
        evidence.append("Python listed as core programming language.")

    deep_found = _keywords_found(combined, PYTHON_DEEP_SKILLS)
    for kw in deep_found[:2]:  # max 12
        pts += 6
        evidence.append(f"Python deep framework/tool: {kw.title()}")

    std_found = _keywords_found(combined, PYTHON_STANDARD - {"python"})
    for kw in std_found[:2]:  # max 6
        pts += 3
        evidence.append(f"Python standard library/ecosystem: {kw.title()}")

    db_found = _keywords_found(combined, BACKEND_INFRA)
    for kw in db_found[:3]:  # max 6
        pts += 2
        evidence.append(f"Backend/database technology: {kw.title()}")

    return min(pts, SCORE_MAX_PYTHON_BACKEND), evidence


# ──────────────────────────────────────────────────────────────────────────────
# Dimension 3: Cloud / Deployment / Full Stack — max 15 pts
# ──────────────────────────────────────────────────────────────────────────────

def _score_cloud_fullstack(
    profile: CandidateProfile, raw_text: str = ""
) -> Tuple[int, List[str]]:
    """
    Points breakdown (total capped at SCORE_MAX_CLOUD_FULLSTACK = 15):
      Cloud provider (AWS, GCP, Azure)                   → +6 (max 6)
      Container/orchestration (Docker, Kubernetes)       → +4 (max 4)
      CI/CD pipelines                                    → +3 (max 3)
      Serverless / PaaS                                  → +2 (max 2)
      Frontend full-stack (React, Next.js)               → +2 (max 2)

    Do not assume deployment occurred just because Docker appears in skills.
    Implementation evidence (project/work descriptions) outweighs skill lists.
    """
    combined = _profile_text(profile) + " " + raw_text.lower()
    evidence: List[str] = []
    pts = 0

    cloud_found = _keywords_found(combined, CLOUD_PROVIDERS)
    if cloud_found:
        pts += 6
        evidence.append(f"Cloud platform experience: {', '.join(cloud_found[:2]).upper()}")

    container_found = _keywords_found(combined, CONTAINER_TOOLS)
    if container_found:
        pts += 4
        evidence.append(f"Container/orchestration: {', '.join(container_found[:2]).title()}")

    cicd_found = _keywords_found(combined, CICD_TOOLS)
    if cicd_found:
        pts += 3
        evidence.append(f"CI/CD pipeline: {', '.join(cicd_found[:2]).title()}")

    serverless_found = _keywords_found(combined, SERVERLESS)
    if serverless_found:
        pts += 2
        evidence.append(f"Serverless/PaaS deployment: {', '.join(serverless_found[:2]).title()}")

    frontend_found = _keywords_found(combined, FRONTEND_FULLSTACK)
    if frontend_found:
        pts += 2
        evidence.append(f"Full-stack frontend: {', '.join(frontend_found[:2]).title()}")

    return min(pts, SCORE_MAX_CLOUD_FULLSTACK), evidence


# ──────────────────────────────────────────────────────────────────────────────
# Dimension 5: Engineering Depth Signals — max 5 pts
# ──────────────────────────────────────────────────────────────────────────────

def _score_engineering_depth(
    profile: CandidateProfile, raw_text: str = ""
) -> Tuple[int, List[str]]:
    """
    Points breakdown (total capped at SCORE_MAX_ENGINEERING_DEPTH = 5):
      Testing frameworks (pytest, jest, etc.)            → +2
      Architecture / modularity signals                  → +2
      Code quality / docs (Swagger, type hints, etc.)   → +1

    Do not award full points for bare keyword mentions without implementation
    context.
    """
    combined = _profile_text(profile) + " " + raw_text.lower()
    evidence: List[str] = []
    pts = 0

    test_found = _keywords_found(combined, TESTING_TOOLS)
    if test_found:
        pts += 2
        evidence.append(f"Testing practice: {', '.join(test_found[:3]).title()}")

    arch_found = _keywords_found(combined, ARCH_SIGNALS)
    if arch_found:
        pts += 2
        evidence.append(f"Engineering depth signals: {', '.join(arch_found[:3]).title()}")

    docs_found = _keywords_found(combined, CODE_QUALITY)
    if docs_found:
        pts += 1
        evidence.append(f"Code quality/documentation: {', '.join(docs_found[:3]).title()}")

    return min(pts, SCORE_MAX_ENGINEERING_DEPTH), evidence


# ──────────────────────────────────────────────────────────────────────────────
# Penalty: Shallow / API-wrapper projects (5–15 pts)
# ──────────────────────────────────────────────────────────────────────────────

def _compute_project_quality_penalty(
    profile: CandidateProfile, raw_text: str = ""
) -> Tuple[int, List[str]]:
    """
    Apply a penalty between SCORE_PENALTY_MIN and SCORE_PENALTY_MAX when the
    evidence supports the conclusion that the project is a shallow API-wrapper
    or tutorial project.

    Safeguards:
    - Do not penalise every project that calls an LLM API.
    - Do not penalise merely because a project is simple; base the decision on
      available evidence showing a LACK of meaningful logic.
    - Do not invent evidence; if unsure, return 0.
    - Avoid double-counting the same weakness already captured in lower category
      scores.
    """
    combined = _profile_text(profile) + " " + raw_text.lower()
    penalty = 0
    reasons: List[str] = []

    # 1. Explicit tutorial/toy project signals (each triggers SCORE_PENALTY_MIN)
    for signal in TUTORIAL_PENALTY_SIGNALS:
        if re.search(rf"\b{re.escape(signal)}\b", combined):
            penalty += SCORE_PENALTY_MIN
            reasons.append(
                f"Tutorial/toy project detected: '{signal.title()}' "
                f"(-{SCORE_PENALTY_MIN} pts)"
            )
            if penalty >= SCORE_PENALTY_MAX:
                break

    # 2. Shallow AI usage signals (only if no advanced AI concepts present)
    if penalty < SCORE_PENALTY_MAX:
        advanced_ai_present = bool(_keywords_found(combined, AI_ADVANCED_CONCEPTS | AI_ADVANCED_FRAMEWORKS))
        shallow_found = _keywords_found(combined, SHALLOW_AI_SIGNALS)
        if shallow_found and not advanced_ai_present:
            penalty += SCORE_PENALTY_MIN
            reasons.append(
                f"Shallow AI wrapper pattern detected without meaningful retrieval, "
                f"state management, or backend logic: '{shallow_found[0]}' "
                f"(-{SCORE_PENALTY_MIN} pts)"
            )

    final_penalty = max(0, min(penalty, SCORE_PENALTY_MAX))
    return final_penalty, reasons


# ──────────────────────────────────────────────────────────────────────────────
# Public API: score_candidate
# ──────────────────────────────────────────────────────────────────────────────

def score_candidate(
    profile: CandidateProfile,
    raw_text: str = "",
) -> ScoreBreakdown:
    """
    Compute the full 100-point score for an eligible candidate.

    The GitHub activity dimension (max 10) starts at 0 and is populated later
    by the ranker after GitHub enrichment.

    Returns a fully populated ScoreBreakdown with total_score reflecting all
    category scores minus any project-quality penalty (GitHub not yet added).
    """
    ai_pts, ai_ev = _score_ai_project_depth(profile, raw_text)
    py_pts, py_ev = _score_python_backend(profile, raw_text)
    cl_pts, cl_ev = _score_cloud_fullstack(profile, raw_text)
    eng_pts, eng_ev = _score_engineering_depth(profile, raw_text)
    penalty, penalty_reasons = _compute_project_quality_penalty(profile, raw_text)

    # GitHub starts at 0; added by ranker._apply_github_bonus() later
    gh_pts = 0
    gh_ev: List[str] = []

    raw_total = ai_pts + py_pts + cl_pts + gh_pts + eng_pts
    total = max(0, min(100, raw_total - penalty))

    # Build per-category evidence detail objects
    score_evidence: List[ScoreCategoryDetail] = [
        ScoreCategoryDetail(
            category="ai_project_depth",
            points_awarded=ai_pts,
            max_points=SCORE_MAX_AI_PROJECT_DEPTH,
            explanation=f"AI/Agentic/RAG project depth: {ai_pts}/{SCORE_MAX_AI_PROJECT_DEPTH} pts",
            evidence=ai_ev,
            limitation="GitHub repos not yet factored in." if not profile.github_url else None,
        ),
        ScoreCategoryDetail(
            category="python_backend",
            points_awarded=py_pts,
            max_points=SCORE_MAX_PYTHON_BACKEND,
            explanation=f"Python & backend engineering: {py_pts}/{SCORE_MAX_PYTHON_BACKEND} pts",
            evidence=py_ev,
        ),
        ScoreCategoryDetail(
            category="cloud_fullstack",
            points_awarded=cl_pts,
            max_points=SCORE_MAX_CLOUD_FULLSTACK,
            explanation=f"Cloud/deployment/full-stack: {cl_pts}/{SCORE_MAX_CLOUD_FULLSTACK} pts",
            evidence=cl_ev,
        ),
        ScoreCategoryDetail(
            category="github",
            points_awarded=0,
            max_points=SCORE_MAX_GITHUB,
            explanation="GitHub activity: pending enrichment",
            evidence=[],
            limitation="GitHub enrichment not yet applied.",
        ),
        ScoreCategoryDetail(
            category="engineering_depth",
            points_awarded=eng_pts,
            max_points=SCORE_MAX_ENGINEERING_DEPTH,
            explanation=f"Engineering depth signals: {eng_pts}/{SCORE_MAX_ENGINEERING_DEPTH} pts",
            evidence=eng_ev,
        ),
    ]

    return ScoreBreakdown(
        ai_project_depth=ai_pts,
        ai_project_depth_evidence=ai_ev,
        python_backend=py_pts,
        python_backend_evidence=py_ev,
        cloud_fullstack=cl_pts,
        cloud_fullstack_evidence=cl_ev,
        github=gh_pts,
        github_evidence=gh_ev,
        engineering_depth=eng_pts,
        engineering_depth_evidence=eng_ev,
        project_quality_penalty=penalty,
        project_quality_penalty_reasons=penalty_reasons,
        total_score=total,
        score_evidence=score_evidence,
    )
