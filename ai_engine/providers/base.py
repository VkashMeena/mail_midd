"""
Abstract base class for AI/LLM providers.
Decouples Django logic from specific LLM provider implementations.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseAIProvider(ABC):
    """
    Abstract Base Class for AI providers.
    """

    @abstractmethod
    def classify(self, email_data: Dict[str, Any]) -> str:
        """
        Executes classification request and returns raw LLM response text.
        Must raise appropriate AIEngineError subclasses on failure.
        """
        pass

    @abstractmethod
    def summarize(self, summary_payload: Dict[str, Any]) -> str:
        """
        Executes daily summary request and returns raw LLM response text (JSON string).
        Must raise appropriate AIEngineError subclasses on failure.
        """
        pass

    @abstractmethod
    def generate_reply(self, reply_payload: Dict[str, Any]) -> str:
        """
        Executes reply generation request and returns generated plain text reply.
        Must raise appropriate AIEngineError subclasses on failure.
        """
        pass

    def analyze(self, analysis_payload: Dict[str, Any]) -> str:
        """
        Executes comprehensive email intelligence analysis and returns structured JSON text.
        Subclasses can implement specifically or use default.
        """
        raise NotImplementedError("Analyze method must be implemented by the provider.")

