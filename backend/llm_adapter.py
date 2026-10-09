"""
LLM adapter for semantic resume information extraction.
Supports OpenAI-compatible APIs and Google Gemini REST endpoints with graceful failure handling.
"""

import json
import logging
from typing import Any, Dict, Optional
import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

SYSTEM_EXTRACTION_PROMPT = """You are an expert technical resume screening parser.
Extract structured candidate information from the provided resume text.
Your output MUST be a valid JSON object matching the following structure:
{
  "candidate_name": "Full Name or null",
  "email": "Email address or null",
  "phone": "Phone number or null",
  "education": ["Degree, Major, Institution"],
  "programming_languages": ["Python", "JavaScript", etc.],
  "technical_skills": ["SQL", "FastAPI", "Docker", etc.],
  "frameworks_and_tools": ["LangChain", "PyTorch", "Git", etc.],
  "projects": [
    {
      "name": "Project Name",
      "description": "Brief description of the project",
      "technologies": ["Technology 1", "Technology 2"],
      "implementation_details": "Key workflow, RAG pipeline, agentic tools, models, or backend details",
      "supporting_evidence": "Exact or closely paraphrased quote/sentence from the resume"
    }
  ],
  "work_experience": [
    {
      "role": "Job / Internship Title",
      "organization": "Company Name",
      "technologies": ["Technologies used"],
      "responsibilities": "Key duties and achievements",
      "evidence": "Evidence quote from resume"
    }
  ],
  "github_url": "https://github.com/username or null"
}

CRITICAL RULES:
1. Do NOT hallucinate or invent candidate experience, projects, or technologies.
2. Only include technologies and projects explicitly mentioned in the resume.
3. If information for a field is missing, use null or an empty list.
4. Output raw JSON only with NO markdown fences or commentary.
"""


class LLMAdapter:
    """Resilient, replaceable LLM client interface for resume extraction."""

    def __init__(self):
        self.provider = (settings.llm_provider or "none").lower()
        self.model = settings.llm_model
        self.timeout = settings.llm_timeout_seconds
        self.openai_key = settings.openai_api_key
        self.gemini_key = settings.gemini_api_key
        self.base_url = settings.llm_base_url or "https://api.openai.com/v1"

    def is_configured(self) -> bool:
        """Check if a valid LLM provider and API key are configured."""
        if self.provider == "openai" and self.openai_key:
            return True
        if self.provider == "gemini" and self.gemini_key:
            return True
        return False

    def extract_candidate_data(self, resume_text: str) -> Optional[Dict[str, Any]]:
        """
        Send resume text to configured LLM and retrieve structured JSON.
        Returns parsed dictionary if successful, or None if unconfigured / failed.
        """
        if not self.is_configured():
            return None

        if self.provider == "openai":
            return self._call_openai(resume_text)
        elif self.provider == "gemini":
            return self._call_gemini(resume_text)
        else:
            return None

    def _call_openai(self, resume_text: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openai_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_EXTRACTION_PROMPT},
                {"role": "user", "content": f"Resume Text:\n\n{resume_text}"},
            ],
            "temperature": settings.llm_temperature,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)
        except httpx.TimeoutException:
            logger.warning("OpenAI LLM request timed out after %.1f seconds.", self.timeout)
            return None
        except httpx.HTTPStatusError as err:
            logger.warning("OpenAI LLM API HTTP error: status %s", err.response.status_code)
            return None
        except Exception as exc:
            logger.warning("OpenAI LLM extraction failed: %s", type(exc).__name__)
            return None

    def _call_gemini(self, resume_text: str) -> Optional[Dict[str, Any]]:
        model_name = self.model or "gemini-1.5-flash"
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            f"?key={self.gemini_key}"
        )
        headers = {"Content-Type": "application/json"}
        prompt = f"{SYSTEM_EXTRACTION_PROMPT}\n\nResume Text:\n\n{resume_text}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": settings.llm_temperature,
            },
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(content)
        except httpx.TimeoutException:
            logger.warning("Gemini LLM request timed out after %.1f seconds.", self.timeout)
            return None
        except httpx.HTTPStatusError as err:
            logger.warning("Gemini LLM API HTTP error: status %s", err.response.status_code)
            return None
        except Exception as exc:
            logger.warning("Gemini LLM extraction failed: %s", type(exc).__name__)
            return None


# Default shared adapter instance
llm_adapter = LLMAdapter()
