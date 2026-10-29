import base64
import email.utils
import logging
import os
import time
from datetime import datetime
from django.utils import timezone
from django.db import transaction
from django.conf import settings
import re
import bleach
from bleach.css_sanitizer import CSSSanitizer, ALLOWED_CSS_PROPERTIES
from googleapiclient.errors import HttpError

from emails.models import Email, EmailAttachment, EmailCategory, EmailPriority, EmailImportance
from .models import GmailAccount, GmailSyncLog
from .client import GmailClient
from .exceptions import (
    GmailIntegrationError,
    GmailTokenError,
    GmailAPIError
)

logger = logging.getLogger(__name__)

# Allowed tags & attributes for safe HTML email rendering in isolated sandboxed iframe
ALLOWED_HTML_TAGS = [
    'a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li', 'ol',
    'strong', 'ul', 'p', 'br', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'img', 'hr', 'pre',
    'style', 'font', 'center', 'u', 's', 'strike', 'sub', 'sup'
]
ALLOWED_HTML_ATTRIBUTES = {
    'a': ['href', 'title', 'target', 'rel', 'style', 'class'],
    'img': ['src', 'alt', 'title', 'width', 'height', 'style', 'class', 'border', 'align'],
    'table': ['width', 'height', 'border', 'cellpadding', 'cellspacing', 'bgcolor', 'background', 'style', 'class', 'align', 'valign'],
    'td': ['width', 'height', 'colspan', 'rowspan', 'bgcolor', 'background', 'style', 'class', 'align', 'valign'],
    'th': ['width', 'height', 'colspan', 'rowspan', 'bgcolor', 'background', 'style', 'class', 'align', 'valign'],
    'tr': ['bgcolor', 'background', 'style', 'class', 'align', 'valign'],
    'font': ['color', 'size', 'face'],
    '*': ['style', 'class', 'align', 'valign', 'dir', 'id', 'width', 'height']
}
SAFE_CSS_PROPERTIES = list(ALLOWED_CSS_PROPERTIES) + [
    'background', 'background-color', 'background-image', 'background-position',
    'background-repeat', 'background-size', 'min-width', 'max-width', 'min-height',
    'max-height', 'table-layout', 'border-spacing', 'vertical-align', 'line-height',
    'text-decoration', 'box-sizing', 'mso-table-lspace', 'mso-table-rspace',
    '-webkit-text-size-adjust', '-ms-text-size-adjust'
]
EMAIL_CSS_SANITIZER = CSSSanitizer(allowed_css_properties=SAFE_CSS_PROPERTIES)


def decode_base64url(data_str: str) -> str:
    """
    Decodes base64url encoded data with automatic padding handling.
    Returns decoded UTF-8 string, or empty string on failure.
    """
    if not data_str:
        return ''
    try:
        # Standardize URL-safe base64 padding
        padding = len(data_str) % 4
        if padding:
            data_str += '=' * (4 - padding)
        raw_bytes = base64.b64decode(data_str.encode('ascii'), altchars=b'-_', validate=True)
        return raw_bytes.decode('utf-8', errors='replace')
    except Exception as exc:
        logger.debug("MIME base64url decode error (ignored): %s", exc)
        return ''


def sanitize_email_html(html_content: str) -> str:
    """
    Sanitizes email HTML to prevent script injection (XSS) while preserving
    safe layout, typography, links, and tables.
    """
    if not html_content:
        return ''
    try:
        # Strip script tags and content completely before bleach
        clean_input = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        cleaned = bleach.clean(
            clean_input,
            tags=ALLOWED_HTML_TAGS,
            attributes=ALLOWED_HTML_ATTRIBUTES,
            css_sanitizer=EMAIL_CSS_SANITIZER,
            strip=True
        )
        from emails.utils import clean_leaked_css_from_html
        return clean_leaked_css_from_html(cleaned)
    except Exception as exc:
        logger.warning("Bleach HTML sanitization failed: %s", exc)
        from emails.utils import clean_leaked_css_from_html
        return clean_leaked_css_from_html(html_content)
def _is_celery_broker_reachable() -> bool:
    """Non-blocking socket check to verify if Celery/Redis broker is active before enqueueing."""
    import socket
    from urllib.parse import urlparse
    broker_url = getattr(settings, 'CELERY_BROKER_URL', '') or ''
    if not broker_url or not broker_url.startswith(('redis://', 'rediss://')):
        return False
    try:
        parsed = urlparse(broker_url)
        host = parsed.hostname or '127.0.0.1'
        port = parsed.port or 6379
        with socket.create_connection((host, port), timeout=0.05):
            return True
    except OSError:
        return False


