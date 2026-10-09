"""
Report builder module for the AI Resume Screening System (Phase 4).

Responsibility:
  - Serialise a BatchReport to a valid JSON file (results.json).
  - Use a safe write process (write to a temp path, then rename) so that a
    crash during serialisation does not overwrite a previously valid report.
  - Validate that all numeric values are finite (no NaN / Infinity) before
    writing.

Output path: results.json in the project root (configurable via RESULTS_JSON_PATH
in backend/config.py).
"""

import json
import logging
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from backend.config import RESULTS_JSON_PATH
from backend.schemas import BatchReport

logger = logging.getLogger(__name__)


def _sanitise(obj: Any) -> Any:
    """
    Recursively convert a decoded JSON-like structure to a form that is safe
    for json.dumps():
      - Replace float NaN / ±Inf with None.
      - Leave all other values unchanged.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitise(v) for v in obj]
    return obj


def write_report(report: BatchReport, output_path: str = RESULTS_JSON_PATH) -> str:
    """
    Serialise *report* to a JSON file at *output_path*.

    Uses a safe write process:
      1. Serialise to a temporary file in the same directory.
      2. Validate the JSON is complete and finite.
      3. Atomically replace the target file with the temp file.

    Returns the absolute path of the written report.
    Raises RuntimeError if serialisation fails (caller decides what to do).
    """
    output_path = str(Path(output_path).resolve())
    output_dir = os.path.dirname(output_path) or "."

    # Convert Pydantic model to dict, then sanitise
    try:
        raw_dict = report.model_dump(mode="json")
        clean_dict = _sanitise(raw_dict)
        payload = json.dumps(clean_dict, indent=2, ensure_ascii=False)
    except Exception as exc:
        raise RuntimeError(f"Failed to serialise BatchReport: {exc}") from exc

    # Safe write: temp file → rename
    try:
        fd, tmp_path = tempfile.mkstemp(dir=output_dir, suffix=".tmp", prefix="results_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
        except Exception:
            os.unlink(tmp_path)
            raise
        os.replace(tmp_path, output_path)
        logger.info("BatchReport written to %s (%d bytes).", output_path, len(payload))
    except Exception as exc:
        raise RuntimeError(f"Failed to write report to {output_path}: {exc}") from exc

    return output_path


def build_report_dict(report: BatchReport) -> dict:
    """
    Return the sanitised dict representation of the report without writing it
    to disk.  Useful for API responses or in-memory validation.
    """
    raw_dict = report.model_dump(mode="json")
    return _sanitise(raw_dict)
