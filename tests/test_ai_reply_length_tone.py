import json
import re
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
)
from ai_engine.reply_generator import (
    EmailReplyGenerator,
    VALID_TONES,
    VALID_LENGTHS,
    normalize_tone,
    normalize_length,
)
from ai_engine.services import ai_service

User = get_user_model()


class ReplyLengthAndToneValidationTests(TestCase):
    """
    Tests validation and normalization of Length and Tone inputs.
    """

    def test_normalize_valid_tones(self):
        for tone_key, expected_val in VALID_TONES.items():
            self.assertEqual(normalize_tone(tone_key), expected_val)
            self.assertEqual(normalize_tone(tone_key.upper()), expected_val)

    def test_normalize_invalid_tone_defaults_to_professional(self):
        self.assertEqual(normalize_tone("aggressive"), "Professional")
        self.assertEqual(normalize_tone(""), "Professional")
        self.assertEqual(normalize_tone(None), "Professional")

    def test_normalize_valid_lengths(self):
        for len_key, expected_val in VALID_LENGTHS.items():
            self.assertEqual(normalize_length(len_key), expected_val)
            self.assertEqual(normalize_length(len_key.upper()), expected_val)

    def test_normalize_invalid_length_defaults_to_medium(self):
        self.assertEqual(normalize_length("super_long"), "Medium")
        self.assertEqual(normalize_length(""), "Medium")
        self.assertEqual(normalize_length(None), "Medium")


class ContextualFallbackGeneratorTests(TestCase):
    """
    Tests the contextual fallback reply engine across all Length and Tone variations.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            username="vikash_test",
            email="vikash@example.com",
            first_name="Vikash",
            last_name="Kumar"
        )
        self.email = Email.objects.create(
            user=self.user,
            gmail_message_id="msg_reply_test_100",
            sender_name="HR Team",
            sender_email="hr@techcorp.com",
            subject="Interview Scheduled for Monday at 11 AM",
            snippet="Please confirm your availability for the technical round on Monday at 11 AM.",
            body_text="Hi Vikash,\n\nYour interview is scheduled for Monday at 11 AM.\nPlease confirm your availability.\n\nBest regards,\nHR Team",
            category=EmailCategory.JOB_INTERNSHIP,
            priority=EmailPriority.HIGH,
            is_important=True,
            received_at=timezone.now()
        )
        self.generator = EmailReplyGenerator()

    def count_sentences(self, text):
        """Helper to count approximate sentences in body text (excluding greeting/closing)."""
        lines = [line.strip() for line in text.strip().split("\n") if line.strip()]
        body_lines = []
        for line in lines:
            lower = line.lower()
            if any(lower.startswith(g) for g in ["dear ", "hi ", "hello ", "hey ", "greetings"]):
                continue
            if any(lower.startswith(c) for c in ["best regards", "regards", "sincerely", "cheers", "warmly", "thanks and regards"]):
                continue
            if line == self.user.get_full_name() or line == self.user.username:
                continue
            body_lines.append(line)
        body_content = " ".join(body_lines)
        sentences = [s.strip() for s in re.split(r'[.!?]+', body_content) if s.strip()]
        return len(sentences)

    def test_short_length_produces_1_to_3_sentences(self):
        tones = ["Professional", "Polite", "Friendly", "Formal", "Casual"]
        for tone in tones:
            reply = self.generator.generate_contextual_fallback(
                email=self.email,
                tone=tone,
                length="Short",
                instruction="",
                user=self.user
            )
            self.assertTrue("interview" in reply.lower() or "availability" in reply.lower(), f"Reply should address interview/availability: {reply}")
            sentence_count = self.count_sentences(reply)
            self.assertTrue(1 <= sentence_count <= 3, f"Expected 1-3 sentences for Short {tone}, got {sentence_count}: {reply}")

    def test_medium_length_produces_3_to_6_sentences(self):
        tones = ["Professional", "Polite", "Friendly", "Formal", "Casual"]
        for tone in tones:
            reply = self.generator.generate_contextual_fallback(
                email=self.email,
                tone=tone,
                length="Medium",
                instruction="",
                user=self.user
            )
            self.assertTrue("interview" in reply.lower() or "availability" in reply.lower(), f"Reply should address interview/availability: {reply}")
            sentence_count = self.count_sentences(reply)
            self.assertTrue(3 <= sentence_count <= 7, f"Expected 3-6 sentences for Medium {tone}, got {sentence_count}: {reply}")

    def test_long_length_produces_detailed_structured_response(self):
        reply = self.generator.generate_contextual_fallback(
            email=self.email,
            tone="Professional",
            length="Long",
            instruction="",
            user=self.user
        )
        self.assertTrue("interview" in reply.lower() or "availability" in reply.lower(), f"Reply should address interview/availability: {reply}")
        # Long should have multiple paragraphs (greeting, acknowledgement, direct answer, explanation, closing)
        paragraphs = [p.strip() for p in reply.split("\n\n") if p.strip()]
        self.assertGreaterEqual(len(paragraphs), 3, f"Long reply should have structured paragraphs: {reply}")

    def test_casual_tone_uses_informal_greeting_and_style(self):
        reply = self.generator.generate_contextual_fallback(
            email=self.email,
            tone="Casual",
            length="Short",
            instruction="",
            user=self.user
        )
        self.assertTrue(reply.startswith("Hey") or reply.startswith("Hi"))
        self.assertTrue("Cheers" in reply or "Thanks" in reply or "Best" in reply)

    def test_formal_tone_uses_formal_structure(self):
        reply = self.generator.generate_contextual_fallback(
            email=self.email,
            tone="Formal",
            length="Medium",
            instruction="",
            user=self.user
        )
        self.assertTrue(reply.startswith("Dear"))
        self.assertTrue("Sincerely" in reply or "Respectfully" in reply or "Best regards" in reply)

    def test_custom_instruction_is_incorporated(self):
        instruction = "Confirm my availability and ask if any preparation materials are required."
        reply = self.generator.generate_contextual_fallback(
            email=self.email,
            tone="Polite",
            length="Medium",
            instruction=instruction,
            user=self.user
        )
        self.assertIn("preparation materials", reply.lower())


class EmailReplyModelPropertyTests(TestCase):
    """
    Tests property getters/setters and database persistence for reply_length and reply_tone.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="test_prop_user", email="prop@example.com")
        self.email = Email.objects.create(
            user=self.user,
            gmail_message_id="msg_prop_101",
            sender_name="Sender",
            sender_email="sender@example.com",
            subject="Test Subject",
            snippet="Snippet",
            category=EmailCategory.WORK,
            priority=EmailPriority.MEDIUM,
            received_at=timezone.now()
        )

    def test_reply_length_and_tone_properties(self):
        reply = EmailReply(
            user=self.user,
            email=self.email,
            reply_type=EmailReply.TYPE_AI_GENERATED,
            recipient="sender@example.com",
            subject="Re: Test Subject",
            generated_text="Hello, thank you for your message.",
            status=EmailReply.STATUS_GENERATED
        )
        # Set via properties
        reply.reply_length = "Short"
        reply.reply_tone = "Casual"
        reply.custom_instruction = "Be friendly"
        reply.save()

        # Reload from database
        reloaded = EmailReply.objects.get(id=reply.id)
        self.assertEqual(reloaded.length, "Short")
        self.assertEqual(reloaded.reply_length, "Short")
        self.assertEqual(reloaded.tone, "Casual")
        self.assertEqual(reloaded.reply_tone, "Casual")
        self.assertEqual(reloaded.instruction, "Be friendly")
        self.assertEqual(reloaded.custom_instruction, "Be friendly")


