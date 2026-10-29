"""
Groq LLM Provider implementation using Groq SDK and high-performance LPU inference.
Supports Llama 3.3 70B, Llama 3.1 8B, and Mixtral models with ultra-low latency.
"""
import time
import json
import logging
from typing import Dict, Any, Optional
import requests
from django.conf import settings

from ..exceptions import (
    AIConfigurationError,
    AIRateLimitError,
    AITimeoutError,
    AIProviderError
)
from ..prompts import (
    CLASSIFICATION_SYSTEM_PROMPT,
    CLASSIFICATION_USER_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    SUMMARY_USER_PROMPT,
    REPLY_SYSTEM_PROMPT,
    REPLY_USER_PROMPT,
)
from .base import BaseAIProvider

logger = logging.getLogger(__name__)

# Optional Groq SDK import
try:
    from groq import Groq as GroqClient
    GROQ_SDK_AVAILABLE = True
except ImportError:
    GroqClient = None
    GROQ_SDK_AVAILABLE = False


class GroqProvider(BaseAIProvider):
    """
    Groq API Provider for ultra-fast LPU inference.
    Supports email classification, deep intelligence analysis, daily summarization,
    and context-aware email reply generation.
    """

    DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
    DEFAULT_MODEL = "openai/gpt-oss-120b"
    FALLBACK_MODEL = "openai/gpt-oss-20b"
    SUPPORTED_MODELS = [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = None

    @property
    def api_key(self) -> str:
        if self._api_key is not None:
            return str(self._api_key).strip()
        key = getattr(settings, 'GROQ_API_KEY', '')
        return str(key).strip()


    @property
    def model(self) -> str:
        return self._model or getattr(settings, 'GROQ_MODEL', self.DEFAULT_MODEL)

    @property
    def base_url(self) -> str:
        url = self._base_url or getattr(settings, 'GROQ_BASE_URL', '')
        return url.rstrip('/') if url else self.DEFAULT_BASE_URL

    @property
    def timeout(self) -> int:
        return self._timeout or getattr(settings, 'AI_TIMEOUT', 30)

    @property
    def max_retries(self) -> int:
        return self._max_retries or getattr(settings, 'AI_MAX_RETRIES', 3)

    @property
    def temperature(self) -> float:
        return self._temperature if self._temperature is not None else getattr(settings, 'AI_TEMPERATURE', 0.2)

    @property
    def max_tokens(self) -> int:
        return self._max_tokens or getattr(settings, 'AI_MAX_TOKENS', 1500)

    def is_configured(self) -> bool:
        return bool(self.api_key and not self.api_key.startswith('gsk_your-groq'))

    def _get_groq_client(self):
        if not self.is_configured():
            raise AIConfigurationError("Groq API key is missing. Please set GROQ_API_KEY in your .env or settings.")
        if self._client is None and GROQ_SDK_AVAILABLE:
            try:
                self._client = GroqClient(api_key=self.api_key, timeout=self.timeout)
            except Exception as exc:
                logger.warning("Could not initialize Groq SDK client (%s); falling back to REST", exc)
                self._client = None
        return self._client

    def _chat_completion(
        self,
        messages: list,
        json_mode: bool = False,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> str:
        """
        Executes a chat completion call to Groq with automatic retry, backoff, and error translation.
        Prefers official Groq SDK and falls back to HTTP REST.
        """
        if not self.is_configured():
            raise AIConfigurationError(
                "Groq API key is missing or invalid. Please set GROQ_API_KEY in your .env or settings."
            )

        target_model = model or self.model
        req_timeout = timeout or self.timeout
        req_temp = temperature if temperature is not None else self.temperature
        req_max_tokens = max_tokens or self.max_tokens

        retries = self.max_retries
        backoff_seconds = 1.0

        # Attempt with Groq SDK if available
        client = self._get_groq_client()
        if client:
            for attempt in range(1, retries + 1):
                try:
                    kwargs = {
                        "model": target_model,
                        "messages": messages,
                        "temperature": req_temp,
                        "max_tokens": req_max_tokens,
                    }
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}

                    completion = client.chat.completions.create(**kwargs)
                    if completion.choices and len(completion.choices) > 0:
                        content = completion.choices[0].message.content
                        if content:
                            return content.strip()
                    raise AIProviderError("Groq returned empty response choices.")

                except Exception as exc:
                    err_str = str(exc).lower()
                    if "model_not_found" in err_str or "404" in err_str or "does not exist" in err_str:
                        for cand in self.SUPPORTED_MODELS:
                            if cand != target_model:
                                logger.info("Groq model '%s' unavailable; auto-switching to '%s'", target_model, cand)
                                target_model = cand
                                break
                        continue
                    elif "rate limit" in err_str or "429" in err_str:
                        logger.warning("Groq rate limit hit on attempt %d/%d: %s", attempt, retries, exc)
                        if attempt < retries:
                            time.sleep(backoff_seconds)
                            backoff_seconds *= 2.0
                            if target_model == self.DEFAULT_MODEL:
                                target_model = self.FALLBACK_MODEL
                            continue
                        raise AIRateLimitError("Groq rate limit reached. Please retry in a few moments.")
                    elif "auth" in err_str or "401" in err_str or "403" in err_str or "invalid api key" in err_str:
                        raise AIConfigurationError(f"Groq authentication failed: {exc}")
                    elif "timeout" in err_str:
                        if attempt < retries:
                            time.sleep(backoff_seconds)
                            backoff_seconds *= 2.0
                            continue
                        raise AITimeoutError(f"Groq request timed out after {req_timeout}s.")
                    else:
                        logger.warning("Groq SDK call failed (%s); trying REST fallback", exc)
                        break  # Break to REST fallback

        # HTTP REST Fallback
        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": target_model,
            "temperature": req_temp,
            "max_tokens": req_max_tokens,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(1, retries + 1):
            try:
                response = requests.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=req_timeout
                )

                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices", [])
                    if not choices:
                        raise AIProviderError("Groq returned 200 OK but with empty 'choices' list.")
                    return choices[0]["message"]["content"].strip()

                if response.status_code == 404 or "model_not_found" in response.text:
                    for cand in self.SUPPORTED_MODELS:
                        if cand != target_model:
                            logger.info("Groq REST model '%s' unavailable (404); auto-switching to '%s'", target_model, cand)
                            target_model = cand
                            payload["model"] = target_model
                            break
                    continue

                if response.status_code == 429:
                    logger.warning("Groq REST rate limit hit (429) on attempt %d/%d", attempt, retries)
                    if attempt < retries:
                        time.sleep(backoff_seconds)
                        backoff_seconds *= 2.0
                        if target_model == self.DEFAULT_MODEL:
                            payload["model"] = self.FALLBACK_MODEL
                        continue
                    raise AIRateLimitError("Groq API rate limit reached. Please retry shortly.")

                if response.status_code in (401, 403):
                    raise AIConfigurationError(f"Groq authentication failed (HTTP {response.status_code}).")

                if response.status_code in (500, 502, 503, 504):
                    logger.warning("Groq server error (%d) on attempt %d/%d", response.status_code, attempt, retries)
                    if attempt < retries:
                        time.sleep(backoff_seconds)
                        backoff_seconds *= 2.0
                        continue
                    raise AIProviderError(f"Groq server error (HTTP {response.status_code}).")

                err_msg = response.text[:200]
                raise AIProviderError(f"Groq error (HTTP {response.status_code}): {err_msg}")

            except requests.exceptions.Timeout as exc:
                if attempt < retries:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2.0
                    continue
                raise AITimeoutError(f"Groq request timed out after {req_timeout}s.")
            except requests.exceptions.RequestException as exc:
                if attempt < retries:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2.0
                    continue
                raise AIProviderError(f"Network error contacting Groq: {exc}")

    def classify(self, email_data: Dict[str, Any]) -> str:
        """
        Sends email metadata and sanitized body to Groq endpoint.
        Returns raw JSON string returned by the model.
        """
        user_content = CLASSIFICATION_USER_PROMPT.format(
            sender_name=email_data.get('sender_name', 'Unknown'),
            sender_email=email_data.get('sender_email', ''),
            subject=email_data.get('subject', '(No Subject)'),
            gmail_labels=", ".join(email_data.get('gmail_labels', [])) or 'None',
            body_text=email_data.get('body_text', '')
        )
        messages = [
            {"role": "system", "content": CLASSIFICATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]
        return self._chat_completion(messages, json_mode=True, max_tokens=500)

    def analyze(self, analysis_payload: Dict[str, Any]) -> str:
        """
        Executes deep intelligence analysis of an email via Groq.
        Extracts objective, category, priority, urgency, sentiment, key points,
        action items, deadlines, and suggested reply hooks.
        """
        from ..prompts import ANALYSIS_SYSTEM_PROMPT, ANALYSIS_USER_PROMPT

        user_content = ANALYSIS_USER_PROMPT.format(
            sender_name=analysis_payload.get('sender_name', 'Unknown'),
            sender_email=analysis_payload.get('sender_email', ''),
            recipient_email=analysis_payload.get('recipient_email', ''),
            subject=analysis_payload.get('subject', '(No Subject)'),
            received_at=analysis_payload.get('received_at', 'Recent'),
            attachments_info=analysis_payload.get('attachments_info', 'None'),
            gmail_labels=", ".join(analysis_payload.get('gmail_labels', [])) or 'None',
            body_text=analysis_payload.get('body_text', '')
        )
        messages = [
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]
        return self._chat_completion(messages, json_mode=True, max_tokens=1200, temperature=0.1)

    def summarize(self, summary_payload: Dict[str, Any]) -> str:
        """
        Sends daily email stream and metadata to Groq endpoint.
        Returns raw JSON string conforming to daily summary schema.
        """
        user_content = SUMMARY_USER_PROMPT.format(
            summary_date=summary_payload.get('summary_date', 'Today'),
            total_count=summary_payload.get('total_count', 0),
            important_count=summary_payload.get('important_count', 0),
            unread_count=summary_payload.get('unread_count', 0),
            category_breakdown=summary_payload.get('category_breakdown', 'None'),
            emails_text=summary_payload.get('emails_text', 'No emails received.')
        )
        messages = [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]
        max_tokens = getattr(settings, 'AI_SUMMARY_MAX_TOKENS', 1200)
        return self._chat_completion(messages, json_mode=True, max_tokens=max_tokens, temperature=0.2)

    def generate_reply(self, reply_payload: Dict[str, Any]) -> str:
        """
        Generates context-aware, human-like professional email reply drafts using Groq LPU.
        Adapts dynamically to Short, Medium, or Long length and Professional, Polite, Friendly,
        Formal, or Casual tone.
        """
        r_tone = reply_payload.get('reply_tone') or reply_payload.get('tone') or 'Professional'
        r_length = reply_payload.get('reply_length') or reply_payload.get('length') or 'Medium'
        c_instruction = reply_payload.get('custom_instruction') or reply_payload.get('instruction') or 'None'
        format_label = reply_payload.get('format_label') or f"{r_length} + {r_tone}"

        prompt_vars = {
            'recipient_name': reply_payload.get('recipient_name', 'Recipient'),
            'recipient_email': reply_payload.get('recipient_email', ''),
            'sender_name': reply_payload.get('sender_name', 'Unknown'),
            'sender_email': reply_payload.get('sender_email', ''),
            'subject': reply_payload.get('subject', '(No Subject)'),
            'received_at': reply_payload.get('received_at', 'Recent'),
            'category': reply_payload.get('category', 'General'),
            'priority': reply_payload.get('priority', 'Medium'),
            'attachments_info': reply_payload.get('attachments_info', 'None'),
            'thread_context': reply_payload.get('thread_context', 'None'),
            'body_text': reply_payload.get('body_text', ''),
            'format_label': format_label,
            'reply_length': r_length,
            'reply_tone': r_tone,
            'custom_instruction': c_instruction,
            'tone': r_tone,
            'length': r_length,
            'instruction': c_instruction,
        }

        user_content = REPLY_USER_PROMPT.format(**prompt_vars)
        messages = [
            {"role": "system", "content": REPLY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        # Allocate max tokens according to length
        length_lower = str(r_length).lower()
        if 'short' in length_lower:
            reply_tokens = 350
        elif 'long' in length_lower:
            reply_tokens = 1500
        else:
            reply_tokens = 750

        return self._chat_completion(
            messages,
            json_mode=False,
            max_tokens=reply_tokens,
            temperature=0.3
        )
