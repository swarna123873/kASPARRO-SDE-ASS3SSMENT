"""
Configuration module for the AI Resume Screening System.
Loads application settings and environment variables with Pydantic Settings.

Scoring weights for the 100-point rubric are defined here as constants so
that the scoring engine can import them from a single, auditable location.
"""

from typing import List, Optional, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ──────────────────────────────────────────────────────────────────────────────
# Phase 4 Scoring Rubric Constants
# These are the canonical weights. Changing a value here propagates everywhere.
# ──────────────────────────────────────────────────────────────────────────────

# Category maximums (must sum to 100 before penalties)
SCORE_MAX_AI_PROJECT_DEPTH: int = 40      # AI / Agentic / RAG Project Depth
SCORE_MAX_PYTHON_BACKEND: int = 30        # Python & Backend Engineering
SCORE_MAX_CLOUD_FULLSTACK: int = 15       # Cloud / Deployment / Full Stack
SCORE_MAX_GITHUB: int = 10               # GitHub Activity
SCORE_MAX_ENGINEERING_DEPTH: int = 5     # Engineering Depth Signals

# Penalty bounds
SCORE_PENALTY_MIN: int = 5    # minimum penalty for a qualifying shallow project
SCORE_PENALTY_MAX: int = 15   # maximum penalty applied in a single batch run

# Verify the rubric totals to 100 (caught at import time, not test-time)
_RUBRIC_TOTAL = (
    SCORE_MAX_AI_PROJECT_DEPTH
    + SCORE_MAX_PYTHON_BACKEND
    + SCORE_MAX_CLOUD_FULLSTACK
    + SCORE_MAX_GITHUB
    + SCORE_MAX_ENGINEERING_DEPTH
)
assert _RUBRIC_TOTAL == 100, (
    f"Scoring rubric weights must sum to 100, but they sum to {_RUBRIC_TOTAL}. "
    "Update the constants in backend/config.py."
)

# GitHub scoring sub-weights (sum ≤ SCORE_MAX_GITHUB)
GITHUB_MAX_RECENT_ACTIVITY: int = 5   # recent public activity
GITHUB_MAX_REPOS: int = 5             # maintained / relevant repositories

# Report output path (relative to project root)
RESULTS_JSON_PATH: str = "results.json"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    app_name: str = "AI Resume Screening System"
    app_version: str = "0.4.0"
    app_env: str = "development"
    debug: bool = True
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # Batch upload limits
    max_files_per_batch: int = 50
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10 MB per resume file

    # LLM Provider Configuration (Phase 3)
    # Providers supported: 'openai' (or compatible), 'gemini', 'none'
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_timeout_seconds: float = 20.0
    llm_temperature: float = 0.0

    # GitHub Enrichment Configuration (Phase 4)
    # Optional token raises rate limit from 60 → 5000 requests/hour
    github_token: Optional[str] = None
    # Set to False to disable live GitHub API calls (useful for offline testing)
    enrich_github_profiles: bool = True

    # Explicit allowed origins for CORS.
    # Includes common local development servers and 'null' for local file:// testing.
    cors_origins: Union[List[str], str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "null",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Union[str, List[str]]) -> List[str]:
        """Convert comma-separated origin strings into a list of origins."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
