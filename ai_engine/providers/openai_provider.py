"""
OpenAI-compatible LLM Provider implementation using lightweight requests.
Supports OpenAI, Azure OpenAI, OpenRouter, Ollama, and local vLLM servers.
"""
import time
import logging
from typing import Dict, Any
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


class OpenAICompatibleProvider(BaseAIProvider):
    """
    OpenAI-compatible HTTP provider.
    Executes REST calls to /chat/completions with automatic retry and rate-limit handling.
    """

    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(
        self,
        api_key: str = None,
        model: str = None,
        base_url: str = None,
        timeout: int = None,
        max_retries: int = None,
        temperature: float = None,
        max_tokens: int = None
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def api_key(self) -> str:
        return self._api_key or getattr(settings, 'AI_API_KEY', '')

    @property
    def model(self) -> str:
        return self._model or getattr(settings, 'AI_MODEL', 'gpt-4o-mini')

    @property
    def base_url(self) -> str:
        url = self._base_url or getattr(settings, 'AI_BASE_URL', '')
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
        return self._max_tokens or getattr(settings, 'AI_MAX_TOKENS', 500)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _chat_completion(
        self,
        messages: list,
        json_mode: bool = False,
        max_tokens: int = None,
        temperature: float = None,
        model: str = None,
        timeout: int = None
    ) -> str:
        """
        Executes a REST call to /chat/completions with automatic retry, backoff, and error translation.
        """
        if not self.is_configured():
            raise AIConfigurationError("AI API key is missing. Please set AI_API_KEY in your .env file.")

        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model or self.model,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": messages,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        retries = self.max_retries
        backoff_seconds = 1.0
        req_timeout = timeout or self.timeout

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
                    choices = data.get('choices', [])
                    if not choices:
                        raise AIProviderError("Provider returned 200 OK but with empty 'choices' list.")
                    return choices[0]['message']['content']

                if response.status_code == 429:
                    logger.warning("AI rate limit hit (429) on attempt %d/%d", attempt, retries)
                    try:
                        err_data = response.json().get('error', {})
                        err_code = err_data.get('code', '')
                        err_type = err_data.get('type', '')
                        err_msg = err_data.get('message', '')
                    except Exception:
                        err_code, err_type, err_msg = '', '', ''

                    if err_code in ('insufficient_quota', 'credit_balance_exhausted') or err_type == 'insufficient_quota' or 'quota' in err_msg.lower() or 'credit' in err_msg.lower():
                        raise AIRateLimitError("OpenAI API quota/credit balance exhausted. Please add credits or update AI_API_KEY in .env.")

                    if attempt < retries:
                        time.sleep(backoff_seconds)
                        backoff_seconds *= 2.0
                        continue
                    raise AIRateLimitError("AI provider rate limit reached. Please try again shortly.")

                if response.status_code in (500, 502, 503, 504):
                    logger.warning("AI server error (%d) on attempt %d/%d", response.status_code, attempt, retries)
                    if attempt < retries:
                        time.sleep(backoff_seconds)
                        backoff_seconds *= 2.0
                        continue
                    raise AIProviderError(f"AI provider server error (HTTP {response.status_code}).")

                # Client errors (401, 403, 400, etc.)
                err_msg = response.text[:200]
                if response.status_code in (401, 403):
                    raise AIConfigurationError(f"AI provider authentication failed (HTTP {response.status_code}).")
                raise AIProviderError(f"AI provider error (HTTP {response.status_code}): {err_msg}")

            except requests.exceptions.Timeout as exc:
                logger.warning("AI provider timed out on attempt %d/%d: %s", attempt, retries, exc)
                if attempt < retries:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2.0
                    continue
                raise AITimeoutError(f"AI provider request timed out after {self.timeout}s.")
            except requests.exceptions.RequestException as exc:
                if attempt < retries:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2.0
                    continue
                raise AIProviderError(f"Network error contacting AI provider: {exc}")

    def classify(self, email_data: Dict[str, Any]) -> str:
        """
        Sends email metadata and sanitized body to the OpenAI-compatible endpoint.
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
        return self._chat_completion(messages, json_mode=True)

    def summarize(self, summary_payload: Dict[str, Any]) -> str:
        """
        Sends daily email stream and metadata to the OpenAI-compatible endpoint.
        Returns raw JSON string conforming to the daily summary schema.
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

    def analyze(self, analysis_payload: Dict[str, Any]) -> str:
        """
        Executes deep intelligence analysis of an email via OpenAI-compatible endpoint.
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

    def generate_reply(self, reply_payload: Dict[str, Any]) -> str:

        """
        Sends complete email context, thread history, attachments, and format preferences
        to the OpenAI-compatible endpoint.
        Returns generated plain text reply draft.
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

        max_tokens = getattr(settings, 'AI_REPLY_MAX_OUTPUT_TOKENS', getattr(settings, 'AI_REPLY_MAX_TOKENS', 1500))
        model_override = getattr(settings, 'AI_REPLY_MODEL', None) or self.model
        timeout_override = getattr(settings, 'AI_REPLY_TIMEOUT', None) or self.timeout

        return self._chat_completion(
            messages,
            json_mode=False,
            max_tokens=max_tokens,
            temperature=0.3,
            model=model_override,
            timeout=timeout_override
        )

