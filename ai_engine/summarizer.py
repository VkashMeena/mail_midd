"""
Email Summarizer Interface & Pipeline.
Generates timezone-aware daily executive briefings, key highlights, action items,
and category breakdowns with caching and structured schema validation.
"""
import json
import logging
from datetime import datetime, time, timedelta
from typing import List, Dict, Any, Optional
import pytz
from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from emails.models import Email, EmailSummary
from .constants import EMAIL_CATEGORIES
from .exceptions import AIEngineError, AIValidationError
from .schemas import validate_summary_payload, AISummaryResult
from .providers import get_ai_provider, BaseAIProvider

logger = logging.getLogger(__name__)


class EmailSummarizer:
    """
    Summarizes daily email streams into executive briefings and action items.
    """

    def __init__(self, provider: Optional[BaseAIProvider] = None):
        self._provider = provider

    @property
    def provider(self) -> BaseAIProvider:
        if self._provider is None:
            self._provider = get_ai_provider()
        return self._provider

    def get_user_timezone(self, user) -> pytz.BaseTzInfo:
        """
        Determines the timezone for the user based on profile settings, fallback to UTC.
        """
        tz_name = 'UTC'
        if hasattr(user, 'profile') and user.profile and getattr(user.profile, 'timezone', None):
            tz_name = user.profile.timezone

        try:
            return pytz.timezone(tz_name)
        except Exception:
            return pytz.UTC

    def get_date_boundaries(self, user, target_date=None):
        """
        Returns (start_of_day, start_of_tomorrow, local_date) localized to user's timezone.
        """
        user_tz = self.get_user_timezone(user)
        now_local = timezone.now().astimezone(user_tz)

        if target_date is None:
            local_date = now_local.date()
        elif isinstance(target_date, str):
            local_date = datetime.strptime(target_date, '%Y-%m-%d').date()
        else:
            local_date = target_date

        start_of_day = user_tz.localize(datetime.combine(local_date, time.min))
        start_of_tomorrow = start_of_day + timedelta(days=1)
        return start_of_day, start_of_tomorrow, local_date

    def get_or_generate_daily_summary(
        self,
        user,
        target_date=None,
        force: bool = False
    ) -> EmailSummary:
        """
        Retrieves cached daily summary or generates a new one.
        If force=False and a completed summary exists, returns it directly.
        """
        start_of_day, start_of_tomorrow, local_date = self.get_date_boundaries(user, target_date)

        if not force:
            existing = EmailSummary.objects.filter(
                user=user,
                summary_date=local_date,
                ai_status=EmailSummary.STATUS_COMPLETED
            ).first()
            if existing:
                return existing

        return self.generate_daily_summary(user, target_date=local_date)

    def summarize_for_user(self, user, target_date=None, force: bool = False) -> EmailSummary:
        """Alias for get_or_generate_daily_summary."""
        return self.get_or_generate_daily_summary(user, target_date=target_date, force=force)

    def generate_daily_summary(
        self,
        user,
        target_date=None
    ) -> EmailSummary:
        """
        Executes end-to-end daily summary generation for a user on a given date:
        1. Queries emails within user's local date window [start_of_day, start_of_tomorrow)
        2. Aggregates metrics & category counts
        3. Constructs bounded prioritized AI payload (important -> priority -> unread -> recency)
        4. Invokes AI provider
        5. Validates structured JSON schema
        6. Persists to EmailSummary with STATUS_COMPLETED or STATUS_FAILED
        """
        start_of_day, start_of_tomorrow, local_date = self.get_date_boundaries(user, target_date)

        emails_qs = Email.objects.filter(
            user=user,
            received_at__gte=start_of_day,
            received_at__lt=start_of_tomorrow
        )

        total_count = emails_qs.count()
        unread_count = emails_qs.filter(is_read=False).count()
        important_count = emails_qs.filter(Q(is_important=True) | Q(ai_is_important=True)).count()

        # Category distribution
        cat_counts = emails_qs.values('ai_category').annotate(count=Count('id'))
        count_map = {item['ai_category']: item['count'] for item in cat_counts if item['ai_category']}
        breakdown_lines = [
            f"- {cat}: {count_map[cat]} email(s)"
            for cat in EMAIL_CATEGORIES
            if cat in count_map
        ]
        breakdown_str = "\n".join(breakdown_lines) if breakdown_lines else "No categorized emails"

        # Case: No emails received today
        if total_count == 0:
            summary, _ = EmailSummary.objects.update_or_create(
                user=user,
                summary_date=local_date,
                defaults={
                    'total_emails': 0,
                    'unread_count': 0,
                    'important_count': 0,
                    'overview': f"No emails were received on {local_date.strftime('%B %d, %Y')}.",
                    'important_points': [],
                    'action_items': [],
                    'category_summary': [],
                    'source_email_ids': [],
                    'ai_status': EmailSummary.STATUS_COMPLETED,
                    'error_message': ''
                }
            )
            return summary

        # Prioritize bounded emails for payload
        max_emails = getattr(settings, 'AI_SUMMARY_MAX_EMAILS', 100)
        prioritized_emails = list(
            emails_qs.order_by(
                '-is_important',
                '-ai_is_important',
                'is_read',
                '-received_at'
            )[:max_emails]
        )

        email_snippets = []
        for em in prioritized_emails:
            sender = em.effective_sender_name or em.sender_name or em.sender_email
            cat = em.effective_category
            imp = "YES" if em.effective_is_important else "NO"
            prio = em.effective_priority
            body_snippet = (em.body_text or em.snippet or "")[:250].replace('\n', ' ').strip()
            email_snippets.append(
                f"- [ID:{em.id}] From: {sender} | Subj: '{em.subject}' | Cat: {cat} | Imp: {imp} | Prio: {prio}\n"
                f"  Snippet: {body_snippet}"
            )
        emails_text = "\n".join(email_snippets)

        payload = {
            'summary_date': local_date.strftime('%Y-%m-%d'),
            'total_count': total_count,
            'important_count': important_count,
            'unread_count': unread_count,
            'category_breakdown': breakdown_str,
            'emails_text': emails_text,
        }

        try:
            raw_response = self.provider.summarize(payload)

            # Strip markdown fences if present
            cleaned_text = raw_response.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            if cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()

            parsed = json.loads(cleaned_text)
            validated: AISummaryResult = validate_summary_payload(parsed)

            summary, _ = EmailSummary.objects.update_or_create(
                user=user,
                summary_date=local_date,
                defaults={
                    'total_emails': total_count,
                    'unread_count': unread_count,
                    'important_count': important_count,
                    'overview': validated.overview,
                    'important_points': validated.important_points,
                    'action_items': validated.action_items,
                    'category_summary': validated.category_summary,
                    'source_email_ids': [e.id for e in prioritized_emails],
                    'ai_status': EmailSummary.STATUS_COMPLETED,
                    'error_message': ''
                }
            )
            return summary

        except Exception as exc:
            logger.error("Failed to generate daily summary for user %s on %s: %s", user, local_date, exc)
            summary, _ = EmailSummary.objects.update_or_create(
                user=user,
                summary_date=local_date,
                defaults={
                    'total_emails': total_count,
                    'unread_count': unread_count,
                    'important_count': important_count,
                    'overview': f"Summary generation encountered an error: {str(exc)[:200]}",
                    'important_points': [],
                    'action_items': [],
                    'category_summary': [],
                    'source_email_ids': [e.id for e in prioritized_emails],
                    'ai_status': EmailSummary.STATUS_FAILED,
                    'error_message': str(exc)[:500]
                }
            )
            raise

    # Backwards compatibility interface
    def summarize_emails(self, emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Phase 1 compatibility method.
        """
        if not self._provider:
            return {
                'status': 'preview',
                'daily_summary': 'AI Daily Summary will be generated dynamically in Phase 7.',
                'important_items': [],
                'action_items': [],
                'deadlines': []
            }
        return self.provider.summarize({'emails_text': str(emails)})
