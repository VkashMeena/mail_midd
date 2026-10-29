"""
Gmail Send & Dispatch Service for Phase 7.
Handles sending reviewed and approved email replies via the official Gmail API (users.messages.send).
Ensures explicit send permissions, RFC 2822 formatting, threading preservation,
atomic double-send protection, and audit logging.
"""
import base64
import logging
from email.mime.text import MIMEText
from django.db import transaction
from django.utils import timezone

from emails.models import Email, EmailReply, ReplyAuditLog
from .models import GmailAccount
from .client import GmailClient
from .services import gmail_service
from .exceptions import (
    GmailIntegrationError,
    GmailPermissionError,
    GmailTokenError,
    GmailAPIError
)

logger = logging.getLogger(__name__)


class GmailSendService:
    """
    Service responsible for dispatching email replies through the Gmail API.
    """

    def send_reply(self, reply: EmailReply, user) -> EmailReply:
        """
        Sends an approved email reply through the user's connected Gmail account.

        Guarantees:
        - Strict user isolation (reply.user == user)
        - Never sends without human confirmation (called only from explicit user action)
        - Atomic state locking to prevent double sends
        - RFC 2822 In-Reply-To and References headers for email client thread threading
        - Gmail threadId preservation
        - Full audit trail logging
        """
        if reply.user != user:
            raise PermissionError("You cannot send an email reply belonging to another user.")

        # 1. Verify active connected Gmail account
        account = gmail_service.get_active_account(user)
        if not account:
            raise GmailIntegrationError("No active connected Gmail account found. Please connect your account in Settings.")

        # 2. Verify explicit send permission (opt-in scope)
        if not account.has_send_permission:
            raise GmailPermissionError(
                "Gmail sending permission is required. Please reconnect your Gmail account and grant sending permission."
            )

        # 3. Atomic double-send locking
        with transaction.atomic():
            locked_reply = EmailReply.objects.select_for_update().get(id=reply.id, user=user)
            if locked_reply.status in (EmailReply.STATUS_SENDING, EmailReply.STATUS_SENT):
                raise GmailIntegrationError("This reply is already being sent or has already been dispatched.")
            locked_reply.status = EmailReply.STATUS_SENDING
            locked_reply.save(update_fields=['status', 'updated_at'])

        # 4. Construct RFC 2822 MIME message
        try:
            content = locked_reply.final_text
            message = MIMEText(content, 'plain', 'utf-8')
            message['To'] = locked_reply.recipient
            message['From'] = account.email_address
            message['Subject'] = locked_reply.subject

            # Thread preservation
            thread_id = None
            if locked_reply.email:
                orig_email = locked_reply.email
                if orig_email.gmail_message_id:
                    msg_id_hdr = orig_email.gmail_message_id
                    if not msg_id_hdr.startswith('<'):
                        msg_id_hdr = f"<{msg_id_hdr}>"
                    message['In-Reply-To'] = msg_id_hdr
                    message['References'] = msg_id_hdr
                if orig_email.gmail_thread_id:
                    thread_id = orig_email.gmail_thread_id

            # Base64url encode for Gmail API
            raw_encoded = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            send_payload = {'raw': raw_encoded}
            if thread_id:
                send_payload['threadId'] = thread_id

            # 5. Dispatch via Gmail API
            client = GmailClient(account=account)
            service = client.build_service()
            sent_result = service.users().messages().send(userId='me', body=send_payload).execute()

            # 6. Update reply state to SENT
            locked_reply.status = EmailReply.STATUS_SENT
            locked_reply.gmail_message_id = sent_result.get('id', '')
            locked_reply.sent_at = timezone.now()
            locked_reply.error_message = ''
            locked_reply.save(update_fields=['status', 'gmail_message_id', 'sent_at', 'error_message', 'updated_at'])

            # 7. Audit log
            ReplyAuditLog.objects.create(
                user=user,
                email=locked_reply.email,
                reply=locked_reply,
                action=EmailReply.STATUS_SENT,
                details=f"Dispatched via Gmail API to {locked_reply.recipient} (Gmail ID: {locked_reply.gmail_message_id})"
            )
            logger.info("Successfully dispatched email reply id=%s for user %s", locked_reply.id, user)
            return locked_reply

        except Exception as exc:
            logger.exception("Failed to send email reply id=%s: %s", locked_reply.id, exc)
            locked_reply.status = EmailReply.STATUS_FAILED
            locked_reply.error_message = str(exc)[:500]
            locked_reply.save(update_fields=['status', 'error_message', 'updated_at'])

            ReplyAuditLog.objects.create(
                user=user,
                email=locked_reply.email,
                reply=locked_reply,
                action=EmailReply.STATUS_FAILED,
                details=f"Send failed: {str(exc)[:250]}"
            )
            raise


send_service = GmailSendService()
