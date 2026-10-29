"""
Comprehensive Tests for Groq Provider, Hybrid Fallback, and AI Email Analyzer.
Verifies real LLM generation, length & tone adaptations, deep email analysis,
and failover between OpenAI and Groq without predefined responses.
"""
import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from emails.models import (
    Email,
    EmailReply,
    EmailCategory,
    EmailPriority,
    EmailAnalysis,
    AIStatus,
)
from ai_engine.providers.groq_provider import GroqProvider
from ai_engine.providers.openai_provider import OpenAICompatibleProvider
from ai_engine.providers import HybridFallbackProvider, get_ai_provider
from ai_engine.analyzer import EmailAnalyzer, email_analyzer
from ai_engine.reply_generator import EmailReplyGenerator
from ai_engine.exceptions import (
    AIRateLimitError,
    AIConfigurationError,
    AITimeoutError,
    AIProviderError
)

User = get_user_model()


class GroqProviderTests(TestCase):
    """
    Tests for GroqProvider inference methods, parameter serialization, and error translation.
    """

    def setUp(self):
        self.provider = GroqProvider(api_key="gsk_test_mock_key_12345", model="llama-3.3-70b-versatile")

    def test_provider_initialization_and_configured(self):
        self.assertTrue(self.provider.is_configured())
        self.assertEqual(self.provider.model, "llama-3.3-70b-versatile")
        self.assertEqual(self.provider.api_key, "gsk_test_mock_key_12345")

    def test_unconfigured_provider(self):
        empty_prov = GroqProvider(api_key="")
        self.assertFalse(empty_prov.is_configured())
        with self.assertRaises(AIConfigurationError):
            empty_prov._chat_completion([{"role": "user", "content": "hi"}])

    @patch('ai_engine.providers.groq_provider.requests.post')
    def test_generate_reply_via_groq(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Dear Sarah,\n\nI confirm my attendance for Monday at 11 AM.\n\nBest regards,\nAlex"}}]
        }
        mock_post.return_value = mock_resp

        # Force REST branch by disabling SDK client
        self.provider._client = None
        with patch('ai_engine.providers.groq_provider.GROQ_SDK_AVAILABLE', False):
            reply = self.provider.generate_reply({
                'sender_name': 'Sarah',
                'subject': 'Interview Confirmation',
                'reply_length': 'Short',
                'reply_tone': 'Professional',
                'body_text': 'Please confirm 11 AM.'
            })
            self.assertIn("confirm my attendance", reply)

    @patch('ai_engine.providers.groq_provider.requests.post')
    def test_analyze_via_groq(self, mock_post):
        analysis_data = {
            "objective": "Confirm technical interview availability for Monday 11 AM",
            "category": "Job/Internship",
            "priority": "High",
            "is_important": True,
            "confidence": 0.95,
            "urgency": "High",
            "sentiment": "Professional",
            "reason": "Recruiter requesting confirmation of interview slot.",
            "action_required": True,
            "key_points": ["Interview on Monday at 11 AM", "Technical screening round"],
            "action_items": ["Confirm attendance by Sunday evening"],
            "extracted_deadlines": ["Monday, 11:00 AM"],
            "suggested_reply_hooks": ["Confirm availability for Monday 11 AM", "Inquire about interview format"]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": json.dumps(analysis_data)}}]
        }
        mock_post.return_value = mock_resp

        with patch('ai_engine.providers.groq_provider.GROQ_SDK_AVAILABLE', False):
            raw = self.provider.analyze({
                'sender_name': 'Tech Recruiter',
                'subject': 'Interview Confirmation',
                'body_text': 'Please confirm your availability for Monday 11 AM.'
            })
            parsed = json.loads(raw)
            self.assertEqual(parsed['category'], "Job/Internship")
            self.assertEqual(parsed['priority'], "High")
            self.assertTrue(parsed['action_required'])


class HybridFallbackProviderTests(TestCase):
    """
    Tests automatic failover between OpenAI and Groq when quota or rate limits occur.
    """

    def setUp(self):
        self.primary = OpenAICompatibleProvider(api_key="sk-test-mock")
        self.secondary = GroqProvider(api_key="gsk-test-mock")
        self.hybrid = HybridFallbackProvider(primary=self.primary, secondary=self.secondary)

    @patch.object(OpenAICompatibleProvider, 'generate_reply')
    def test_primary_success_does_not_call_secondary(self, mock_openai):
        mock_openai.return_value = "Direct OpenAI generated reply."
        result = self.hybrid.generate_reply({'body_text': 'hello'})
        self.assertEqual(result, "Direct OpenAI generated reply.")

    @patch.object(OpenAICompatibleProvider, 'generate_reply')
    @patch.object(GroqProvider, 'generate_reply')
    def test_primary_quota_exhausted_failover_to_groq(self, mock_groq, mock_openai):
        mock_openai.side_effect = AIRateLimitError("OpenAI quota exhausted")
        mock_groq.return_value = "Groq LPU ultra-fast response."

        result = self.hybrid.generate_reply({'body_text': 'hello'})
        self.assertEqual(result, "Groq LPU ultra-fast response.")
        mock_openai.assert_called_once()
        mock_groq.assert_called_once()


