"""
AI Engine Central Coordination Service.
Provides uniform service access layer for views and background workers.
"""
import logging
from typing import List, Dict, Any
from django.conf import settings
from django.db.models import Count, Q

from emails.models import Email, AIStatus
from ai_engine.constants import EMAIL_CATEGORIES, CATEGORY_META
from .classifier import EmailClassifier
from .summarizer import EmailSummarizer
from .reply_generator import EmailReplyGenerator
from .analyzer import EmailAnalyzer, email_analyzer
from .schemas import AIClassificationResult

logger = logging.getLogger(__name__)


class AIService:
    def __init__(self, classifier: EmailClassifier = None):
        self.classifier = classifier or EmailClassifier()
        self.summarizer = EmailSummarizer()
        self.reply_generator = EmailReplyGenerator()
        self.analyzer = EmailAnalyzer()


    def get_batch_size(self) -> int:
        return getattr(settings, 'AI_BATCH_SIZE', 10)

    def classify_email(self, email: Email, force: bool = False) -> AIClassificationResult:
        """
        Classifies a single email using the configured classifier.
        """
        return self.classifier.classify_email(email, force=force)

    def classify_batch(self, emails: List[Email], force: bool = False) -> Dict[str, Any]:
        """
        Classifies a bounded list of emails.
        Returns a dict summarizing results:
        {'total': X, 'completed': Y, 'failed': Z, 'skipped': S, 'errors': [...]}
        """
        batch_size = self.get_batch_size()
        to_process = list(emails)[:batch_size]

        stats = {
            'total': len(to_process),
            'completed': 0,
            'failed': 0,
            'skipped': 0,
            'errors': []
        }

        for email in to_process:
            if not force and email.ai_status == AIStatus.COMPLETED and email.ai_category:
                stats['skipped'] += 1
                continue

            try:
                self.classify_email(email, force=force)
                stats['completed'] += 1
            except Exception as exc:
                stats['failed'] += 1
                stats['errors'].append({
                    'email_id': email.id,
                    'subject': email.subject,
                    'error': str(exc)[:200]
                })

        return stats

    def classify_unprocessed(self, user, limit: int = None) -> Dict[str, Any]:
        """
        Finds pending or unanalyzed emails for the given user and classifies them in a batch.
        """
        batch_limit = limit or self.get_batch_size()
        unprocessed = Email.objects.filter(
            user=user
        ).filter(
            Q(ai_status=AIStatus.PENDING) | Q(ai_status__isnull=True)
        ).order_by('-received_at')[:batch_limit]

        return self.classify_batch(unprocessed, force=False)

    def retry_failed(self, user, limit: int = None) -> Dict[str, Any]:
        """
        Retries emails for the user that previously had ai_status = FAILED.
        """
        batch_limit = limit or self.get_batch_size()
        failed = Email.objects.filter(
            user=user,
            ai_status=AIStatus.FAILED
        ).order_by('-received_at')[:batch_limit]

        return self.classify_batch(failed, force=True)

    def get_ai_processing_stats(self, user) -> Dict[str, Any]:
        """
        Returns stats for the AI dashboard (/ai/):
        Total, Pending, Processing, Completed, Failed counts and category breakdown.
        """
        if not user.is_authenticated:
            return {
                'total': 0,
                'pending': 0,
                'processing': 0,
                'completed': 0,
                'failed': 0,
                'category_distribution': [],
                'failed_emails': []
            }

        user_emails = Email.objects.filter(user=user)
        total = user_emails.count()
        pending = user_emails.filter(Q(ai_status=AIStatus.PENDING) | Q(ai_status__isnull=True)).count()
        processing = user_emails.filter(ai_status=AIStatus.PROCESSING).count()
        completed = user_emails.filter(ai_status=AIStatus.COMPLETED).count()
        failed = user_emails.filter(ai_status=AIStatus.FAILED).count()

        # Category distribution from completed emails
        cat_counts = user_emails.filter(ai_status=AIStatus.COMPLETED).values('ai_category').annotate(count=Count('id'))
        count_map = {item['ai_category']: item['count'] for item in cat_counts if item['ai_category']}

        category_distribution = []
        for cat in EMAIL_CATEGORIES:
            cnt = count_map.get(cat, 0)
            category_distribution.append({
                'name': cat,
                'count': cnt,
                'meta': CATEGORY_META.get(cat, CATEGORY_META['Other'])
            })

        failed_emails = user_emails.filter(ai_status=AIStatus.FAILED).order_by('-received_at')[:10]

        return {
            'total': total,
            'pending': pending,
            'processing': processing,
            'completed': completed,
            'failed': failed,
            'category_distribution': category_distribution,
            'failed_emails': failed_emails
        }

    # --- Phase 1 Summary & Reply Preview Methods (Preserved for Phase 7 & 8) ---
    def get_summary_preview_data(self, user):
        """Returns structured briefing data clearly designated as Phase 1 preview."""
        if not user.is_authenticated:
            total_count = 12
            unread_count = 3
            important_count = 2
        else:
            total_count = Email.objects.filter(user=user).count()
            unread_count = Email.objects.filter(user=user, is_read=False).count()
            important_count = Email.objects.filter(user=user, is_important=True).count()

        return {
            'is_preview': True,
            'preview_badge': 'AI Summary Preview (Phase 1)',
            'total_emails': total_count,
            'unread_emails': unread_count,
            'important_emails': important_count,
            'summary_text': (
                "Your day includes critical academic and recruitment communications requiring prompt attention. "
                "The Head of Department has scheduled a hard deadline for the Phase 1 Internal Assessment this Friday. "
                "In addition, Company HR has requested confirmation for a Senior Fullstack interview slot tomorrow afternoon. "
                "Cloud infrastructure billing and travel notifications have been logged with normal priority."
            ),
            'action_items': [
                "Confirm interview slot with Company HR for tomorrow 2:00 PM.",
                "Review and submit Phase 1 Assessment project report by Friday 5:00 PM.",
                "Regenerate expiring GitHub personal access token (due in 7 days).",
                "Verify automated deduction for Apex Cloud monthly billing ($42.50)."
            ],
            'key_deadlines': [
                {"title": "Internal Assessment Portal Closes", "time": "This Friday, 5:00 PM IST", "urgency": "High"},
                {"title": "HR System Design Interview", "time": "Tomorrow, 2:00 PM", "urgency": "High"},
                {"title": "PowerGrid Utility Bill Due", "time": "October 10", "urgency": "Medium"}
            ]
        }

    def get_sample_reply(self, email_id, tone='Professional', user=None):
        email = None
        if email_id and user:
            email = Email.objects.filter(id=email_id, user=user).first()

        subject = email.subject if email else "Interview Schedule Confirmation"
        sender = email.effective_sender_name if email else "Company HR"

        replies = {
            'Professional': (
                f"Dear {sender},\n\n"
                f"Thank you for reaching out regarding '{subject}'. I confirm my availability "
                f"for the scheduled time. I look forward to our discussion.\n\n"
                f"Best regards,\nAlex Morgan"
            ),
            'Friendly': (
                f"Hi {sender}!\n\n"
                f"Thanks so much for the update on '{subject}'. I'm excited about this opportunity "
                f"and happy to confirm that the time works perfectly for me. See you then!\n\n"
                f"Warmly,\nAlex"
            ),
            'Short': (
                f"Confirmed. I will attend the session at the specified time. Thank you!"
            ),
            'Formal': (
                f"Dear Sir/Madam,\n\n"
                f"I acknowledge receipt of your correspondence regarding '{subject}'. "
                f"Please be advised that I accept the proposed schedule and will attend promptly.\n\n"
                f"Sincerely,\nAlex Morgan"
            )
        }
    # --- Phase 7: Real AI Daily Summary & Smart Reply Methods ---
    def get_daily_summary(self, user, target_date=None, force: bool = False):
        """Retrieves or generates daily summary for user on target_date."""
        return self.summarizer.get_or_generate_daily_summary(user, target_date=target_date, force=force)

    def analyze_email(self, email: Email, user=None, force: bool = False, provider_name: str = None):
        """Executes deep intelligence analysis of an email via Groq / AI provider."""
        return self.analyzer.analyze_email(
            email=email,
            user=user,
            force=force,
            provider_name=provider_name
        )

    def generate_reply(
        self,
        email: Email,
        user,
        tone: str = 'Professional',
        length: str = 'Medium',
        instruction: str = '',
        format_key: str = None,
        provider_name: str = None,
        allow_fallback: bool = None
    ):
        """Generates contextual AI reply suggestion for the given email."""
        return self.reply_generator.generate_ai_reply(
            email=email,
            user=user,
            tone=tone,
            length=length,
            instruction=instruction,
            format_key=format_key,
            provider_name=provider_name,
            allow_fallback=allow_fallback
        )


    def save_reply_draft(self, reply, user, edited_text: str, subject: str = None):
        """Saves edited draft response."""
        return self.reply_generator.save_draft(reply, user, edited_text, subject=subject)

    def apply_template_to_email(self, template, email: Email, user):
        """Applies a static reply template to an email."""
        return self.reply_generator.apply_static_template(template, email, user)

    def send_reply(self, reply, user):
        """Dispatches an approved reply via GmailSendService."""
        from gmail_integration.send_service import send_service
        return send_service.send_reply(reply, user)


# Global singleton instance for clean service imports
ai_service = AIService()

