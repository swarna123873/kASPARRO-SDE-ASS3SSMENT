# AI Resume Screening System

An automated, evidence-based candidate screening pipeline that processes batches of PDF resumes, extracts structured candidate profiles, applies deterministic eligibility rules, produces explainable 100-point scores, enriches GitHub profiles, ranks candidates, and generates a complete machine-readable report.

Designed for an **SDE Intern** role with mandatory Python + AI/Agentic project evidence requirements.

---

## 1. Project Objective & Architecture

The system provides an end-to-end screening pipeline:

1. **Batch PDF Processing** — Accepts up to 50 PDF resumes simultaneously; per-file errors never interrupt the batch.
2. **Duplicate Detection** — SHA-256 content hashing identifies byte-identical uploads; duplicates are quarantined, not ranked twice.
3. **Structured Candidate Extraction** — Hybrid parser (deterministic heuristics + optional LLM) produces Pydantic-validated candidate profiles.
4. **Deterministic Eligibility Rules** — Hard filter: candidates must have verifiable Python **and** meaningful AI/LLM/RAG/agentic project evidence. Missing GitHub/contact info never causes rejection.
5. **Explainable 100-Point Scoring** — Five weighted categories scored from resume evidence; project-quality penalties applied where evidence supports it.
6. **Lightweight GitHub Enrichment** — Public GitHub API queried per candidate; per-run in-memory cache prevents repeat requests; failures are non-fatal.
7. **Deterministic Ranking** — Eligible candidates sorted by final score; documented tie-breaker; ineligible candidates never enter the ranked list.
8. **Machine-Readable Report** — `results.json` written after every `/report` call; also returned in the API response.

---

## 2. Scoring Formula (Phase 4)

### 100-Point Rubric

| Category | Key | Max Points |
|---|---|---|
| AI / Agentic / RAG Project Depth | `ai_project_depth` | **40** |
| Python & Backend Engineering | `python_backend` | **30** |
| Cloud / Deployment / Full Stack | `cloud_fullstack` | **15** |
| GitHub Activity | `github` | **10** |
| Engineering Depth Signals | `engineering_depth` | **5** |
| **Total before penalties** | | **100** |

**Final score formula:**
```
final_score = max(0, min(100, sum(category_scores) - project_quality_penalty))
```

### Category Scoring Logic

**AI / Agentic / RAG Project Depth (max 40)**
- Advanced AI frameworks (LangChain, LangGraph, LlamaIndex, CrewAI, etc.): +12 each (max 2 → max 24)
- Advanced concepts (RAG, multi-agent, tool-calling, embeddings, vector search, etc.): +8 each (max 2 → max 16)
- Standard AI tools (PyTorch, HuggingFace, OpenAI, etc.): +4 each (max 2 → max 8)
- AI evidence quality bonus (meaningful implementation evidence strings): +8
- **Does NOT award points merely for listing a framework name**

**Python & Backend Engineering (max 30)**
- Python as core programming language: +10
- Deep Python frameworks (FastAPI, Django, Flask, Pytest, Asyncio, Celery): +6 each (max 2)
- Standard Python ecosystem (NumPy, Pandas, Pydantic, etc.): +3 each (max 2)
- Backend infrastructure (PostgreSQL, Redis, MongoDB, etc.): +2 each (max 3)

**Cloud / Deployment / Full Stack (max 15)**
- Cloud provider (AWS, GCP, Azure): +6
- Container/orchestration (Docker, Kubernetes, etc.): +4
- CI/CD pipelines (GitHub Actions, GitLab CI, etc.): +3
- Serverless/PaaS (Cloud Run, Vercel, Lambda, etc.): +2
- Frontend full-stack (React, Next.js, etc.): +2