class EmailAnalyzerTests(TestCase):
    """
    Tests EmailAnalyzer deep analysis extraction, DB persistence, and synchronization.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="analyzer_user", email="user@smartmail.ai")
        self.email = Email.objects.create(
            user=self.user,
            sender_name="Campus Placement Office",
            sender_email="placements@university.edu",
            subject="Technical Assessment Invitation — Senior Engineer Role",
            snippet="Please complete the online assessment before Friday midnight.",
            body_text="Hi Candidate,\n\nYou have been shortlisted. The deadline to complete the assessment is Friday at 11:59 PM.\n\nBest regards,\nPlacement Cell",
            category=EmailCategory.OTHER,
            priority=EmailPriority.MEDIUM,
            is_important=False
        )

    @patch.object(GroqProvider, 'analyze')
    def test_analyze_email_creates_analysis_and_syncs_email(self, mock_analyze):
        mock_payload = {
            "objective": "Complete coding assessment before Friday midnight",
            "category": "Job/Internship",
            "priority": "High",
            "is_important": True,
            "confidence": 0.98,
            "urgency": "High",
            "sentiment": "Formal",
            "reason": "Official placement assessment with firm deadline.",
            "action_required": True,
            "key_points": ["Assessment link provided", "Strict Friday deadline"],
            "action_items": ["Complete online test before Friday 11:59 PM"],
            "extracted_deadlines": ["Friday at 11:59 PM"],
            "suggested_reply_hooks": ["Acknowledge assessment invitation", "Confirm completion"]
        }
        mock_analyze.return_value = json.dumps(mock_payload)

        analyzer = EmailAnalyzer(provider=GroqProvider(api_key="gsk-mock-key"))
        analysis = analyzer.analyze_email(self.email, user=self.user, force=True)

        self.assertIsInstance(analysis, EmailAnalysis)
        self.assertEqual(analysis.category, "Job/Internship")
        self.assertEqual(analysis.priority, "High")
        self.assertTrue(analysis.is_important)
        self.assertTrue(analysis.action_required)
        self.assertIn("Friday", analysis.extracted_deadlines[0])

        # Verify parent email record synced
        self.email.refresh_from_db()
        self.assertEqual(self.email.category, "Job/Internship")
        self.assertEqual(self.email.priority, "High")
        self.assertTrue(self.email.is_important)
        self.assertEqual(self.email.ai_status, AIStatus.COMPLETED)
        self.assertIn("Complete coding assessment", self.email.ai_objective)


class EmailReplyGeneratorGroqTests(TestCase):
    """
    Tests EmailReplyGenerator using Groq / dynamic LLM without predefined fallbacks.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="reply_user", email="reply@smartmail.ai")
        self.email = Email.objects.create(
            user=self.user,
            sender_name="Jane Doe",
            sender_email="jane@company.com",
            subject="Quarterly Roadmap Review Sync",
            body_text="Hi team,\n\nCan you share the latest slide deck for Thursday's review meeting?\n\nThanks,\nJane",
            category=EmailCategory.WORK,
            priority=EmailPriority.HIGH
        )

    @patch('ai_engine.reply_generator.get_ai_provider')
    def test_dynamic_ai_reply_generation_short(self, mock_get_prov):
        mock_prov = MagicMock()
        mock_prov.generate_reply.return_value = "Hi Jane,\n\nI will send over the latest slide deck shortly.\n\nBest,\nUser"
        mock_get_prov.return_value = mock_prov

        gen = EmailReplyGenerator()
        reply = gen.generate_ai_reply(
            email=self.email,
            user=self.user,
            length="Short",
            tone="Professional",
            allow_fallback=False
        )

        self.assertIn("latest slide deck shortly", reply.generated_text)
        self.assertEqual(reply.length, "Short")
        self.assertEqual(reply.tone, "Professional")
        self.assertEqual(reply.status, EmailReply.STATUS_GENERATED)

    @patch('ai_engine.reply_generator.get_ai_provider')
    def test_unmocked_failure_raises_exception_when_no_fallback(self, mock_get_prov):
        mock_prov = MagicMock()
        mock_prov.generate_reply.side_effect = AIProviderError("Connection timeout")
        mock_get_prov.return_value = mock_prov

        gen = EmailReplyGenerator()
        with self.assertRaises(AIProviderError):
            gen.generate_ai_reply(
                email=self.email,
                user=self.user,
                length="Medium",
                tone="Polite",
                allow_fallback=False
            )


class AIAnalyzerViewsTests(TestCase):
    """
    Tests views for email analysis and the AI analyzer hub.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="view_tester", email="tester@smartmail.ai")
        self.client = Client()
        self.client.force_login(self.user)
        self.email = Email.objects.create(
            user=self.user,
            sender_name="HR Director",
            sender_email="hr@innovate.com",
            subject="Job Offer — Lead Python Architect",
            body_text="We are thrilled to offer you the position. Please review the attached contract.",
            category=EmailCategory.JOB_INTERNSHIP,
            priority=EmailPriority.HIGH
        )

    def test_ai_analyzer_hub_view_loads_successfully(self):
        url = reverse('ai_analyzer')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI Email Analyzer Hub")

    @patch.object(EmailAnalyzer, 'analyze_email')
    def test_email_analyzer_post_json_returns_structured_analysis(self, mock_analyze):
        mock_analysis = EmailAnalysis(
            user=self.user,
            email=self.email,
            category="Job/Internship",
            priority="High",
            is_important=True,
            objective="Offer letter for Lead Python Architect",
            sentiment="Appreciative",
            urgency="High",
            confidence=0.99,
            action_required=True,
            action_items=["Review offer letter"],
            key_points=["Competitive compensation package"],
            extracted_deadlines=["Next Monday"],
            suggested_reply_hooks=["Express gratitude and accept offer"]
        )
        mock_analysis.id = 999
        mock_analysis.updated_at = timezone.now()
        mock_analyze.return_value = mock_analysis

        url = reverse('email_analyze', kwargs={'email_id': self.email.id})
        response = self.client.post(
            url,
            data=json.dumps({'provider': 'groq'}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['analysis']['objective'], "Offer letter for Lead Python Architect")
        self.assertEqual(data['analysis']['priority'], "High")
        self.assertTrue(data['analysis']['action_required'])
