"""
Lightweight public GitHub profile enrichment module.

Fetches public user data from the GitHub REST API (unauthenticated by default).
  - Rate limit: 60 requests/hour without a token.
  - GITHUB_TOKEN in .env raises the limit to 5 000/hr.
  - Per-run in-memory cache prevents repeated API calls for the same username.
  - All network errors are caught; enrichment failure never aborts the batch.
  - No private data is accessed; only public endpoints are called.

GitHub score sub-weights (from config.py):
  Recent public activity   0–5 pts  (GITHUB_MAX_RECENT_ACTIVITY)
  Maintained/relevant repos 0–5 pts  (GITHUB_MAX_REPOS)
  Total maximum            0–10 pts  (SCORE_MAX_GITHUB)

Time window: repositories pushed within the last 365 days are considered
"recently updated".  Followers ≥ 10 are used as an activity proxy when the
events endpoint is unavailable without a token.

Status values returned:
  success         — data fetched successfully
  missing_profile — GitHub 404 (user not found)
  rate_limited    — GitHub 403/429 (rate limit exceeded)
  failed          — network/timeout/unexpected API error
  no_github       — no GitHub URL found in the resume
  skipped         — enrichment disabled via config flag
"""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx

from backend.config import (
    GITHUB_MAX_RECENT_ACTIVITY,
    GITHUB_MAX_REPOS,
    SCORE_MAX_GITHUB,
    settings,
)
from backend.schemas import GitHubEnrichmentResult

logger = logging.getLogger(__name__)

# AI-related keywords used to detect AI projects in repo names/descriptions
AI_PROJECT_SIGNALS: set = {
    "rag", "llm", "langchain", "agentic", "agent", "gpt", "openai",
    "gemini", "embeddings", "vector", "nlp", "transformer", "pytorch",
    "tensorflow", "huggingface", "chatbot", "ai", "ml", "machine-learning",
    "deep-learning", "retrieval",
}

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT = 8.0  # seconds

# ── Per-run in-memory cache ────────────────────────────────────────────────────
# Key: normalised lowercase GitHub username
# Value: GitHubEnrichmentResult  (populated once per batch/process lifetime)
_enrichment_cache: Dict[str, GitHubEnrichmentResult] = {}


def clear_enrichment_cache() -> None:
    """Clear the per-run enrichment cache (used between test runs)."""
    _enrichment_cache.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _extract_username(github_url: str) -> Optional[str]:
    """Extract the GitHub username from a profile URL or plain username."""
    if not github_url:
        return None
    # Match https://github.com/username or github.com/username
    match = re.search(r"github\.com/([a-zA-Z0-9_-]+)", github_url, re.IGNORECASE)
    if match:
        username = match.group(1)
        # Exclude organisation-like reserved paths
        if username.lower() not in {"features", "about", "pricing", "blog", "login"}:
            return username
    return None


