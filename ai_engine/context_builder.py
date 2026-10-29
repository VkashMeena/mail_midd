"""
Email Context Builder for AI Smart Mail Manager.
Extracts and synthesizes comprehensive context from an email for context-aware
LLM reply generation. Handles HTML-to-text extraction, smart long-email preservation,
Gmail conversation thread history, attachment summaries, and recipient perspective.
"""
import re
import html
import logging
from html.parser import HTMLParser
from typing import Dict, Any, List, Optional
from django.conf import settings
from django.utils import timezone

from emails.models import Email, EmailAttachment

logger = logging.getLogger(__name__)


class _HTMLToTextParser(HTMLParser):
    """
    Lightweight, safe HTML to plain text extractor.
    Strips scripts, styles, converts block elements to newlines, and collapses whitespace.
    """
    def __init__(self):
        super().__init__()
        self._pieces = []
        self._ignore = False

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower in ('script', 'style', 'head', 'title', 'meta', 'noscript'):
            self._ignore = True
        elif tag_lower in ('br', 'p', 'div', 'tr', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            self._pieces.append('\n')

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower in ('script', 'style', 'head', 'title', 'meta', 'noscript'):
            self._ignore = False
        elif tag_lower in ('p', 'div', 'tr', 'li'):
            self._pieces.append('\n')

    def handle_data(self, data):
        if not self._ignore:
            self._pieces.append(data)

    def get_text(self) -> str:
        raw = "".join(self._pieces)
        raw = html.unescape(raw)
        lines = [line.strip() for line in raw.split('\n')]
        cleaned = []
        blank = False
        for line in lines:
            if line:
                cleaned.append(line)
                blank = False
            elif not blank:
                cleaned.append('')
                blank = True
        return "\n".join(cleaned).strip()


def html_to_plain_text(html_content: str) -> str:
    """Safely converts an HTML string to clean, readable plain text."""
    if not html_content:
        return ""
    try:
        parser = _HTMLToTextParser()
        parser.feed(html_content)
        return parser.get_text()
    except Exception as exc:
        logger.warning("Error parsing HTML to text: %s. Using regex fallback.", exc)
        cleaned = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r'<[^>]+>', ' ', cleaned)
        return html.unescape(re.sub(r'\s+', ' ', cleaned)).strip()


def extract_clean_email_text(email_or_text: Any, max_chars: Optional[int] = None) -> str:
    """
    Extracts the most complete, safe plain-text representation of an email body.
    Supports either an Email instance or a raw string.
    Checks body_text, body_html, and snippet when Email is provided.
    Implements smart preservation for long emails: retains beginning and end (where
    key instructions, questions, deadlines, and sign-offs exist) rather than blunt truncation.
    """
    if max_chars is None:
        max_chars = getattr(settings, 'AI_REPLY_MAX_EMAIL_CHARS', 30000)

    if isinstance(email_or_text, str):
        full_text = email_or_text.strip()
    elif email_or_text is None:
        full_text = ""
    else:
        plain_body = (getattr(email_or_text, 'body_text', '') or '').strip()
        html_body = (getattr(email_or_text, 'body_html', '') or '').strip()

        extracted_html_text = html_to_plain_text(html_body) if html_body else ""

        # Choose the representation with richer content
        if len(extracted_html_text) > len(plain_body) + 50:
            full_text = extracted_html_text
        elif plain_body:
            full_text = plain_body
        elif extracted_html_text:
            full_text = extracted_html_text
        else:
            full_text = (getattr(email_or_text, 'snippet', '') or '').strip()

    if not full_text:
        return "(No email body content available)"

    # Smart preservation for emails exceeding max_chars
    if len(full_text) > max_chars:
        head_len = int(max_chars * 0.65)
        tail_len = int(max_chars * 0.35)
        omitted_len = len(full_text) - (head_len + tail_len)
        full_text = (
            f"{full_text[:head_len]}\n\n"
            f"[... Content omitted for length: {omitted_len:,} characters preserved/summarized ...]\n\n"
            f"{full_text[-tail_len:]}"
        )

    return full_text


