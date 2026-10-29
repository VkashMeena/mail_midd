"""
AI Provider package exports, hybrid fallback orchestrator, and factory functions.
Supports Groq LPU inference, OpenAI, and automatic failover.
"""
import logging
from typing import Dict, Any, Optional
from django.conf import settings

from .base import BaseAIProvider
from .openai_provider import OpenAICompatibleProvider
from .groq_provider import GroqProvider
from ..exceptions import AIRateLimitError, AIConfigurationError, AIProviderError

logger = logging.getLogger(__name__)

# Alias for backwards compatibility with Phase 1
AIProvider = BaseAIProvider


class HybridFallbackProvider(BaseAIProvider):
    """
    Intelligent provider wrapper that automatically fails over between
    OpenAI and Groq if quota or rate-limit errors occur.
    """

    def __init__(self, primary: BaseAIProvider, secondary: Optional[BaseAIProvider] = None):
        self.primary = primary
        self.secondary = secondary

    def _execute_with_fallback(self, method_name: str, *args, **kwargs) -> Any:
        try:
            method = getattr(self.primary, method_name)
            return method(*args, **kwargs)
        except (AIRateLimitError, AIConfigurationError) as exc:
            if self.secondary and self.secondary.is_configured():
                logger.info(
                    "Primary AI provider (%s) encountered %s; auto-failing over to %s",
                    self.primary.__class__.__name__, exc, self.secondary.__class__.__name__
                )
                try:
                    sec_method = getattr(self.secondary, method_name)
                    return sec_method(*args, **kwargs)
                except Exception as sec_exc:
                    logger.error(
                        "Secondary AI provider (%s) also failed after failover: %s",
                        self.secondary.__class__.__name__, sec_exc
                    )
                    if isinstance(self.primary, GroqProvider):
                        raise AIProviderError(
                            f"Groq inference failed ({exc}), and OpenAI failover failed ({sec_exc}). "
                            f"Please verify your GROQ_API_KEY in Settings."
                        )
                    raise
            raise

    def classify(self, email_data: Dict[str, Any]) -> str:
        return self._execute_with_fallback('classify', email_data)

    def analyze(self, analysis_payload: Dict[str, Any]) -> str:
        return self._execute_with_fallback('analyze', analysis_payload)

    def summarize(self, summary_payload: Dict[str, Any]) -> str:
        return self._execute_with_fallback('summarize', summary_payload)

    def generate_reply(self, reply_payload: Dict[str, Any]) -> str:
        return self._execute_with_fallback('generate_reply', reply_payload)


def get_ai_provider(provider_name: Optional[str] = None) -> BaseAIProvider:
    """
    Factory function returning the configured AI Provider instance.
    Supports 'groq', 'openai', or automatic hybrid failover.
    """
    target = (provider_name or getattr(settings, 'AI_PROVIDER', 'groq')).lower()

    groq_prov = GroqProvider()
    openai_prov = OpenAICompatibleProvider()

    if target == 'groq':
        if not groq_prov.is_configured():
            return groq_prov
        if openai_prov.is_configured():
            return HybridFallbackProvider(primary=groq_prov, secondary=openai_prov)
        return groq_prov

    if target in ('openai', 'openai_compatible', 'azure', 'ollama', 'openrouter'):
        # If Groq is configured and OpenAI is not, prefer Groq
        if groq_prov.is_configured() and not openai_prov.is_configured():
            return groq_prov
        # If Groq is configured, wrap with fallback to Groq
        if groq_prov.is_configured():
            return HybridFallbackProvider(primary=openai_prov, secondary=groq_prov)
        return openai_prov

    # Default fallback
    if groq_prov.is_configured():
        return groq_prov
    return openai_prov


__all__ = [
    'BaseAIProvider',
    'AIProvider',
    'OpenAICompatibleProvider',
    'GroqProvider',
    'HybridFallbackProvider',
    'get_ai_provider',
]
