import json
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
import pytz

from emails.models import (
    Email,
    EmailSummary,
    EmailReply,
    ReplyTemplate,
    ReplyAuditLog,
    EmailCategory,
    EmailPriority,
)
from gmail_integration.models import GmailAccount
from gmail_integration.scopes import get_scopes_list, get_send_scopes_list, GMAIL_READ_SCOPES, GMAIL_SEND_SCOPE, SCOPES
from gmail_integration.send_service import send_service
from gmail_integration.exceptions import GmailIntegrationError, GmailPermissionError
from ai_engine.schemas import validate_summary_payload, AISummaryResult
from ai_engine.exceptions import AIValidationError, AIConfigurationError
from ai_engine.summarizer import EmailSummarizer
from ai_engine.reply_generator import EmailReplyGenerator
from ai_engine.services import ai_service

User = get_user_model()


class AISummarySchemaTests(TestCase):
    def test_valid_summary_payload(self):
        raw = {
            "overview": "You received 5 emails today regarding college internal assessments and project reviews.",
            "important_points": [
                "HOD confirmed assessment report deadline for Friday 5 PM.",
                "Recruiter requested availability for system design round."
            ],
            "action_items": [
                "Submit project report before Friday 5:00 PM.",
                "Reply to recruiter with available interview slots."
            ],
            "category_summary": [
                {"category": "Education", "highlight": "Phase 1 assessment deadline announcement."},
                {"category": "Work", "highlight": "Interview schedule coordination."}
            ]
        }
        res = validate_summary_payload(raw)
        self.assertIsInstance(res, AISummaryResult)
        self.assertIn("college internal assessments", res.overview)
        self.assertEqual(len(res.important_points), 2)
        self.assertEqual(len(res.action_items), 2)
        self.assertEqual(len(res.category_summary), 2)
        self.assertEqual(res.category_summary[0]['category'], "Education")

    def test_summary_payload_missing_overview_raises_validation_error(self):
        raw = {
            "overview": "",
            "important_points": ["Item 1"]
        }
        with self.assertRaises(AIValidationError):
            validate_summary_payload(raw)

    def test_summary_payload_list_normalization_and_truncation(self):
        raw = {
            "overview": "Short overview.",
            "important_points": "Single string point",  # String instead of list
            "action_items": ["Action item " + ("x" * 400)],  # Over 300 chars
            "category_summary": {"Work": "Work highlight", "Finance": "Billing alert"}  # Dict format
        }
        res = validate_summary_payload(raw)
        self.assertEqual(len(res.important_points), 1)
        self.assertEqual(res.important_points[0], "Single string point")
        self.assertEqual(len(res.action_items[0]), 300)
        self.assertEqual(len(res.category_summary), 2)


class EmailSummaryModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='summaryuser', email='summaryuser@example.com', password='password123')

    def test_email_summary_creation_and_defaults(self):
        summary = EmailSummary.objects.create(
            user=self.user,
            summary_date=date(2026, 9, 29),
            total_emails=10,
            unread_count=4,
            important_count=2,
            overview="Productive day with assessment reviews.",
            important_points=["Exam schedule published."],
            action_items=["Complete assignment."],
            category_summary=[{"category": "Education", "highlight": "Exam details."}],
            ai_status=EmailSummary.STATUS_COMPLETED
        )
        self.assertEqual(summary.total_emails_analyzed, 10)
        self.assertEqual(summary.ai_status, EmailSummary.STATUS_COMPLETED)
        self.assertIn("2026-09-29", str(summary))

    def test_email_summary_unique_constraint_user_and_date(self):
        summary_date = date(2026, 9, 29)
        EmailSummary.objects.create(
            user=self.user,
            summary_date=summary_date,
            overview="First summary"
        )
        with self.assertRaises(Exception):
            EmailSummary.objects.create(
                user=self.user,
                summary_date=summary_date,
                overview="Duplicate summary for same user and date"
            )


class EmailReplyModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='replyuser', email='replyuser@example.com', password='password123')
        self.email = Email.objects.create(
            user=self.user,
            sender_name="Alice Smith",
            sender_email="alice@example.com",
            recipient_email="replyuser@example.com",
            subject="Project Meeting Sync",
            body_text="Hi, can we meet tomorrow at 10 AM to discuss the API contract?"
        )

    def test_email_reply_creation_and_final_text_property(self):
        reply = EmailReply.objects.create(
            user=self.user,
            email=self.email,
            reply_type=EmailReply.TYPE_AI_GENERATED,
            tone=EmailReply.TONE_PROFESSIONAL,
            recipient=self.email.sender_email,
            subject="Re: Project Meeting Sync",
            generated_text="Dear Alice, yes tomorrow at 10 AM works well. Best regards.",
            status=EmailReply.STATUS_GENERATED
        )
        # Without edited_text, final_text is generated_text
        self.assertEqual(reply.final_text, "Dear Alice, yes tomorrow at 10 AM works well. Best regards.")

        # With edited_text, final_text returns edited_text
        reply.edited_text = "Dear Alice, 10:30 AM works better for me. Best regards."
        reply.save()
        self.assertEqual(reply.final_text, "Dear Alice, 10:30 AM works better for me. Best regards.")

    def test_email_reply_status_transitions(self):
        reply = EmailReply.objects.create(
            user=self.user,
            email=self.email,
            recipient=self.email.sender_email,
            subject="Re: Project Meeting Sync",
            status=EmailReply.STATUS_GENERATED
        )
        self.assertEqual(reply.status, EmailReply.STATUS_GENERATED)

        reply.status = EmailReply.STATUS_SAVED
        reply.save()
        self.assertEqual(reply.status, EmailReply.STATUS_SAVED)


class ReplyTemplateAndAuditTests(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username='tmpluser1', email='tmpluser1@example.com', password='password123')
        self.user2 = User.objects.create_user(username='tmpluser2', email='tmpluser2@example.com', password='password123')

    def test_reply_template_get_templates_for_user(self):
        # System default template
        ReplyTemplate.objects.create(
            user=None,
            name="System Standard Acknowledgment",
            content="Hello {sender_name}, thank you for your email regarding '{subject}'.",
            is_default=True
        )
        # Custom template for user1
        ReplyTemplate.objects.create(
            user=self.user1,
            name="User1 Custom Pitch Decline",
            content="Thank you {sender_name}, but we are not interested at this time.",
            is_default=False
        )
        # Custom template for user2
        ReplyTemplate.objects.create(
            user=self.user2,
            name="User2 Meeting Request",
            content="Hello {sender_name}, let us set up a 15-minute call.",
            is_default=False
        )

        user1_tmpls = ReplyTemplate.get_templates_for_user(self.user1)
        names1 = [t.name for t in user1_tmpls]
        self.assertIn("System Standard Acknowledgment", names1)
        self.assertIn("User1 Custom Pitch Decline", names1)
        self.assertNotIn("User2 Meeting Request", names1)

    def test_reply_audit_log_creation(self):
        email = Email.objects.create(
            user=self.user1,
            sender_name="Bob",
            sender_email="bob@example.com",
            recipient_email="tmpluser1@example.com",
            subject="Audit Test"
        )
        reply = EmailReply.objects.create(
            user=self.user1,
            email=email,
            recipient="bob@example.com",
            subject="Re: Audit Test",
            status=EmailReply.STATUS_GENERATED
        )
        log = ReplyAuditLog.objects.create(
            user=self.user1,
            email=email,
            reply=reply,
            action=EmailReply.STATUS_GENERATED,
            details="Draft created via AI"
        )
        self.assertEqual(log.user, self.user1)
        self.assertEqual(log.action, EmailReply.STATUS_GENERATED)
        self.assertIn("GENERATED", str(log))


class EmailSummarizerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sumtestuser', email='sumtestuser@example.com', password='password123')
        if hasattr(self.user, 'profile'):
            self.user.profile.timezone = 'UTC'
            self.user.profile.save()

    def test_summarizer_timezone_boundary_calculation(self):
        summarizer = EmailSummarizer()
        start, end, ldate = summarizer.get_date_boundaries(self.user, target_date="2026-09-29")
        self.assertEqual(ldate, date(2026, 9, 29))
        self.assertEqual(start.date(), date(2026, 9, 29))
        self.assertEqual(start.hour, 0)
        self.assertEqual(end, start + timedelta(days=1))

    def test_summarizer_no_emails_creates_empty_summary(self):
        summarizer = EmailSummarizer()
        summary = summarizer.generate_daily_summary(self.user, target_date=date(2026, 9, 29))
        self.assertEqual(summary.total_emails, 0)
        self.assertEqual(summary.ai_status, EmailSummary.STATUS_COMPLETED)
        self.assertIn("No emails were received", summary.overview)

    @patch('ai_engine.providers.openai_provider.OpenAICompatibleProvider.summarize')
    def test_summarizer_successful_generation(self, mock_summarize):
        mock_summarize.return_value = json.dumps({
            "overview": "Overview of today's incoming correspondence.",
            "important_points": ["Urgent security patch required."],
            "action_items": ["Apply patch by end of day."],
            "category_summary": [{"category": "Security", "highlight": "Vulnerability notice."}]
        })

        # Create emails for today
        now = timezone.now()
        Email.objects.create(
            user=self.user,
            sender_name="Security Team",
            sender_email="sec@company.com",
            recipient_email="sumtestuser@company.com",
            subject="Critical Vulnerability Notice",
            body_text="Please update OpenSSL to version 3.2 immediately.",
            received_at=now,
            ai_category=EmailCategory.TECHNOLOGY,
            ai_is_important=True,
            ai_priority=EmailPriority.HIGH
        )

        summarizer = EmailSummarizer()
        summary = summarizer.generate_daily_summary(self.user, target_date=now.date())

        self.assertEqual(summary.total_emails, 1)
        self.assertEqual(summary.important_count, 1)
        self.assertEqual(summary.ai_status, EmailSummary.STATUS_COMPLETED)
        self.assertIn("Overview of today's incoming", summary.overview)
        self.assertEqual(len(summary.important_points), 1)

    @patch('ai_engine.providers.openai_provider.OpenAICompatibleProvider.summarize')
    def test_summarizer_caching_returns_existing_unless_forced(self, mock_summarize):
        mock_summarize.return_value = json.dumps({
            "overview": "Cached summary test.",
            "important_points": [],
            "action_items": [],
            "category_summary": []
        })
        now = timezone.now()
        Email.objects.create(
            user=self.user,
            sender_name="Test",
            sender_email="test@test.com",
            recipient_email="sumtestuser@test.com",
            subject="Test Mail",
            received_at=now
        )
        summarizer = EmailSummarizer()
        # First call: invokes provider
        s1 = summarizer.get_or_generate_daily_summary(self.user, target_date=now.date(), force=False)
        self.assertEqual(mock_summarize.call_count, 1)

        # Second call with force=False: returns cached summary without invoking provider
        s2 = summarizer.get_or_generate_daily_summary(self.user, target_date=now.date(), force=False)
        self.assertEqual(mock_summarize.call_count, 1)
        self.assertEqual(s1.id, s2.id)

        # Third call with force=True: forces regeneration
        s3 = summarizer.get_or_generate_daily_summary(self.user, target_date=now.date(), force=True)
        self.assertEqual(mock_summarize.call_count, 2)


class EmailReplyGeneratorTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='replygentest', email='replygentest@example.com', password='password123')
        self.email = Email.objects.create(
            user=self.user,
            sender_name="Dr. Evelyn Reed",
            sender_email="ereed@university.edu",
            recipient_email="replygentest@university.edu",
            subject="Internal Assessment Clarification",
            body_text="Could you submit the updated presentation slides by Wednesday afternoon?"
        )

    def test_format_reply_subject_no_stacking(self):
        gen = EmailReplyGenerator()
        self.assertEqual(gen.format_reply_subject("Assessment"), "Re: Assessment")
        self.assertEqual(gen.format_reply_subject("Re: Assessment"), "Re: Assessment")
        self.assertEqual(gen.format_reply_subject("RE: Re: Assessment"), "Re: Assessment")

    @patch('ai_engine.providers.openai_provider.OpenAICompatibleProvider.generate_reply')
    def test_generate_ai_reply_success_and_audit(self, mock_gen):
        mock_gen.return_value = "Dear Dr. Reed,\n\nI will send the updated slides by Wednesday 2 PM.\n\nBest regards."

        gen = EmailReplyGenerator()
        reply = gen.generate_ai_reply(
            email=self.email,
            user=self.user,
            tone=EmailReply.TONE_PROFESSIONAL,
            length=EmailReply.LENGTH_SHORT,
            instruction="Confirm Wednesday 2 PM"
        )

        self.assertEqual(reply.user, self.user)
        self.assertEqual(reply.recipient, "ereed@university.edu")
        self.assertEqual(reply.subject, "Re: Internal Assessment Clarification")
        self.assertIn("Wednesday 2 PM", reply.generated_text)
        self.assertEqual(reply.status, EmailReply.STATUS_GENERATED)

        # Verify audit log
        audit = ReplyAuditLog.objects.filter(reply=reply).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.action, EmailReply.STATUS_GENERATED)

    def test_save_draft_updates_text_and_audit(self):
        reply = EmailReply.objects.create(
            user=self.user,
            email=self.email,
            recipient=self.email.sender_email,
            subject="Re: Test",
            generated_text="Initial text",
            status=EmailReply.STATUS_GENERATED
        )
        gen = EmailReplyGenerator()
        gen.save_draft(reply, self.user, edited_text="Updated modified draft", subject="Re: Updated Subject")

        reply.refresh_from_db()
        self.assertEqual(reply.edited_text, "Updated modified draft")
        self.assertEqual(reply.subject, "Re: Updated Subject")
        self.assertEqual(reply.status, EmailReply.STATUS_SAVED)

        audit = ReplyAuditLog.objects.filter(reply=reply, action=EmailReply.STATUS_SAVED).first()
        self.assertIsNotNone(audit)

    def test_apply_static_template_replaces_placeholders(self):
        template = ReplyTemplate.objects.create(
            user=self.user,
            name="Interview Confirmation",
            content="Dear {sender_name},\n\nI confirm receipt of your note regarding '{subject}'. Thank you,\n{user_name}"
        )
        gen = EmailReplyGenerator()
        reply = gen.apply_static_template(template, self.email, self.user)

        self.assertEqual(reply.recipient, self.email.sender_email)
        self.assertIn("Dr. Evelyn Reed", reply.generated_text)
        self.assertIn("Internal Assessment Clarification", reply.generated_text)
        self.assertEqual(reply.reply_type, EmailReply.TYPE_STATIC_TEMPLATE)


class GmailScopeAndSendPermissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='scopetestuser', email='scopetestuser@example.com', password='password123')

    def test_default_scopes_and_send_scopes(self):
        self.assertIn('https://www.googleapis.com/auth/gmail.readonly', SCOPES)
        self.assertIn('https://www.googleapis.com/auth/gmail.send', SCOPES)

        default_scopes = get_scopes_list(include_send=False)
        self.assertIn('https://www.googleapis.com/auth/gmail.readonly', default_scopes)
        self.assertNotIn(GMAIL_SEND_SCOPE, default_scopes)

        send_scopes = get_send_scopes_list()
        self.assertIn(GMAIL_SEND_SCOPE, send_scopes)
        self.assertIn('https://www.googleapis.com/auth/gmail.readonly', send_scopes)

    def test_account_has_send_permission_false_by_default(self):
        account = GmailAccount.objects.create(
            user=self.user,
            email_address="scopetest@gmail.com",
            scopes="https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email"
        )
        self.assertFalse(account.has_send_permission)
        self.assertTrue(account.has_read_permission)

    def test_account_has_send_permission_true_when_granted(self):
        account = GmailAccount.objects.create(
            user=self.user,
            email_address="sendtest@gmail.com",
            scopes="https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send"
        )
        self.assertTrue(account.has_send_permission)
        self.assertTrue(account.has_read_permission)


class GmailSendServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sendtestuser', email='sendtestuser@example.com', password='password123')
        self.other_user = User.objects.create_user(username='otheruser', email='otheruser@example.com', password='password123')
        self.email = Email.objects.create(
            user=self.user,
            sender_name="Sender",
            sender_email="sender@example.com",
            recipient_email="sendtestuser@gmail.com",
            subject="Threaded Inquiry",
            gmail_message_id="msg-12345-abc",
            gmail_thread_id="thread-98765-xyz"
        )
        self.reply = EmailReply.objects.create(
            user=self.user,
            email=self.email,
            recipient="sender@example.com",
            subject="Re: Threaded Inquiry",
            generated_text="Thank you for your inquiry.",
            status=EmailReply.STATUS_GENERATED
        )

    def test_send_reply_without_connected_account_raises_error(self):
        with self.assertRaises(GmailIntegrationError) as ctx:
            send_service.send_reply(self.reply, self.user)
        self.assertIn("No active connected Gmail account", str(ctx.exception))

    def test_send_reply_without_permission_raises_error(self):
        GmailAccount.objects.create(
            user=self.user,
            email_address="sendtestuser@gmail.com",
            is_connected=True,
            is_active=True,
            scopes="https://www.googleapis.com/auth/gmail.readonly"
        )
        with self.assertRaises(GmailPermissionError) as ctx:
            send_service.send_reply(self.reply, self.user)
        self.assertIn("Gmail sending permission is required", str(ctx.exception))

    def test_send_reply_cross_user_raises_permission_error(self):
        with self.assertRaises(PermissionError):
            send_service.send_reply(self.reply, self.other_user)

    def test_send_reply_double_send_prevention(self):
        GmailAccount.objects.create(
            user=self.user,
            email_address="sendtestuser@gmail.com",
            is_connected=True,
            is_active=True,
            scopes="https://www.googleapis.com/auth/gmail.send"
        )
        self.reply.status = EmailReply.STATUS_SENT
        self.reply.save()

        with self.assertRaises(GmailIntegrationError) as ctx:
            send_service.send_reply(self.reply, self.user)
        self.assertIn("already being sent or has already been dispatched", str(ctx.exception))

    @patch('gmail_integration.client.GmailClient.build_service')
    def test_send_reply_success_with_threading_headers(self, mock_build):
        GmailAccount.objects.create(
            user=self.user,
            email_address="sendtestuser@gmail.com",
            is_connected=True,
            is_active=True,
            scopes="https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"
        )

        mock_messages = MagicMock()
        mock_send = MagicMock()
        mock_send.execute.return_value = {'id': 'sent-gmail-id-999', 'threadId': 'thread-98765-xyz'}
        mock_messages.send.return_value = mock_send

        mock_svc = MagicMock()
        mock_svc.users.return_value.messages.return_value = mock_messages
        mock_build.return_value = mock_svc

        sent_reply = send_service.send_reply(self.reply, self.user)

        self.assertEqual(sent_reply.status, EmailReply.STATUS_SENT)
        self.assertEqual(sent_reply.gmail_message_id, 'sent-gmail-id-999')
        self.assertIsNotNone(sent_reply.sent_at)

        # Verify audit log was recorded
        audit = ReplyAuditLog.objects.filter(reply=sent_reply, action=EmailReply.STATUS_SENT).first()
        self.assertIsNotNone(audit)
        self.assertIn("sent-gmail-id-999", audit.details)


class SummaryAndReplyViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='viewtestuser', email='viewtestuser@example.com', password='password123')
        self.client = Client()
        self.client.force_login(self.user)

        self.email = Email.objects.create(
            user=self.user,
            sender_name="Prof. Sharma",
            sender_email="sharma@college.edu",
            recipient_email="viewtestuser@college.edu",
            subject="Project Submission Review",
            body_text="Please submit your final slides for the Phase 7 evaluation.",
            received_at=timezone.now()
        )

    def test_summary_today_view_authenticated(self):
        resp = self.client.get(reverse('summary_today'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Daily Email Summary")

    def test_summary_date_view(self):
        resp = self.client.get(reverse('summary_date', kwargs={'date_str': '2026-09-29'}))
        self.assertEqual(resp.status_code, 200)

    @patch('ai_engine.providers.openai_provider.OpenAICompatibleProvider.summarize')
    def test_generate_summary_view_post(self, mock_summarize):
        mock_summarize.return_value = json.dumps({
            "overview": "Fresh summary from view test.",
            "important_points": [],
            "action_items": [],
            "category_summary": []
        })
        resp = self.client.post(reverse('summary_generate'), {'date_str': '2026-09-29'})
        self.assertEqual(resp.status_code, 302)

    def test_ai_reply_view_authenticated(self):
        resp = self.client.get(reverse('ai_reply'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "AI Smart Reply Studio")

    def test_email_reply_view_with_email_id(self):
        resp = self.client.get(reverse('email_reply', kwargs={'email_id': self.email.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.email.subject)

    @patch('ai_engine.providers.openai_provider.OpenAICompatibleProvider.generate_reply')
    def test_generate_reply_action_ajax(self, mock_reply):
        mock_reply.return_value = "Dear Prof. Sharma,\n\nI will submit the slides today.\n\nBest regards."
        resp = self.client.post(
            reverse('email_reply_generate', kwargs={'email_id': self.email.id}),
            data=json.dumps({
                'tone': 'Professional',
                'length': 'Short',
                'instruction': 'Confirm submission today'
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn("Prof. Sharma", data['final_text'])

    def test_save_reply_draft_action_ajax(self):
        resp = self.client.post(
            reverse('email_reply_draft', kwargs={'email_id': self.email.id}),
            data=json.dumps({
                'edited_text': 'Draft text saved from editor.',
                'subject': 'Re: Project Submission Review'
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        reply = EmailReply.objects.get(id=data['reply_id'])
        self.assertEqual(reply.edited_text, 'Draft text saved from editor.')

    def test_send_reply_action_without_permission_returns_400(self):
        reply = EmailReply.objects.create(
            user=self.user,
            email=self.email,
            recipient=self.email.sender_email,
            subject="Re: Test",
            status=EmailReply.STATUS_SAVED
        )
        resp = self.client.post(
            reverse('email_reply_send', kwargs={'email_id': self.email.id}),
            data=json.dumps({'reply_id': reply.id}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])

    def test_send_reply_action_with_read_only_account_returns_permission_required(self):
        GmailAccount.objects.create(
            user=self.user,
            email_address="viewtestuser@gmail.com",
            is_connected=True,
            is_active=True,
            scopes="https://www.googleapis.com/auth/gmail.readonly"
        )
        reply = EmailReply.objects.create(
            user=self.user,
            email=self.email,
            recipient=self.email.sender_email,
            subject="Re: Test",
            status=EmailReply.STATUS_SAVED
        )
        resp = self.client.post(
            reverse('email_reply_send', kwargs={'email_id': self.email.id}),
            data=json.dumps({'reply_id': reply.id}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])
        self.assertEqual(data.get('code'), 'GMAIL_SEND_PERMISSION_REQUIRED')
        self.assertIn('grant_url', data)
        self.assertIn('Gmail sending permission is required', data['error'])

    def test_authorize_send_view_redirects_with_send_scope(self):
        resp = self.client.get(reverse('gmail:authorize_send'))
        self.assertEqual(resp.status_code, 302)
        redirect_url = resp['Location']
        self.assertIn('gmail.send', redirect_url)
        self.assertIn('gmail.readonly', redirect_url)

    def test_reauthorization_preserves_refresh_token_and_updates_scopes(self):
        from gmail_integration.services import gmail_service
        # Existing account with read-only scopes and an encrypted refresh token
        account = GmailAccount.objects.create(
            user=self.user,
            email_address="reauth@gmail.com",
            is_connected=True,
            is_active=True,
            scopes="https://www.googleapis.com/auth/gmail.readonly"
        )
        account.set_refresh_token("existing-refresh-token-xyz")
        account.save()

        # Mock token exchange returning new scopes (including send) but NO new refresh token
        with patch.object(gmail_service.oauth_handler, 'validate_callback_state', return_value=True):
            with patch.object(gmail_service.oauth_handler, 'exchange_code_for_tokens', return_value={
                'access_token': 'new-access-token-123',
                'refresh_token': None,  # Google omits refresh token on re-auth if consent not full prompt
                'expires_in': 3600,
                'scope': 'https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send',
                'email': 'reauth@gmail.com'
            }):
                updated_account = gmail_service.connect_gmail_account(
                    user=self.user,
                    auth_code="fake-code",
                    incoming_state="state123",
                    session_state="state123"
                )

                self.assertEqual(updated_account.id, account.id)
                self.assertEqual(updated_account.email_address, "reauth@gmail.com")
                # Refresh token was preserved!
                self.assertEqual(updated_account.get_refresh_token(), "existing-refresh-token-xyz")
                # Scopes now include gmail.send!
                self.assertTrue(updated_account.has_send_permission)
                self.assertTrue(updated_account.has_read_permission)


    def test_apply_template_action_ajax(self):
        tmpl = ReplyTemplate.objects.create(
            user=self.user,
            name="Quick Acknowledgment",
            content="Hello {sender_name}, received with thanks."
        )
        resp = self.client.post(
            reverse('email_reply_template', kwargs={'email_id': self.email.id}),
            data=json.dumps({'template_id': tmpl.id}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn("Prof. Sharma", data['final_text'])

    def test_reply_template_crud_views(self):
        # Create template via view
        resp = self.client.post(reverse('reply_templates_manage'), {
            'name': 'Follow-Up Template',
            'content': 'Hi {sender_name}, following up on our discussion.'
        })
        self.assertEqual(resp.status_code, 302)
        tmpl = ReplyTemplate.objects.filter(user=self.user, name='Follow-Up Template').first()
        self.assertIsNotNone(tmpl)

        # Delete template
        del_resp = self.client.post(reverse('reply_template_delete', kwargs={'template_id': tmpl.id}))
        self.assertEqual(del_resp.status_code, 302)
        self.assertFalse(ReplyTemplate.objects.filter(id=tmpl.id).exists())

    def test_unauthenticated_redirects(self):
        anon_client = Client()
        self.assertEqual(anon_client.get(reverse('summary_today')).status_code, 302)
        self.assertEqual(anon_client.get(reverse('ai_reply')).status_code, 302)