def get_thread_context(email: Email, user=None, max_prior_messages: int = 5) -> str:
    """
    Retrieves previous relevant messages in the same Gmail thread if available.
    Returns chronologically ordered conversation summary stubs.
    """
    effective_user = user or getattr(email, 'user', None)
    if not email.gmail_thread_id or not effective_user:
        return "None (Single message or no previous thread history available)."

    try:
        prior_emails = Email.objects.filter(
            user=effective_user,
            gmail_thread_id=email.gmail_thread_id
        ).exclude(
            id=email.id
        ).order_by('received_at')[:max_prior_messages]

        if not prior_emails.exists():
            return "None (First message in this conversation thread)."

        thread_lines = []
        for em in prior_emails:
            date_str = em.received_at.strftime('%Y-%m-%d %H:%M') if em.received_at else 'Unknown date'
            sender = em.effective_sender_name or em.sender_name or em.sender_email
            # Short preview of prior message
            body_preview = (em.snippet or extract_clean_email_text(em, max_chars=300))[:250].strip()
            body_preview = body_preview.replace('\n', ' ')
            thread_lines.append(f"- [{date_str}] From {sender} <{em.sender_email}>: \"{body_preview}\"")

        return "\n".join(thread_lines)

    except Exception as exc:
        logger.warning("Error fetching thread context for email id=%s: %s", email.id, exc)
        return "None (Thread context lookup unavailable)."


def get_attachments_summary(email: Email) -> str:
    """
    Safely summarizes attached files (filenames, sizes, types).
    Explicitly instructs that binary attachment contents are not analyzed.
    """
    try:
        attachments = email.attachments.all()
        if not attachments.exists():
            return "No attachments."

        items = []
        for att in attachments:
            items.append(f"{att.filename} ({att.size_formatted}, {att.mime_type or 'unknown'}, binary file not extracted into prompt)")

        summary = ", ".join(items)
        return f"{summary}\n(Note: Binary attachment files cannot be read directly. Do not invent attachment content.)"
    except Exception as exc:
        logger.warning("Error summarizing attachments for email id=%s: %s", email.id, exc)
        return "None."


def build_email_reply_context(
    email: Email,
    user=None,
    reply_length: str = "Medium",
    reply_tone: str = "Professional",
    custom_instruction: str = "",
    instruction: str = "",
    **kwargs
) -> Dict[str, Any]:
    """
    Builds the complete dictionary of email context and metadata
    for context-aware LLM reply generation.
    """
    effective_user = user or getattr(email, 'user', None)
    instruction_text = custom_instruction or instruction or ""

    # Recipient perspective (The user who is replying)
    if effective_user:
        user_name = getattr(effective_user, 'get_full_name', lambda: '')() or getattr(effective_user, 'first_name', '') or getattr(effective_user, 'username', 'Recipient')
        user_email = getattr(effective_user, 'email', '') or getattr(email, 'recipient_email', '') or 'user@example.com'
    else:
        user_name = "Recipient"
        user_email = getattr(email, 'recipient_email', '') or 'user@example.com'

    sender_display = getattr(email, 'effective_sender_name', '') or getattr(email, 'sender_name', '') or getattr(email, 'sender_email', '')
    clean_body = extract_clean_email_text(email)
    thread_history = get_thread_context(email, effective_user)
    attachments_info = get_attachments_summary(email)

    received_str = email.received_at.strftime('%Y-%m-%d %H:%M') if email.received_at else 'Recent'

    # Format combination label, e.g. "Medium + Professional"
    format_label = f"{reply_length} + {reply_tone}"

    return {
        'sender_name': sender_display,
        'sender_email': email.sender_email,
        'recipient_name': user_name,
        'recipient_email': user_email,
        'cc': getattr(email, 'cc', '') or 'None',
        'subject': email.subject or '(No Subject)',
        'received_at': received_str,
        'category': getattr(email, 'effective_category', 'General'),
        'priority': getattr(email, 'effective_priority', 'Medium'),
        'is_important': getattr(email, 'effective_is_important', False),
        'ai_objective': getattr(email, 'ai_objective', '') or 'None',
        'clean_body': clean_body,
        'body_text': clean_body,
        'thread_context': thread_history,
        'attachments_info': attachments_info,
        'reply_length': reply_length,
        'reply_tone': reply_tone,
        'format_label': format_label,
        'user_instruction': instruction_text,
        'custom_instruction': instruction_text.strip() if instruction_text else 'None',
    }
