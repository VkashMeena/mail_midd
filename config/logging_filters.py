"""
Logging filters for security hardening.
Ensures sensitive tokens, passwords, and API credentials are never leaked in logs.
"""
import re
import logging


class SensitiveDataFilter(logging.Filter):
    """
    Scrubs sensitive tokens, authorization keys, API secrets, and passwords from log records.
    """

    PATTERNS = [
        # Bearer tokens
        (re.compile(r'(Bearer\s+)[A-Za-z0-9_\-\.]{8,}', re.IGNORECASE), r'\1[REDACTED]'),
        # Google OAuth Access Tokens (ya29.*)
        (re.compile(r'ya29\.[A-Za-z0-9_\-]{15,}', re.IGNORECASE), r'ya29.[REDACTED]'),
        # OpenAI API Keys (sk-*)
        (re.compile(r'sk-[A-Za-z0-9_\-]{20,}', re.IGNORECASE), r'sk-[REDACTED]'),
        # JSON or query param style keys: password, secret, token, api_key
        (re.compile(r'(["\']?(?:password|client_secret|token|api_key|refresh_token)["\']?\s*[:=]\s*["\'])([^"\',\s&]+)(["\']?)', re.IGNORECASE), r'\1[REDACTED]\3'),
    ]

    def _sanitize(self, val):
        if not isinstance(val, str):
            return val
        sanitized = val
        for pattern, replacement in self.PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._sanitize(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._sanitize(v) for k, v in record.args.items()}
            elif isinstance(record.args, (list, tuple)):
                record.args = tuple(self._sanitize(arg) for arg in record.args)

        return True