class AIReplyViewAndEndpointTests(TestCase):
    """
    Tests UI rendering of Length and Tone options, badges, and the generation/regeneration AJAX endpoint.
    """

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="view_user",
            password="testpassword123",
            email="view@example.com",
            first_name="Vikash"
        )
        self.client.login(username="view_user", password="testpassword123")
        self.email = Email.objects.create(
            user=self.user,
            gmail_message_id="msg_view_201",
            sender_name="Coordinator",
            sender_email="coordinator@college.edu",
            subject="DBMS Internal Exam Schedule",
            snippet="Tomorrow DBMS Internal Examination will be held at 10 AM.",
            body_text="Hi Vikash,\n\nPlease note tomorrow's DBMS internal examination is scheduled for 10 AM.",
            category=EmailCategory.EDUCATION,
            priority=EmailPriority.HIGH,
            received_at=timezone.now()
        )

    def test_ai_reply_page_renders_length_and_tone_controls_and_badges(self):
        url = reverse('email_reply', kwargs={'email_id': self.email.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        # Check Length radios
        self.assertIn('name="replyLength"', content)
        self.assertIn('value="Short"', content)
        self.assertIn('value="Medium"', content)
        self.assertIn('value="Long"', content)

        # Check Tone radios
        self.assertIn('name="replyTone"', content)
        self.assertIn('value="Professional"', content)
        self.assertIn('value="Polite"', content)
        self.assertIn('value="Friendly"', content)
        self.assertIn('value="Formal"', content)
        self.assertIn('value="Casual"', content)

        # Check UI buttons & Badges
        self.assertIn('id="customInstruction"', content)
        self.assertIn('id="btnGenerateAI"', content)
        self.assertIn('id="previewLengthBadge"', content)
        self.assertIn('id="previewToneBadge"', content)
        self.assertIn('id="btnRegenerateAI"', content)
        self.assertIn('id="btnEdit"', content)

    def test_ajax_generate_reply_endpoint_returns_json_with_length_and_tone(self):
        url = reverse('email_reply_generate', kwargs={'email_id': self.email.id})
        payload = {
            'reply_length': 'short',
            'reply_tone': 'casual',
            'custom_instruction': 'Say thanks and confirm arrival'
        }
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['reply_length'], 'Short')
        self.assertEqual(data['reply_tone'], 'Casual')
        self.assertEqual(data['custom_instruction'], 'Say thanks and confirm arrival')
        self.assertTrue(len(data['final_text']) > 0)

        # Verify reply was saved in database
        reply = EmailReply.objects.get(id=data['reply_id'])
        self.assertEqual(reply.length, 'Short')
        self.assertEqual(reply.tone, 'Casual')
        self.assertEqual(reply.instruction, 'Say thanks and confirm arrival')

    def test_ajax_regenerate_flow_updates_reply_with_new_options(self):
        url = reverse('email_reply_generate', kwargs={'email_id': self.email.id})

        # First generation: Short & Casual
        resp1 = self.client.post(
            url,
            data=json.dumps({'reply_length': 'short', 'reply_tone': 'casual'}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertEqual(data1['reply_length'], 'Short')
        self.assertEqual(data1['reply_tone'], 'Casual')

        # Regeneration: Long & Formal
        resp2 = self.client.post(
            url,
            data=json.dumps({'reply_length': 'long', 'reply_tone': 'formal'}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2['reply_length'], 'Long')
        self.assertEqual(data2['reply_tone'], 'Formal')

        # The new generated reply must be different
        self.assertNotEqual(data1['final_text'], data2['final_text'])