**GitHub Activity (max 10)**
- Recent activity proxy (repos pushed within 365 days or ≥10 followers): 0–5 points
- Maintained/relevant repositories (AI-related repos detected): 0–5 points
- Details: see [Milestone 4.3](#github-enrichment)

**Engineering Depth Signals (max 5)**
- Testing frameworks (pytest, jest, etc.): +2
- Architecture signals (system design, caching, concurrency, observability): +2
- Code quality/documentation (Swagger, OpenAPI, type hints, etc.): +1

### Project-Quality Penalties (5–15 points)

A penalty between **5 and 15 points** is applied when evidence supports the conclusion that a project is a shallow tutorial or API-wrapper project.

**Penalty triggers:**
- Explicit toy project names (todo app, todo list, CRUD app, calculator, etc.): -5 pts each
- Shallow AI wrapper patterns (simple chatbot, API wrapper, no retrieval) without advanced AI concepts: -5 pts

**Safeguards:**
- Never penalise every project that calls an LLM API
- Do not penalise based on simplicity alone — requires positive evidence of shallowness
- Avoid double-counting the same weakness in both category scores and penalties
- If evidence is insufficient to establish a penalty, none is applied
- Total final score is always clamped to [0, 100]

### Tie-Breaker (deterministic)

When `total_score` is equal:
1. `ai_project_depth` descending (higher AI depth ranks first)
2. `python_backend` descending (higher Python score ranks next)
3. `candidate_name` ascending (alphabetical)

---

## 3. GitHub Enrichment

### Scoring Sub-weights

| Signal | Points |
|---|---|
| Recent public activity (repos pushed within 365 days or ≥10 followers proxy) | 0–5 |
| Maintained/relevant repositories (AI/Python repos detected) | 0–5 |
| **Total maximum** | **10** |

### Reliability Rules

| Behaviour | Implementation |
|---|---|
| Optional auth token | Read from `GITHUB_TOKEN` env var; never hard-coded |
| Per-run cache | `_enrichment_cache` dict keyed by lowercase username; cleared at start of each `/report` batch |
| Request timeouts | 8 seconds per request |
| Rate limit handling | 403/429 → `rate_limited` status; score contribution = 0; candidate NOT rejected |
| 404 handling | → `missing_profile` status; candidate NOT rejected |
| Network failure | → `failed` status; candidate NOT rejected |
| Concurrency | Single-threaded sequential requests (no complex task queue needed at this scale) |
| Private data | Only public API endpoints (`/users/{username}` and `/users/{username}/repos`); no private repo access |

### Status Values

| Status | Meaning |
|---|---|
| `success` | Data fetched successfully from GitHub API |
| `missing_profile` | GitHub returned 404 for the username |
| `rate_limited` | GitHub API returned 403 or 429 |
| `failed` | Network error, timeout, or malformed response |
| `no_github` | No GitHub URL found in the resume |
| `skipped` | Enrichment disabled via `ENRICH_GITHUB_PROFILES=false` |

---

## 4. Report Schema

The `/report` endpoint returns and writes `results.json` with:

```json
{
  "ranked_eligible_candidates": [
    {
      "rank": 1,
      "filename": "alice_resume.pdf",
      "candidate_name": "Alice Engineer",
      "eligible": true,
      "total_score": 78,
      "score_breakdown": {
        "ai_project_depth": 36,
        "python_backend": 22,
        "cloud_fullstack": 10,
        "github": 5,
        "engineering_depth": 5,
        "project_quality_penalty": 0,
        "total_score": 78
      },
      "project_quality_penalty": 0,
      "matched_skills": ["Python", "LangChain", "FastAPI", "Docker"],
      "project_summary": ["RAG Chatbot: Multi-agent pipeline with LangGraph"],
      "github_summary": "GitHub @alice: 30 public repos, 25 followers. 8 repos pushed within the last year.",
      "github_enrichment": {"status": "success", "score": 5, ...},
      "strengths": ["Strong AI/Agentic project depth", "Solid Python & backend engineering"],
      "concerns": [],
      "score_evidence": [...]
    }
  ],
  "rejected_candidates": [
    {
      "filename": "bob_resume.pdf",
      "candidate_name": "Bob Developer",
      "eligible": false,
      "rejection_reasons": ["Missing verifiable Python competency evidence"]
    }
  ],
  "failed_resumes": [
    {
      "filename": "corrupt.pdf",
      "status": "failed",
      "failure_stage": "pdf_parsing",
      "error_message": "Corrupted or invalid PDF format"
    }
  ],
  "duplicates": [
    {
      "filename": "alice_copy.pdf",
      "original_filename": "alice_resume.pdf",
      "file_hash": "sha256hex..."
    }
  ],
  "batch_summary": {
    "total_resumes": 5,
    "successfully_parsed": 3,
    "eligible": 2,
    "rejected": 1,
    "failed_or_unreadable": 1,
    "duplicates": 1,
    "highest_score": 78,
    "lowest_score": 52,
    "average_score": 65.0
  }
}
```

### Count Reconciliation Rules

| Rule | Formula |
|---|---|
| Every uploaded file accounted for | `total_resumes` == number of uploaded files (including duplicates) |
| Unique processing | `successfully_parsed` counts unique, non-duplicate, successfully parsed resumes |
| Eligibility decisions | `eligible + rejected` == `successfully_parsed` |
| Parse failures | `failed_or_unreadable` == failed + no_text files (non-duplicates) |
| Total reconciliation | `eligible + rejected + failed_or_unreadable + duplicates` == `total_resumes` |

---

## 5. Technology Stack

### Backend
- **Language**: Python 3.12+
- **Web Framework**: FastAPI
- **ASGI Server**: Uvicorn
- **PDF Extraction**: PyMuPDF (`fitz`)
- **HTTP Client**: HTTPX (for GitHub API)
- **Validation & Settings**: Pydantic v2 & Pydantic-Settings
- **Testing**: Pytest & HTTPX (FastAPI TestClient)

### Frontend
- **Markup**: Semantic HTML5
- **Styling**: Vanilla CSS3 (Slate dark theme)
- **Scripting**: Vanilla JavaScript (ES6+, Fetch API)

---

## 6. Project Structure

```text
ai-resume-screening/
├── backend/
│   ├── __init__.py            # Backend package marker
│   ├── candidate_extractor.py # Hybrid candidate profile extraction (deterministic + LLM)
│   ├── config.py              # Settings, scoring weights, GitHub config, output path
│   ├── eligibility.py         # Deterministic hard eligibility rules engine
│   ├── github_enricher.py     # Lightweight public GitHub enrichment with per-run cache
│   ├── llm_adapter.py         # Pluggable OpenAI & Gemini LLM adapter with fallback
│   ├── main.py                # FastAPI entry point: /health, /screen, /report
│   ├── pdf_parser.py          # PyMuPDF text extraction module
│   ├── ranker.py              # Scoring pipeline, duplicate detection, ranking, report assembly
│   ├── report_builder.py      # Safe JSON serialisation and atomic file write
│   └── schemas.py             # Pydantic models for all phases
├── frontend/
│   ├── index.html             # Dashboard markup
│   ├── style.css              # Design system, dark theme
│   └── script.js             # Health check, upload, DOM rendering
├── tests/
│   ├── test_candidate_extractor.py
│   ├── test_eligibility.py
│   ├── test_health.py
│   ├── test_pdf_parser.py
│   ├── test_phase4.py         # Phase 4: 50+ tests for scoring, GitHub, ranking, report
│   └── test_screen_api.py
├── results.json               # Generated after each /report call (git-ignored)
├── .env.example               # Safe template for environment variables
├── .env                       # Local environment configuration (git-ignored)
├── .gitignore
├── pytest.ini
├── requirements.txt
└── README.md
```

---

## 7. Prerequisites & Environment Setup

- **Operating System**: Windows 10/11 (or macOS / Linux)
- **Python**: Python 3.10+ (tested on Python 3.12.7)
- **Web Browser**: Modern browser (Chrome, Edge, Firefox)

### Windows Quick Setup

```powershell
# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure environment
Copy-Item .env.example .env
# Edit .env to add optional OPENAI_API_KEY and/or GITHUB_TOKEN
```

### GitHub Token (Optional but recommended)

Without a token, the GitHub API is limited to **60 requests/hour** (unauthenticated).
Add `GITHUB_TOKEN=your_token` in `.env` to raise the limit to **5,000 requests/hour**.

Create a token at: https://github.com/settings/tokens (classic, read:user scope is sufficient).

---

## 8. Running the Servers

### 1. Start the FastAPI Backend

```powershell
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

- **Health Check**: http://127.0.0.1:8000/health
- **Swagger UI**: http://127.0.0.1:8000/docs
- **ReDoc**: http://127.0.0.1:8000/redoc

### 2. Serve the Frontend Dashboard

```powershell
python -m http.server 3000 --directory frontend
```
Navigate to: http://localhost:3000

---

## 9. API Reference

### `GET /health`

Returns backend operational status.

### `POST /screen`

Batch PDF upload with eligibility evaluation (does not score or rank).

- **Request**: `multipart/form-data` with `files[]` (max 50 PDFs, 10 MB each)
- **Response**: `BatchScreenResponse` with per-file extraction results and eligibility status

### `POST /report` ★ Phase 4

Full pipeline: parse → deduplicate → extract → eligibility → score → GitHub enrich → rank → report.

- **Request**: Same as `/screen`
- **Response**: `BatchReport` (ranked candidates, rejected candidates, failed files, duplicates, summary)
- **Side effect**: Writes `results.json` to the project root (safe atomic write)

#### Example: one ranked, one rejected, one failed

```json
{
  "ranked_eligible_candidates": [{
    "rank": 1,
    "candidate_name": "Alice Engineer",
    "total_score": 72,
    "score_breakdown": {
      "ai_project_depth": 36, "python_backend": 22, "cloud_fullstack": 6,
      "github": 5, "engineering_depth": 3, "project_quality_penalty": 0,
      "total_score": 72
    },
    "strengths": ["Strong AI/Agentic project depth"],
    "concerns": []
  }],
  "rejected_candidates": [{
    "candidate_name": "Bob ReactDev",
    "eligible": false,
    "rejection_reasons": ["Missing verifiable Python competency evidence", "Missing AI project evidence"]
  }],
  "failed_resumes": [{
    "filename": "corrupted.pdf",
    "status": "failed",
    "error_message": "Corrupted or invalid PDF format"
  }],
  "duplicates": [],
  "batch_summary": {
    "total_resumes": 3, "successfully_parsed": 2,
    "eligible": 1, "rejected": 1,
    "failed_or_unreadable": 1, "duplicates": 0,
    "highest_score": 72, "lowest_score": 72, "average_score": 72.0
  }
}
```

---

## 10. Running Automated Tests

```powershell
# Full test suite (89 tests across all phases)
pytest -v

# Phase 4 tests only
pytest tests/test_phase4.py -v

# With coverage report
pytest --cov=backend --cov-report=term-missing
```

### Test Coverage (Phase 4 spec requirements)

| # | Requirement | Test |
|---|---|---|
| 1 | All five category scores respect their maximums | `TestScorer::test_*_does_not_exceed_max` |
| 2 | Category weights total 100 | `TestScoringWeights::test_category_weights_sum_to_100` |
| 3 | Final score correctly subtracts penalties | `TestScorer::test_penalty_reduces_total_score` |
| 4 | Final score remains 0–100 | `TestScorer::test_score_capped_at_100`, `test_score_floor_is_zero` |
| 5 | Shallow API-wrapper gets penalty | `TestScorer::test_shallow_ai_wrapper_receives_penalty` |
| 6 | Meaningful AI project not auto-penalised | `TestScorer::test_meaningful_ai_project_not_penalised` |
| 7 | Ineligible candidates never enter ranked list | `TestRanker::test_rejected_candidate_is_not_ranked` |
| 8 | Eligible candidates sorted descending | `TestRanker::test_ranking_order_by_score_descending` |
| 9 | Ties follow documented tie-breaker | `TestRanker::test_tie_break_*` |
| 10 | GitHub scoring never exceeds 10 | `TestGitHubEnricher::test_github_bonus_never_exceeds_10_*` |
| 11 | Missing GitHub profiles don't cause rejection | `TestGitHubEnricher::test_missing_github_profile_does_not_reject_candidate` |
| 12 | GitHub rate limits don't stop the batch | `TestGitHubEnricher::test_enrich_rate_limit_returns_rate_limited` |
| 13 | Repeated profiles use per-run cache | `TestGitHubEnricher::test_repeated_github_url_uses_cache` |
| 14 | One candidate failure doesn't abort batch | `TestRanker::test_enrichment_failure_for_one_does_not_abort_batch` |
| 15 | Duplicate PDFs detected and not ranked twice | `TestRanker::test_duplicate_pdf_detected_and_excluded` |
| 16 | Batch counts reconcile | `TestReportBuilder::test_batch_counts_reconcile` |
| 17 | JSON report validates and serialises | `TestReportBuilder::test_report_serialises_to_valid_json` |
| 18 | Phase 1/2/3 tests still pass | All 38 prior tests still green |

---

## 11. Configuration Reference

All settings are in `backend/config.py` and loaded from environment variables (`.env`).

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai`, `gemini`, or `none` |
| `OPENAI_API_KEY` | — | OpenAI API key (optional; deterministic fallback if unset) |
| `GEMINI_API_KEY` | — | Gemini API key (optional) |
| `GITHUB_TOKEN` | — | GitHub Personal Access Token (optional; raises rate limit to 5000/hr) |
| `ENRICH_GITHUB_PROFILES` | `true` | Set `false` to disable live GitHub API calls |
| `MAX_FILES_PER_BATCH` | `50` | Maximum resumes per request |
| `MAX_FILE_SIZE_BYTES` | `10485760` | Maximum file size (10 MB) |

### Scoring Weights (constants in `config.py`, not env vars)

```python
SCORE_MAX_AI_PROJECT_DEPTH  = 40
SCORE_MAX_PYTHON_BACKEND    = 30
SCORE_MAX_CLOUD_FULLSTACK   = 15
SCORE_MAX_GITHUB            = 10
SCORE_MAX_ENGINEERING_DEPTH =  5
# Total = 100

SCORE_PENALTY_MIN = 5   # minimum penalty per qualifying shallow project
SCORE_PENALTY_MAX = 15  # maximum combined penalty per candidate

GITHUB_MAX_RECENT_ACTIVITY = 5  # sub-score: recent activity proxy
GITHUB_MAX_REPOS           = 5  # sub-score: maintained/relevant repos
```

---

## 12. Known Limitations

1. **Deterministic scoring only**: The scoring engine uses keyword matching, not LLM-based project quality assessment. A highly sophisticated project described without recognisable keywords may score lower than expected.
2. **GitHub enrichment accuracy**: The GitHub API does not expose push frequency or commit counts without authentication. Follower count is used as a proxy for recent activity when push data is insufficient.
3. **Unstructured resumes**: Resumes without clear section headings (Projects, Experience) may have weaker structured extraction; the raw text fallback still contributes to scoring.
4. **LLM extraction quality**: LLM profile extraction depends on the quality of the configured model. With `LLM_PROVIDER=none`, deterministic heuristics are used which may miss nuanced project descriptions.
5. **PDF encoding**: Scanned PDFs (image-only) produce no text and are classified as `no_text`; OCR is not implemented.
6. **No database**: Results are ephemeral per batch. `results.json` captures the last batch run.

---

## 13. Phase Roadmap

| Phase | Status | Description |
|---|---|---|
| Phase 1 | ✅ Done | Project foundation, FastAPI setup, health endpoint |
| Phase 2 | ✅ Done | Batch PDF upload, PyMuPDF text extraction, frontend dashboard |
| Phase 3 | ✅ Done | Structured candidate extraction, LLM adapter, deterministic eligibility rules |
| Phase 4 | ✅ Done | 100-point scoring, GitHub enrichment, duplicate detection, ranking, `results.json` report |
| Phase 5 | 🔜 Planned | Enhanced frontend results dashboard with ranked candidates display |
