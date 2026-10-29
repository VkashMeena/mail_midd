import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.http import Http404

from emails.models import Email, PrioritySender, EmailCategory, EmailPriority, AIStatus
from ai_engine.constants import EMAIL_CATEGORIES
from ai_engine.schemas import validate_classification_payload, AIClassificationResult
from ai_engine.parser import extract_json_from_text, parse_and_validate_classification
from ai_engine.exceptions import (
    AIEngineError,
    AIConfigurationError,
    AIValidationError,
    AIRateLimitError,
    AITimeoutError
)
from ai_engine.providers.openai_provider import OpenAICompatibleProvider
from ai_engine.classifier import EmailClassifier
from ai_engine.services import ai_service
from dashboard.services import get_dashboard_stats

User = get_user_model()


class AISchemaAndParserTests(TestCase):
    def test_valid_classification_payload(self):
        payload = {
            "category": "Education",
            "importance": True,
            "priority": "High",
            "confidence": 0.95,
            "reason": "Midterm examination schedule announced."
        }
        res = validate_classification_payload(payload)
        self.assertIsInstance(res, AIClassificationResult)
        self.assertEqual(res.category, "Education")
        self.assertTrue(res.importance)
        self.assertEqual(res.priority, "High")
        self.assertEqual(res.confidence, 0.95)
        self.assertIn("examination schedule", res.reason)

    def test_confidence_percentage_and_integer_conversion(self):
        # 1. Percentage string
        res1 = validate_classification_payload({
            "category": "Work",
            "importance": False,
            "priority": "Low",
            "confidence": "94%",
            "reason": "Weekly sync update"
        })
        self.assertEqual(res1.confidence, 0.94)

        # 2. Integer 0-100
        res2 = validate_classification_payload({
            "category": "Finance",
            "importance": True,
            "priority": "Medium",
            "confidence": 88,
            "reason": "Bank statement"
        })
        self.assertEqual(res2.confidence, 0.88)

    def test_invalid_category_rejected(self):
        with self.assertRaises(AIValidationError):
            validate_classification_payload({
                "category": "Random Hallucinated Category",
                "importance": True,
                "priority": "High",
                "confidence": 0.9,
                "reason": "Test"
            })

    def test_invalid_priority_rejected(self):
        with self.assertRaises(AIValidationError):
            validate_classification_payload({
                "category": "Education",
                "importance": True,
                "priority": "CriticalUrgentExtreme",
                "confidence": 0.9,
                "reason": "Test"
            })

    def test_invalid_confidence_rejected(self):
        with self.assertRaises(AIValidationError):
            validate_classification_payload({
                "category": "Education",
                "importance": True,
                "priority": "High",
                "confidence": 150.0,  # invalid
                "reason": "Test"
            })

    def test_malformed_json_rejected(self):
        with self.assertRaises(AIValidationError):
            extract_json_from_text("This is not valid json at all")

    def test_fenced_markdown_json_parsed(self):
        fenced_text = """
        Here is the classification:
        ```json
        {
            "category": "Technology",
            "importance": false,
            "priority": "Low",
            "confidence": 0.82,
            "reason": "Server maintenance notice"
        }
        ```
        Hope that helps!
        """
        res = parse_and_validate_classification(fenced_text)
        self.assertEqual(res.category, "Technology")
        self.assertFalse(res.importance)
        self.assertEqual(res.priority, "Low")

    def test_reason_length_truncated(self):
        long_reason = "X" * 600
        res = validate_classification_payload({
            "category": "Personal",
            "importance": False,
            "priority": "Low",
            "confidence": 0.9,
            "reason": long_reason
        })
        self.assertLessEqual(len(res.reason), 500)
        self.assertTrue(res.reason.endswith("..."))