def _build_headers() -> dict:
    """Build API request headers, attaching token if configured."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "AI-Resume-Screener/1.0",
    }
    token = getattr(settings, "github_token", None)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _detect_ai_repos(repos: list) -> List[str]:
    """Return names of repos whose name or description contains AI signals."""
    ai_repos: List[str] = []
    for repo in repos:
        name = (repo.get("name") or "").lower()
        desc = (repo.get("description") or "").lower()
        combined = f"{name} {desc}"
        for signal in AI_PROJECT_SIGNALS:
            if re.search(rf"\b{re.escape(signal)}\b", combined):
                ai_repos.append(repo.get("name", ""))
                break
    return ai_repos


def _top_languages_from_repos(repos: list) -> List[str]:
    """Collect unique languages from the top public repos."""
    langs: List[str] = []
    for repo in repos:
        lang = repo.get("language")
        if lang and lang not in langs:
            langs.append(lang)
        if len(langs) >= 5:
            break
    return langs


def _is_recently_pushed(pushed_at: Optional[str], days: int = 365) -> bool:
    """Return True if pushed_at is within the last *days* days."""
    if not pushed_at:
        return False
    try:
        dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (now - dt).days <= days
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# GitHub score computation
# ──────────────────────────────────────────────────────────────────────────────

def compute_github_score_bonus(
    enrichment: "GitHubEnrichmentResult",
) -> Tuple[int, List[str]]:
    """
    Compute the GitHub Activity score contribution (max SCORE_MAX_GITHUB = 10).

    Sub-scores:
      Recent activity proxy (followers ≥ 10 or recently pushed repos):
        ≥ 5 recently-active repos  → GITHUB_MAX_RECENT_ACTIVITY pts (5)
        1–4 recently-active repos  → partial credit proportional
        ≥ 10 followers as proxy    → 3 pts

      Maintained / relevant repos:
        Has AI-related repo        → GITHUB_MAX_REPOS pts (5)
        ≥ 20 public repos          → 3 pts
        ≥ 5 public repos           → 2 pts

    Returns (score, evidence_strings).
    Only returns non-zero for 'success' status.
    """
    if enrichment.status != "success":
        return 0, []

    pts = 0
    evidence: List[str] = []

    # ── Recent activity sub-score (0–5) ─────────────────────────────────────
    activity_pts = 0
    recent_count = getattr(enrichment, "_recent_repo_count", 0)
    if recent_count >= 5:
        activity_pts = GITHUB_MAX_RECENT_ACTIVITY
        evidence.append(f"Active recent development: {recent_count} repos pushed within the last year.")
    elif recent_count >= 1:
        activity_pts = min(recent_count, GITHUB_MAX_RECENT_ACTIVITY - 1)
        evidence.append(f"Some recent activity: {recent_count} repos pushed within the last year.")
    elif (enrichment.followers or 0) >= 10:
        activity_pts = 3
        evidence.append(f"GitHub community engagement proxy: {enrichment.followers} followers.")
    pts += activity_pts

    # ── Maintained / relevant repos sub-score (0–5) ──────────────────────────
    repo_pts = 0
    if enrichment.has_pinned_ai_project:
        repo_pts = GITHUB_MAX_REPOS
        evidence.append(
            f"AI/ML-related public repositories detected: "
            f"{', '.join(enrichment.relevant_repositories[:3]) or 'present'}."
        )
    elif (enrichment.public_repos or 0) >= 20:
        repo_pts = 3
        evidence.append(f"Active GitHub presence: {enrichment.public_repos} public repositories.")
    elif (enrichment.public_repos or 0) >= 5:
        repo_pts = 2
        evidence.append(f"GitHub profile with {enrichment.public_repos} public repositories.")
    pts += repo_pts

    return min(pts, SCORE_MAX_GITHUB), evidence


# ──────────────────────────────────────────────────────────────────────────────
# Public API: enrich_github  (with per-run cache)
# ──────────────────────────────────────────────────────────────────────────────

def enrich_github(github_url: Optional[str]) -> GitHubEnrichmentResult:
    """
    Fetch public GitHub profile data for a candidate.

    Returns GitHubEnrichmentResult with status:
      'no_github'       — no GitHub URL found in the resume
      'success'         — data fetched successfully
      'missing_profile' — GitHub returned 404 (user not found)
      'rate_limited'    — GitHub API returned 403 or 429
      'failed'          — network error, timeout, or malformed response
    """
    if not github_url:
        return GitHubEnrichmentResult(status="no_github")

    username = _extract_username(github_url)
    if not username:
        return GitHubEnrichmentResult(
            status="failed",
            error_message=f"Could not extract a valid username from URL: {github_url}",
        )

    cache_key = username.lower()

    # ── Cache hit ─────────────────────────────────────────────────────────────
    if cache_key in _enrichment_cache:
        logger.debug("GitHub cache hit for user '%s'.", username)
        return _enrichment_cache[cache_key]

    # ── Live API fetch ────────────────────────────────────────────────────────
    profile_url = f"https://github.com/{username}"
    headers = _build_headers()

    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            # 1. Fetch user profile
            user_resp = client.get(f"{GITHUB_API_BASE}/users/{username}", headers=headers)

            if user_resp.status_code == 404:
                result = GitHubEnrichmentResult(
                    status="missing_profile",
                    profile_url=profile_url,
                    github_username=username,
                    error_message=f"GitHub user '{username}' not found (404).",
                )
                _enrichment_cache[cache_key] = result
                return result

            if user_resp.status_code in (403, 429):
                result = GitHubEnrichmentResult(
                    status="rate_limited",
                    profile_url=profile_url,
                    github_username=username,
                    error_message=(
                        "GitHub API rate limit exceeded. "
                        "Set GITHUB_TOKEN in .env to increase the limit."
                    ),
                )
                _enrichment_cache[cache_key] = result
                return result

            user_resp.raise_for_status()
            user_data = user_resp.json()

            # 2. Fetch public repos (up to 30, sorted by most recently pushed)
            repos_resp = client.get(
                f"{GITHUB_API_BASE}/users/{username}/repos",
                headers=headers,
                params={"sort": "pushed", "per_page": 30, "type": "public"},
            )
            repos: list = repos_resp.json() if repos_resp.status_code == 200 else []
            if not isinstance(repos, list):
                repos = []

        # Post-process
        ai_repos = _detect_ai_repos(repos)
        top_languages = _top_languages_from_repos(repos)
        recent_repo_count = sum(
            1 for r in repos if _is_recently_pushed(r.get("pushed_at"))
        )
        public_repos = user_data.get("public_repos", 0) or 0
        followers = user_data.get("followers", 0) or 0

        # Build human-readable summaries
        recent_summary = (
            f"{recent_repo_count} repos pushed within the last 365 days."
            if recent_repo_count
            else "No recently-pushed public repositories found."
        )
        repo_summary = (
            f"{public_repos} public repositories; "
            f"top languages: {', '.join(top_languages[:3]) or 'N/A'}."
        )

        result = GitHubEnrichmentResult(
            status="success",
            profile_url=profile_url,
            github_username=username,
            public_repos=public_repos,
            followers=followers,
            following=user_data.get("following"),
            bio=(user_data.get("bio") or "")[:200] or None,
            top_languages=top_languages,
            has_pinned_ai_project=bool(ai_repos),
            relevant_repositories=ai_repos[:10],
            recent_activity_summary=recent_summary,
            repository_summary=repo_summary,
        )
        # Attach hidden count for score computation
        object.__setattr__(result, "_recent_repo_count", recent_repo_count)

        _enrichment_cache[cache_key] = result
        return result

    except httpx.TimeoutException:
        logger.warning("GitHub enrichment timed out for user '%s'.", username)
        result = GitHubEnrichmentResult(
            status="failed",
            profile_url=profile_url,
            github_username=username,
            error_message=f"Request timed out after {DEFAULT_TIMEOUT}s.",
        )
        _enrichment_cache[cache_key] = result
        return result

    except httpx.HTTPStatusError as err:
        logger.warning("GitHub API HTTP error for '%s': %s", username, err.response.status_code)
        result = GitHubEnrichmentResult(
            status="failed",
            profile_url=profile_url,
            github_username=username,
            error_message=f"HTTP {err.response.status_code} from GitHub API.",
        )
        _enrichment_cache[cache_key] = result
        return result

    except Exception as exc:
        logger.warning("GitHub enrichment failed for '%s': %s", username, str(exc))
        result = GitHubEnrichmentResult(
            status="failed",
            profile_url=profile_url,
            github_username=username,
            error_message=str(exc),
        )
        _enrichment_cache[cache_key] = result
        return result
