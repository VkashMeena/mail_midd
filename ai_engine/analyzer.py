"""
AI Email Analyzer Service.
Deeply analyzes email objective, urgency, sentiment, key takeaways, action items,
extracted deadlines, and response angles using Groq LPU / LLM providers.
"""
import re
import json
import logging
from typing import Dict, Any, Optional
from django.conf import settings
from django.utils import timezone

from emails.models import Email, EmailAnalysis, AIStatus, EmailCategory, EmailPriority
from .exceptions import AIEngineError, AIProviderError, AIValidationError, AIConfigurationError
from .providers import get_ai_provider, BaseAIProvider
from .context_builder import extract_clean_email_text, get_attachments_summary
from .constants import PRIMARY_CATEGORIES

logger = logging.getLogger(__name__)


class EmailAnalyzer:
    """
    Dedicated AI analyzer for deep email understanding and intelligence extraction.
    Powered by Groq LPU (Llama 3.3 70B) with automatic failover.
    """

    def __init__(self, provider: Optional[BaseAIProvider] = None):
        self._provider = provider

    @property
    def provider(self) -> BaseAIProvider:
        if self._provider is None:
            self._provider = get_ai_provider()
        return self._provider

    @staticmethod
    def _parse_json_response(raw_text: str) -> Dict[str, Any]:
        """
        Parses JSON response robustly, stripping markdown fences or extracting JSON blocks.
        """
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
            cleaned = cleaned.strip()

        # Try direct parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to match the first '{' and last '}'
            match = re.search(r'(\{.*\})', cleaned, flags=re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except Exception:
                    pass
            raise AIValidationError("Unable to parse JSON intelligence payload from AI response.")

    @staticmethod
    def _normalize_category(cat_str: Optional[str]) -> str:
        if not cat_str:
            return EmailCategory.OTHER
        cleaned = str(cat_str).strip()
        for valid_cat in PRIMARY_CATEGORIES:
            if cleaned.lower() == valid_cat.lower() or cleaned.lower().replace('/', '_') == valid_cat.lower().replace('/', '_'):
                return valid_cat
        # Fuzzy keyword matching
        c_low = cleaned.lower()
        if 'job' in c_low or 'intern' in c_low or 'interview' in c_low or 'hiring' in c_low:
            return EmailCategory.JOB_INTERNSHIP
        if 'work' in c_low or 'office' in c_low or 'project' in c_low:
            return EmailCategory.WORK
        if 'edu' in c_low or 'academic' in c_low or 'course' in c_low or 'university' in c_low:
            return EmailCategory.EDUCATION
        if 'finan' in c_low or 'bank' in c_low or 'bill' in c_low or 'pay' in c_low:
            return EmailCategory.FINANCE
        if 'shop' in c_low or 'order' in c_low or 'deliver' in c_low:
            return EmailCategory.SHOPPING
        if 'promo' in c_low or 'deal' in c_low or 'discount' in c_low or 'sale' in c_low:
            return EmailCategory.PROMOTION
        if 'news' in c_low:
            return EmailCategory.NEWSLETTER
        if 'notif' in c_low or 'alert' in c_low:
            return EmailCategory.NOTIFICATION
        if 'person' in c_low:
            return EmailCategory.PERSONAL
        return EmailCategory.OTHER

    @staticmethod
    def _normalize_priority(prio_str: Optional[str]) -> str:
        cleaned = str(prio_str or '').strip().capitalize()
        if cleaned in (EmailPriority.HIGH, EmailPriority.MEDIUM, EmailPriority.LOW):
            return cleaned
        return EmailPriority.MEDIUM

    def analyze_email(
        self,
        email: Email,
        user=None,
        force: bool = False,
        provider_name: Optional[str] = None
    ) -> EmailAnalysis:
        """
        Executes complete intelligence analysis of an email using Groq / AI provider.
        Stores results in EmailAnalysis and updates Email classification fields.
        """
        target_user = user or email.user

        if not force:
            existing = EmailAnalysis.objects.filter(email=email).first()
            if existing:
                return existing

        # Build clean payload for LLM analysis
        clean_body = extract_clean_email_text(email.body_text or email.snippet or "", max_chars=18000)
        attachments_info = get_attachments_summary(email)
        gmail_labels = [l.strip() for l in email.gmail_labels.split(',') if l.strip()] if email.gmail_labels else []

        payload = {
            'sender_name': email.effective_sender_name or email.sender_name or 'Unknown',
            'sender_email': email.sender_email or '',
            'recipient_email': email.recipient_email or (target_user.email if target_user else ''),
            'subject': email.subject or '(No Subject)',
            'received_at': email.received_at.strftime('%Y-%m-%d %H:%M:%S') if email.received_at else 'Recent',
            'attachments_info': attachments_info,
            'gmail_labels': gmail_labels,
            'body_text': clean_body,
        }

        # Resolve provider
        prov = get_ai_provider(provider_name) if provider_name else self.provider
        prov_name = provider_name or getattr(settings, 'AI_PROVIDER', 'groq')
        model_name = getattr(prov, 'model', getattr(settings, 'GROQ_MODEL', 'llama-3.3-70b-versatile'))

        try:
            raw_response = prov.analyze(payload)
            parsed = self._parse_json_response(raw_response)

            category = self._normalize_category(parsed.get('category'))
            priority = self._normalize_priority(parsed.get('priority'))
            is_important = bool(parsed.get('is_important', priority == EmailPriority.HIGH))
            confidence = float(parsed.get('confidence', 0.9))
            confidence = max(0.0, min(1.0, confidence))
            objective = str(parsed.get('objective', '')).strip()
            reason = str(parsed.get('reason', '')).strip()
            action_required = bool(parsed.get('action_required', False))
            urgency = str(parsed.get('urgency', 'Moderate')).strip()
            sentiment = str(parsed.get('sentiment', 'Professional')).strip()

            key_points = parsed.get('key_points', [])
            if not isinstance(key_points, list):
                key_points = [str(key_points)]

            action_items = parsed.get('action_items', [])
            if not isinstance(action_items, list):
                action_items = [str(action_items)]

            extracted_deadlines = parsed.get('extracted_deadlines', [])
            if not isinstance(extracted_deadlines, list):
                extracted_deadlines = [str(extracted_deadlines)]

            suggested_reply_hooks = parsed.get('suggested_reply_hooks', [])
            if not isinstance(suggested_reply_hooks, list):
                suggested_reply_hooks = [str(suggested_reply_hooks)]

            # Save or update EmailAnalysis
            analysis, _ = EmailAnalysis.objects.update_or_create(
                email=email,
                defaults={
                    'user': target_user,
                    'provider': prov_name,
                    'model_name': model_name,
                    'objective': objective,
                    'category': category,
                    'priority': priority,
                    'is_important': is_important,
                    'urgency': urgency,
                    'sentiment': sentiment,
                    'confidence': confidence,
                    'reason': reason,
                    'action_required': action_required,
                    'key_points': key_points,
                    'action_items': action_items,
                    'extracted_deadlines': extracted_deadlines,
                    'suggested_reply_hooks': suggested_reply_hooks,
                    'raw_response': raw_response,
                }
            )

            # Update parent Email model fields (respecting user manual overrides)
            update_fields = [
                'ai_objective', 'ai_reason', 'action_required', 'ai_confidence',
                'ai_status', 'ai_processed_at', 'ai_error', 'updated_at'
            ]
            email.ai_objective = objective
            email.ai_reason = reason
            email.action_required = action_required
            email.ai_confidence = confidence
            email.ai_status = AIStatus.COMPLETED
            email.ai_processed_at = timezone.now()
            email.ai_error = ''

            if not email.user_category:
                email.ai_category = category
                email.category = category
                update_fields.extend(['ai_category', 'category'])

            if not email.user_priority:
                email.ai_priority = priority
                email.priority = priority
                update_fields.extend(['ai_priority', 'priority'])

            if email.user_is_important is None:
                email.ai_is_important = is_important
                email.is_important = is_important
                update_fields.extend(['ai_is_important', 'is_important'])

            email.save(update_fields=list(set(update_fields)))

            # If determined important, trigger notification
            if is_important:
                try:
                    from notifications.services import create_important_notification
                    create_important_notification(email)
                except Exception as notif_exc:
                    logger.warning("Could not dispatch notification for important email %s: %s", email.id, notif_exc)

            return analysis


        except Exception as exc:
            logger.error("AI analysis failed for email id=%s: %s", email.id, exc)
            email.ai_status = AIStatus.FAILED
            email.ai_error = str(exc)[:500]
            email.save(update_fields=['ai_status', 'ai_error', 'updated_at'])
            raise


# Global singleton instance for convenient imports
email_analyzer = EmailAnalyzer()
