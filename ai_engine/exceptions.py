"""
AI Engine Custom Exception Hierarchy.
"""

class AIEngineError(Exception):
    """Base exception for all AI Engine related errors."""
    def __init__(self, message="An error occurred in the AI Engine.", details=None):
        super().__init__(message)
        self.message = message
        self.details = details


class AIConfigurationError(AIEngineError):
    """Raised when the AI provider or environment is missing required configuration."""
    pass


class AIValidationError(AIEngineError):
    """Raised when the AI provider response fails strict schema or bounds validation."""
    pass


class AIRateLimitError(AIEngineError):
    """Raised when the AI provider returns a rate limit (HTTP 429)."""
    pass


class AITimeoutError(AIEngineError):
    """Raised when the AI provider request times out."""
    pass


class AIProviderError(AIEngineError):
    """Raised when an upstream AI provider fails with a 5xx or connection error."""
    pass
