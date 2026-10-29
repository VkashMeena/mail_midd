"""
Safe JSON extraction and parser for LLM responses.
Handles raw JSON, fenced markdown codeblocks, and validates against schemas.
"""
import json
import re
import logging
from typing import Dict, Any

from .exceptions import AIValidationError
from .schemas import AIClassificationResult, validate_classification_payload

logger = logging.getLogger(__name__)


def extract_json_from_text(raw_text: str) -> Dict[str, Any]:
    """
    Extracts a JSON object from text that may contain markdown formatting,
    fenced code blocks (```json ... ```), or leading/trailing commentary.
    """
    if not raw_text or not raw_text.strip():
        raise AIValidationError("Empty response received from AI provider.")

    cleaned = raw_text.strip()

    # Pattern 1: Fenced markdown code block ```json { ... } ``` or ``` { ... } ```
    block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL | re.IGNORECASE)
    if block_match:
        cleaned = block_match.group(1).strip()
    else:
        # Pattern 2: First '{' to last '}'
        start_idx = cleaned.find('{')
        end_idx = cleaned.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            cleaned = cleaned[start_idx:end_idx + 1]

    try:
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            raise AIValidationError(f"Parsed JSON must be an object/dict, got {type(data).__name__}")
        return data
    except json.JSONDecodeError as exc:
        logger.warning("Failed to decode AI JSON response: %s | Raw response snippet: %s", exc, raw_text[:200])
        raise AIValidationError(f"Invalid JSON in AI response: {exc}")


def parse_and_validate_classification(raw_response_text: str) -> AIClassificationResult:
    """
    Parses raw LLM text into JSON and runs strict schema validation.
    """
    data = extract_json_from_text(raw_response_text)
    return validate_classification_payload(data)
