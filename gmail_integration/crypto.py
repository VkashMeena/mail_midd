import base64
import hashlib
import logging
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

def _get_fernet_key() -> bytes:
    """
    Derives a valid 32-byte urlsafe base64-encoded key for Fernet.
    Uses GMAIL_TOKEN_ENCRYPTION_KEY if set, with a fallback to SECRET_KEY.
    """
    raw_key = getattr(settings, 'GMAIL_TOKEN_ENCRYPTION_KEY', '') or getattr(settings, 'SECRET_KEY', 'default-dev-secret-key-32-chars')
    # Use SHA-256 digest to get exactly 32 bytes, then urlsafe base64 encode
    digest = hashlib.sha256(raw_key.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest)

def encrypt_token(plaintext: str) -> str:
    """
    Encrypts a token string at rest. Returns base64 ciphertext string.
    If plaintext is empty or None, returns empty string.
    """
    if not plaintext:
        return ''
    try:
        fernet = Fernet(_get_fernet_key())
        encrypted_bytes = fernet.encrypt(plaintext.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')
    except Exception as exc:
        logger.error("Token encryption failed: %s", exc)
        raise

def decrypt_token(ciphertext: str) -> str:
    """
    Decrypts a token string from storage into plaintext in memory.
    If ciphertext is empty or None, returns empty string.
    Includes self-healing for legacy double-encrypted tokens.
    """
    if not ciphertext:
        return ''
    try:
        fernet = Fernet(_get_fernet_key())
        decrypted_bytes = fernet.decrypt(ciphertext.encode('utf-8'))
        result = decrypted_bytes.decode('utf-8')
        # Self-healing: if decrypted string is still a Fernet ciphertext, decrypt the second layer
        if result.startswith('gAAAAA'):
            try:
                result = fernet.decrypt(result.encode('utf-8')).decode('utf-8')
            except Exception:
                pass
        return result
    except InvalidToken:
        logger.error("Decryption failed: Token is corrupted or encryption key changed.")
        return ''
    except Exception as exc:
        logger.error("Token decryption failed: %s", exc)
        return ''