class AIProviderUnitTests(TestCase):
    @override_settings(AI_API_KEY="")
    def test_provider_missing_api_key_raises_config_error(self):
        provider = OpenAICompatibleProvider(api_key="")
        with self.assertRaises(AIConfigurationError):
            provider.classify({"subject": "Hello", "body_text": "World"})

    @patch('requests.post')
    def test_provider_classify_success_with_mock(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "category": "Jobs",
                        "importance": True,
                        "priority": "High",
                        "confidence": 0.96,
                        "reason": "Software Engineer interview invitation"
                    })
                }
            }]
        }
        mock_post.return_value = mock_response

        provider = OpenAICompatibleProvider(api_key="test-key-123")
        raw_output = provider.classify({"subject": "Interview", "body_text": "Join us tomorrow"})
        data = json.loads(raw_output)
        self.assertEqual(data["category"], "Jobs")
        self.assertTrue(data["importance"])

    @patch('requests.post')
    def test_provider_rate_limit_429_retries_and_raises_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_post.return_value = mock_response

        provider = OpenAICompatibleProvider(api_key="test-key-123", max_retries=2)
        with self.assertRaises(AIRateLimitError):
            provider.classify({"subject": "Hello"})
        self.assertEqual(mock_post.call_count, 2)

    @patch('requests.post')
    def test_provider_timeout_retries_and_raises_error(self, mock_post):
        import requests
        mock_post.side_effect = requests.exceptions.Timeout("Read timeout")

        provider = OpenAICompatibleProvider(api_key="test-key-123", max_retries=2)
        with self.assertRaises(AITimeoutError):
            provider.classify({"subject": "Hello"})
        self.assertEqual(mock_post.call_count, 2)


class AIClassifierAndServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='aiuser',
            email='aiuser@example.com',
            password='Password123!'
        )
        self.mock_provider = MagicMock()
        self.classifier = EmailClassifier(provider=self.mock_provider)

    def test_single_email_classification_success(self):
        email = Email.objects.create(
            user=self.user,
            sender_name="Exam Office",
            sender_email="exams@university.edu",
            subject="Final Exam Timetable Fall 2026",
            body_text="The final examination timetable is released. Check portal.",
            ai_status=AIStatus.PENDING
        )

        self.mock_provider.classify.return_value = json.dumps({
            "category": "Education",
            "importance": True,
            "priority": "High",
            "confidence": 0.98,
            "reason": "Official final exam timetable notification"
        })

        result = self.classifier.classify_email(email)
        self.assertEqual(result.category, "Education")
        self.assertTrue(result.importance)
        self.assertEqual(result.priority, "High")

        email.refresh_from_db()
        self.assertEqual(email.ai_category, "Education")
        self.assertTrue(email.ai_is_important)
        self.assertEqual(email.ai_priority, "High")
        self.assertEqual(email.ai_confidence, 0.98)
        self.assertEqual(email.ai_status, AIStatus.COMPLETED)
        self.assertIsNotNone(email.ai_processed_at)
        self.assertEqual(email.effective_category, "Education")
        self.assertTrue(email.effective_importance)

    def test_skip_already_completed_email(self):
        email = Email.objects.create(
            user=self.user,
            sender_email="already@done.com",
            subject="Already Processed",
            body_text="No need to re-run",
            ai_category="Work",
            ai_is_important=False,
            ai_priority="Medium",
            ai_status=AIStatus.COMPLETED
        )

        # Force=False should not call the provider
        result = self.classifier.classify_email(email, force=False)
        self.assertEqual(result.category, "Work")
        self.mock_provider.classify.assert_not_called()

    def test_reanalyze_email_forces_reclassification(self):
        email = Email.objects.create(
            user=self.user,
            sender_email="reanalyze@work.com",
            subject="Q3 Goals",
            body_text="Review goals",
            ai_category="Other",
            ai_status=AIStatus.COMPLETED
        )

        self.mock_provider.classify.return_value = json.dumps({
            "category": "Work",
            "importance": True,
            "priority": "High",
            "confidence": 0.95,
            "reason": "Quarterly work goals review"
        })

        result = self.classifier.classify_email(email, force=True)
        self.assertEqual(result.category, "Work")
        self.mock_provider.classify.assert_called_once()
        email.refresh_from_db()
        self.assertEqual(email.ai_category, "Work")

    def test_classification_failure_sets_failed_status(self):
        email = Email.objects.create(
            user=self.user,
            sender_email="bad@input.com",
            subject="Bad Output",
            body_text="Trigger error",
            ai_status=AIStatus.PENDING
        )

        self.mock_provider.classify.side_effect = AIValidationError("Schema validation failed")

        with self.assertRaises(AIValidationError):
            self.classifier.classify_email(email)

        email.refresh_from_db()
        self.assertEqual(email.ai_status, AIStatus.FAILED)
        self.assertIn("Schema validation failed", email.ai_error)

    def test_batch_classification(self):
        emails = [
            Email.objects.create(
                user=self.user,
                sender_email=f"sender{i}@test.com",
                subject=f"Subject {i}",
                body_text=f"Body {i}",
                ai_status=AIStatus.PENDING
            )
            for i in range(3)
        ]

        self.mock_provider.classify.return_value = json.dumps({
            "category": "Technology",
            "importance": False,
            "priority": "Low",
            "confidence": 0.8,
            "reason": "Tech notice"
        })

        service = ai_service
        service.classifier = self.classifier
        stats = service.classify_batch(emails)

        self.assertEqual(stats['total'], 3)
        self.assertEqual(stats['completed'], 3)
        self.assertEqual(stats['failed'], 0)
        self.assertEqual(self.mock_provider.classify.call_count, 3)

    def test_security_no_sensitive_tokens_passed_to_ai(self):
        email = Email.objects.create(
            user=self.user,
            sender_name="Security Test",
            sender_email="security@domain.com",
            subject="Test Payload Security",
            body_text="Testing payload minimization",
            gmail_labels="INBOX,UNREAD"
        )
        payload = self.classifier.prepare_email_payload(email)
        # Ensure no credential or ID leakage
        self.assertNotIn('password', payload)
        self.assertNotIn('access_token', payload)
        self.assertNotIn('encrypted_access_token', payload)
        self.assertNotIn('user_id', payload)
        self.assertNotIn('id', payload)
        self.assertIn('sender_name', payload)
        self.assertIn('sender_email', payload)
        self.assertIn('body_text', payload)


class SenderIntelligenceAndOverridesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='senderuser',
            email='sender@example.com',
            password='Password123!'
        )

    def test_priority_sender_case_insensitive_matching(self):
        sender = PrioritySender.objects.create(
            user=self.user,
            email_address="HOD@College.EDU",
            display_name="HOD College",
            priority="High",
            is_important=True
        )
        self.assertEqual(sender.email_address, "hod@college.edu")

        # Email received with mixed casing
        email = Email.objects.create(
            user=self.user,
            sender_name="Professor Smith",
            sender_email="hod@college.edu",
            subject="Faculty Notice",
            body_text="Please submit syllabus",
            ai_is_important=False
        )
        self.assertEqual(email.effective_sender_name, "HOD College")
        self.assertTrue(email.effective_importance)
        self.assertIn("HOD College", email.effective_importance_reason)

    def test_user_category_override(self):
        email = Email.objects.create(
            user=self.user,
            sender_email="company@hr.com",
            subject="Interview Offer",
            body_text="Job details",
            ai_category="Education",  # AI misclassification
            ai_status=AIStatus.COMPLETED
        )
        self.assertEqual(email.effective_category, "Education")

        # User overrides category to Jobs
        email.user_category = "Jobs"
        email.save(update_fields=['user_category'])

        email.refresh_from_db()
        # User category takes precedence
        self.assertEqual(email.effective_category, "Jobs")
        # Original AI category is preserved untouched
        self.assertEqual(email.ai_category, "Education")

    def test_user_importance_override(self):
        email = Email.objects.create(
            user=self.user,
            sender_email="newsletter@daily.com",
            subject="Daily Digest",
            body_text="Digest content",
            ai_is_important=False
        )
        self.assertFalse(email.effective_importance)

        # User overrides to important
        email.user_is_important = True
        email.save(update_fields=['user_is_important'])
        self.assertTrue(email.effective_importance)
        self.assertEqual(email.effective_importance_reason, "Marked Important by you")

        # User explicitly marks not important even if AI said important
        email.ai_is_important = True
        email.user_is_important = False
        email.save(update_fields=['ai_is_important', 'user_is_important'])
        self.assertFalse(email.effective_importance)
        self.assertEqual(email.effective_importance_reason, "Marked Not Important by you")

    def test_effective_importance_synthesis_hierarchy(self):
        # 1. Pinned email is effective important
        pinned_email = Email.objects.create(
            user=self.user,
            sender_email="pinned@test.com",
            subject="Pinned Mail",
            body_text="Pinned content",
            is_pinned=True,
            ai_is_important=False
        )
        self.assertTrue(pinned_email.effective_importance)
        self.assertIn("Pinned", pinned_email.effective_importance_reason)

        # 2. Gmail important label makes effective important
        gmail_imp_email = Email.objects.create(
            user=self.user,
            sender_email="gmail@test.com",
            subject="Gmail Mail",
            body_text="Gmail content",
            gmail_is_important=True,
            ai_is_important=False
        )
        self.assertTrue(gmail_imp_email.effective_importance)
        self.assertIn("Gmail", gmail_imp_email.effective_importance_reason)


class AIViewsAndControllersTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='viewtester',
            email='viewtester@example.com',
            password='Password123!'
        )
        self.other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='Password123!'
        )
        self.email = Email.objects.create(
            user=self.user,
            sender_name="Dean",
            sender_email="dean@university.edu",
            subject="College Announcement",
            body_text="Academic schedule update",
            ai_status=AIStatus.PENDING
        )

    def test_ai_dashboard_view_requires_login(self):
        response = self.client.get(reverse('ai_engine:dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_ai_dashboard_view_renders_accurate_metrics(self):
        self.client.force_login(self.user)
        # Create completed email
        Email.objects.create(
            user=self.user,
            sender_email="finance@test.com",
            subject="Invoice",
            body_text="Invoice details",
            ai_category="Finance",
            ai_status=AIStatus.COMPLETED
        )
        resp = self.client.get(reverse('ai_engine:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "AI Processing Dashboard")
        self.assertContains(resp, "Finance")

    @patch.object(ai_service, 'classify_email')
    def test_analyze_single_view_post_success(self, mock_classify):
        self.client.force_login(self.user)
        mock_classify.return_value = AIClassificationResult(
            category="Education",
            importance=True,
            priority="High",
            confidence=0.99,
            reason="Dean announcement"
        )
        response = self.client.post(reverse('ai_engine:analyze_single', kwargs={'email_id': self.email.id}))
        self.assertRedirects(response, reverse('emails:detail', kwargs={'email_id': self.email.id}))
        mock_classify.assert_called_once()

    def test_cross_user_isolation_prevented(self):
        self.client.force_login(self.other_user)
        # Attempt to classify another user's email
        response = self.client.post(reverse('ai_engine:analyze_single', kwargs={'email_id': self.email.id}))
        self.assertEqual(response.status_code, 404)

    def test_category_detail_view_rejects_invalid_category_with_404(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('emails:category_detail', kwargs={'category_name': 'UnknownArbitraryCategory'}))
        self.assertEqual(response.status_code, 404)

    def test_category_detail_view_valid_category(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('emails:category_detail', kwargs={'category_name': 'Education'}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(resp:=response, "Education Emails")

    def test_override_email_ai_view(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse('emails:override_ai', kwargs={'email_id': self.email.id}),
            {
                'user_category': 'Work',
                'user_is_important': 'true',
                'user_priority': 'High'
            }
        )
        self.assertRedirects(resp, reverse('emails:detail', kwargs={'email_id': self.email.id}))
        self.email.refresh_from_db()
        self.assertEqual(email:=self.email, self.email)
        self.assertEqual(self.email.user_category, 'Work')
        self.assertTrue(self.email.user_is_important)
        self.assertEqual(self.email.user_priority, 'High')
        self.assertEqual(self.email.effective_category, 'Work')
        self.assertTrue(self.email.effective_importance)

    def test_dashboard_stats_ai_analyzed_count(self):
        Email.objects.create(
            user=self.user,
            sender_email="comp@test.com",
            subject="Done",
            body_text="Done",
            ai_category="Education",
            ai_status=AIStatus.COMPLETED
        )
        stats = get_dashboard_stats(self.user)
        self.assertEqual(stats['ai_analyzed'], 1)
        self.assertEqual(stats['ai_pending'], 1)