class GmailSyncService:
    """
    Service responsible for pulling real Gmail correspondence, extracting MIME content,
    sanitizing bodies, mapping labels, and persisting records idempotently into the database.
    """

    def __init__(self, initial_sync_limit=None, batch_size=None):
        self.initial_sync_limit = initial_sync_limit or getattr(settings, 'GMAIL_INITIAL_SYNC_LIMIT', int(os.environ.get('GMAIL_INITIAL_SYNC_LIMIT', 100)))
        self.batch_size = batch_size or getattr(settings, 'GMAIL_SYNC_BATCH_SIZE', int(os.environ.get('GMAIL_SYNC_BATCH_SIZE', 25)))

    def sync_gmail_account(self, account: GmailAccount, query='label:INBOX') -> dict:
        """
        Synchronizes Gmail messages for a connected account.
        Returns summary statistics dictionary:
        {'fetched': X, 'created': Y, 'updated': Z, 'failed': W, 'skipped': S}
        """
        if not account.is_connected:
            raise GmailIntegrationError("Cannot synchronize a disconnected Gmail account.")

        sync_log = GmailSyncLog.objects.create(
            gmail_account=account,
            status='RUNNING',
            started_at=timezone.now()
        )

        stats = {
            'fetched': 0,
            'created': 0,
            'updated': 0,
            'failed': 0,
            'skipped': 0
        }

        try:
            client = GmailClient(account=account)
            # Ensure valid credentials (refreshes expired access token automatically)
            client.get_credentials()
            service = client.build_service()

            messages_to_fetch = self._fetch_message_list(service, query, self.initial_sync_limit, self.batch_size)
            stats['fetched'] = len(messages_to_fetch)
            sync_log.fetched_count = stats['fetched']
            sync_log.save(update_fields=['fetched_count'])

            logger.info("Starting synchronization of %s messages for %s", len(messages_to_fetch), account.email_address)

            for msg_meta in messages_to_fetch:
                msg_id = msg_meta.get('id')
                if not msg_id:
                    stats['skipped'] += 1
                    continue

                try:
                    msg_data = self._fetch_message_detail_with_retry(service, msg_id)
                    if not msg_data:
                        stats['failed'] += 1
                        continue

                    parsed_email = self.parse_message_payload(msg_data, account)
                    is_new = self._save_or_update_email(account, parsed_email)
                    if is_new:
                        stats['created'] += 1
                    else:
                        stats['updated'] += 1
                except Exception as item_exc:
                    logger.error("Failed to parse and save message id=%s: %s", msg_id, item_exc)
                    stats['failed'] += 1

            # Update account and sync log
            now = timezone.now()
            account.last_synced_at = now
            account.save(update_fields=['last_synced_at'])

            sync_log.status = 'COMPLETED'
            sync_log.completed_at = now
            sync_log.created_count = stats['created']
            sync_log.updated_count = stats['updated']
            sync_log.failed_count = stats['failed']
            sync_log.save()

            logger.info("Gmail sync completed for %s: %s", account.email_address, stats)
            return stats

        except GmailTokenError as exc:
            sync_log.status = 'FAILED'
            sync_log.completed_at = timezone.now()
            sync_log.error_message = str(exc)
            sync_log.save()
            raise

        except Exception as exc:
            logger.exception("Gmail sync failed for account %s: %s", account.email_address, exc)
            sync_log.status = 'FAILED'
            sync_log.completed_at = timezone.now()
            sync_log.error_message = str(exc)[:500]
            sync_log.save()
            raise GmailAPIError("Unable to synchronize your Gmail account right now.")

    def _fetch_message_list(self, service, query: str, max_messages: int, batch_size: int) -> list:
        """
        Retrieves message stubs (id and threadId) using nextPageToken pagination.
        """
        messages = []
        page_token = None

        while len(messages) < max_messages:
            fetch_size = min(batch_size, max_messages - len(messages))
            params = {
                'userId': 'me',
                'q': query,
                'maxResults': fetch_size,
            }
            if page_token:
                params['pageToken'] = page_token

            try:
                response = service.users().messages().list(**params).execute()
                page_messages = response.get('messages', [])
                if not page_messages:
                    break
                messages.extend(page_messages)
                page_token = response.get('nextPageToken')
                if not page_token:
                    break
            except HttpError as exc:
                logger.error("Gmail list API returned HttpError: %s", exc)
                if exc.resp.status in (401, 403):
                    raise GmailTokenError("Your Gmail connection needs to be renewed.")
                raise GmailAPIError("Failed to list messages from Gmail.")
            except Exception as exc:
                logger.error("Error calling Gmail message list: %s", exc)
                raise GmailAPIError("Error communicating with Gmail.")

        return messages

    def _fetch_message_detail_with_retry(self, service, message_id: str, max_retries=2) -> dict:
        """
        Fetches full message detail with exponential backoff on transient errors.
        """
        for attempt in range(max_retries + 1):
            try:
                return service.users().messages().get(
                    userId='me',
                    id=message_id,
                    format='full'
                ).execute()
            except HttpError as exc:
                if exc.resp.status in (429, 500, 503) and attempt < max_retries:
                    sleep_time = (2 ** attempt) * 0.5
                    logger.warning("Transient error %s for msg %s, retrying in %ss", exc.resp.status, message_id, sleep_time)
                    time.sleep(sleep_time)
                else:
                    logger.error("Failed to retrieve message detail %s: %s", message_id, exc)
                    return {}
            except Exception as exc:
                logger.error("Unexpected error retrieving message %s: %s", message_id, exc)
                return {}
        return {}

    def parse_message_payload(self, msg_data: dict, account: GmailAccount) -> dict:
        """
        Recursively parses Gmail message payload into a normalized dictionary.
        Extracts headers, sender, date, snippet, plain-text body, sanitized HTML body,
        labels, and attachment metadata.
        """
        msg_id = msg_data.get('id', '')
        thread_id = msg_data.get('threadId', '')
        history_id = msg_data.get('historyId', '')
        labels = msg_data.get('labelIds', [])
        snippet = msg_data.get('snippet', '')
        internal_date_raw = msg_data.get('internalDate')

        payload = msg_data.get('payload', {})
        headers_list = payload.get('headers', [])

        # Build case-insensitive header map
        headers = {}
        for h in headers_list:
            name = h.get('name', '').lower()
            val = h.get('value', '')
            headers[name] = val

        # 1. Subject extraction
        subject = headers.get('subject', '').strip() or '(No Subject)'

        # 2. Sender extraction
        from_header = headers.get('from', '')
        name, addr = email.utils.parseaddr(from_header)
        sender_email = addr.strip().lower() if addr else 'unknown@example.com'
        sender_name = name.strip() if name.strip() else sender_email

        # 3. Recipients extraction
        to_header = headers.get('to', '')
        cc_header = headers.get('cc', '')
        bcc_header = headers.get('bcc', '')

        _, to_addr = email.utils.parseaddr(to_header)
        recipient_email = to_addr.strip().lower() if to_addr else account.email_address

        # 4. Date parsing
        received_at = None
        if internal_date_raw:
            try:
                ms = int(internal_date_raw)
                received_at = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
            except Exception:
                pass

        if not received_at and 'date' in headers:
            try:
                parsed_dt = email.utils.parsedate_to_datetime(headers['date'])
                if timezone.is_naive(parsed_dt):
                    parsed_dt = timezone.make_aware(parsed_dt, timezone.utc)
                received_at = parsed_dt
            except Exception:
                pass

        if not received_at:
            received_at = timezone.now()

        # 5. Recursive MIME traversal for body and attachments
        body_text, raw_html, attachments = self._extract_mime_content(payload)

        # 6. HTML sanitization
        sanitized_html = sanitize_email_html(raw_html) if raw_html else ''

        # Fallback body_text if only HTML was present
        if not body_text and raw_html:
            clean_for_text = re.sub(r'<style[^>]*>.*?</style>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
            clean_for_text = re.sub(r'<script[^>]*>.*?</script>', '', clean_for_text, flags=re.DOTALL | re.IGNORECASE)
            body_text = bleach.clean(clean_for_text, tags=[], strip=True).strip()

        from emails.utils import clean_leaked_css_from_text
        if body_text:
            body_text = clean_leaked_css_from_text(body_text)

        # 7. Label Mapping (UNREAD -> is_read, STARRED -> is_starred, IMPORTANT -> gmail_is_important)
        is_read = 'UNREAD' not in labels
        is_starred = 'STARRED' in labels
        gmail_is_important = 'IMPORTANT' in labels
        has_attachments = bool(attachments) or ('has_attachments' in labels)

        return {
            'gmail_message_id': msg_id,
            'gmail_thread_id': thread_id,
            'gmail_history_id': history_id,
            'sender_name': sender_name[:255],
            'sender_email': sender_email[:254],
            'recipient_email': recipient_email[:254],
            'cc': cc_header,
            'bcc': bcc_header,
            'subject': subject[:500],
            'snippet': snippet[:300],
            'body_text': body_text,
            'body_html': sanitized_html,
            'received_at': received_at,
            'is_read': is_read,
            'is_starred': is_starred,
            'gmail_is_important': gmail_is_important,
            'has_attachments': has_attachments,
            'gmail_labels': ','.join(labels),
            'attachments': attachments,
        }

    def _extract_mime_content(self, payload: dict) -> tuple:
        """
        Traverses multipart MIME trees and extracts text, html, and attachments.
        """
        body_text = ''
        body_html = ''
        attachments = []

        def walk(part):
            nonlocal body_text, body_html
            mime_type = part.get('mimeType', '').lower()
            filename = part.get('filename', '')
            part_body = part.get('body', {})
            attachment_id = part_body.get('attachmentId')
            size = part_body.get('size', 0)

            # Detect attachment
            if filename or attachment_id:
                attachments.append({
                    'filename': filename or 'attachment',
                    'mime_type': mime_type or 'application/octet-stream',
                    'size': size,
                    'gmail_attachment_id': attachment_id or ''
                })

            # Detect text/plain and text/html bodies
            data_b64 = part_body.get('data')
            if data_b64:
                decoded = decode_base64url(data_b64)
                if mime_type == 'text/plain' and not body_text:
                    body_text = decoded
                elif mime_type == 'text/html' and not body_html:
                    body_html = decoded

            # Recurse into subparts
            for subpart in part.get('parts', []):
                walk(subpart)

        walk(payload)
        return body_text, body_html, attachments

    def _save_or_update_email(self, account: GmailAccount, data: dict) -> bool:
        """
        Persists email and its attachments into the database idempotently.
        Returns True if a new record was created, False if existing was updated.
        """
        user = account.user
        msg_id = data['gmail_message_id']
        attachments = data.pop('attachments', [])

        with transaction.atomic():
            email_obj, created = Email.objects.update_or_create(
                gmail_account=account,
                gmail_message_id=msg_id,
                defaults={
                    'user': user,
                    'gmail_thread_id': data['gmail_thread_id'],
                    'gmail_history_id': data['gmail_history_id'],
                    'sender_name': data['sender_name'],
                    'sender_email': data['sender_email'],
                    'recipient_email': data['recipient_email'],
                    'cc': data['cc'],
                    'bcc': data['bcc'],
                    'subject': data['subject'],
                    'snippet': data['snippet'],
                    'body_text': data['body_text'],
                    'body_html': data['body_html'],
                    'received_at': data['received_at'],
                    'is_read': data['is_read'],
                    'is_starred': data['is_starred'],
                    'gmail_is_important': data['gmail_is_important'],
                    'has_attachments': data['has_attachments'],
                    'gmail_labels': data['gmail_labels'],
                    # Phase 4 keeps category unassigned or default until Phase 5 AI classifier runs
                    'is_demo': False,
                }
            )

            # Persist attachment metadata
            if attachments:
                for att in attachments:
                    EmailAttachment.objects.update_or_create(
                        email=email_obj,
                        filename=att['filename'][:255],
                        defaults={
                            'gmail_attachment_id': att['gmail_attachment_id'],
                            'mime_type': att['mime_type'][:100],
                            'size': att['size'],
                        }
                    )

        if created:
            # 1. Trigger AI Classification for newly synchronized email
            if getattr(settings, 'AI_CLASSIFICATION_ENABLED', True):
                classified_async = False
                if _is_celery_broker_reachable():
                    try:
                        from ai_engine.tasks import process_email_classification
                        process_email_classification.delay(email_obj.id)
                        classified_async = True
                    except Exception as celery_err:
                        logger.debug("Celery task dispatch skipped for email id=%s (%s), using synchronous processing.", email_obj.id, celery_err)

                if not classified_async:
                    try:
                        from ai_engine.classifier import EmailClassifier
                        classifier = EmailClassifier()
                        classifier.classify_email(email_obj)
                    except Exception as ai_err:
                        logger.warning("AI classification during sync failed for email id=%s: %s", email_obj.id, ai_err)

            # 2. Check and trigger Important Notification (Priority Sender Rule or AI Important)
            try:
                from notifications.services import create_important_notification
                email_obj.refresh_from_db()
                create_important_notification(email_obj)
            except Exception as notif_err:
                logger.debug("Notification hook error during email creation (ignored): %s", notif_err)

        return created

    def sync_account(self, account: GmailAccount, query: str = '') -> dict:
        """Alias for sync_gmail_account for task and service compatibility."""
        return self.sync_gmail_account(account, query=query)


sync_service = GmailSyncService()
