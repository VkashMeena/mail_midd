import base64
from unittest.mock import patch, MagicMock
from datetime import timedelta
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone

from emails.models import Email, EmailAttachment, EmailCategory, EmailPriority, EmailImportance
from gmail_integration.models import GmailAccount, GmailSyncLog
from gmail_integration.sync import (
    decode_base64url,
    sanitize_email_html,
    GmailSyncService
)
from gmail_integration.exceptions import GmailIntegrationError, GmailTokenError
from dashboard.services import get_dashboard_stats

User = get_user_model()


def make_b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode('utf-8')).decode('ascii').rstrip('=')


class Base64AndSanitizerTests(TestCase):
    def test_decode_base64url(self):
        original = "Hello, world! This is a test email body."
        encoded = make_b64url(original)
        decoded = decode_base64url(encoded)
        self.assertEqual(decoded, original)

    def test_decode_empty_and_invalid(self):
        self.assertEqual(decode_base64url(""), "")
        self.assertEqual(decode_base64url(None), "")
        # Corrupted base64
        self.assertEqual(decode_base64url("???invalid!!!"), "")

    def test_sanitize_email_html_strips_scripts(self):
        unsafe_html = (
            "<p>Normal text</p>"
            "<script>alert('xss')</script>"
            "<img src='http://example.com/pic.jpg' onerror='alert(1)' />"
            "<a href=\"javascript:alert('pwned')\">Click me</a>"
        )
        safe_html = sanitize_email_html(unsafe_html)
        self.assertNotIn("<script>", safe_html)
        self.assertNotIn("</script>", safe_html)
        self.assertNotIn("onerror", safe_html)
        self.assertNotIn("javascript:", safe_html)
        self.assertIn("<p>Normal text</p>", safe_html)
        self.assertIn("src=\"http://example.com/pic.jpg\"", safe_html)

    def test_sanitize_email_html_preserves_safe_tags(self):
        safe_input = (
            "<h1>Title</h1>"
            "<p>This is a <b>bold</b> and <i>italic</i> email with a "
            "<a href=\"https://example.com\">link</a>.</p>"
            "<table><tr><td>Cell 1</td><td>Cell 2</td></tr></table>"
        )
        sanitized = sanitize_email_html(safe_input)
        self.assertIn("<h1>Title</h1>", sanitized)
        self.assertIn("<b>bold</b>", sanitized)
        self.assertIn("<a href=\"https://example.com\">link</a>", sanitized)
        self.assertIn("<table>", sanitized)

    def test_sanitize_email_html_removes_leaked_outlook_css_header(self):
        dirty_input = (
            "#outlook a { padding:0; } body { width:100%!important; }\n"
            "<div class=\"banner\"><p>Special Offer</p></div>"
        )
        cleaned = sanitize_email_html(dirty_input)
        self.assertNotIn("#outlook a", cleaned)
        self.assertIn("<div class=\"banner\"><p>Special Offer</p></div>", cleaned)

    def test_sanitize_email_html_preserves_table_attributes_and_backgrounds(self):
        table_html = '<table width="600" background="https://example.com/bg.png" style="background-color: #ffffff; max-width: 600px;"><tr><td align="center">Content</td></tr></table>'
        cleaned = sanitize_email_html(table_html)
        self.assertIn('background="https://example.com/bg.png"', cleaned)
        self.assertIn('max-width: 600px;', cleaned)
        self.assertIn('Content', cleaned)



class GmailPayloadParserTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='parsertest',
            email='parsertest@example.com',
            password='Password123!'
        )
        self.account = GmailAccount.objects.create(
            user=self.user,
            email_address='parsertest@gmail.com',
            is_connected=True
        )
        self.account.set_access_token('fake_access_token')
        self.account.set_refresh_token('fake_refresh_token')
        self.account.save()
        self.service = GmailSyncService()

    def test_parse_single_part_plain_message(self):
        body_text = "Simple plain text message body."
        raw_msg = {
            'id': 'msg_001',
            'threadId': 'th_001',
            'historyId': '12345',
            'labelIds': ['INBOX', 'UNREAD'],
            'internalDate': '1700000000000',
            'snippet': 'Simple plain text...',
            'payload': {
                'mimeType': 'text/plain',
                'headers': [
                    {'name': 'From', 'value': 'Alice Smith <alice@example.com>'},
                    {'name': 'To', 'value': 'parsertest@gmail.com'},
                    {'name': 'Subject', 'value': 'Project Meeting Tomorrow'},
                    {'name': 'Date', 'value': 'Mon, 13 Nov 2023 10:00:00 +0000'},
                ],
                'body': {
                    'size': len(body_text),
                    'data': make_b64url(body_text)
                }
            }
        }

        parsed = self.service.parse_message_payload(raw_msg, self.account)
        self.assertEqual(parsed['gmail_message_id'], 'msg_001')
        self.assertEqual(parsed['gmail_thread_id'], 'th_001')
        self.assertEqual(parsed['sender_name'], 'Alice Smith')
        self.assertEqual(parsed['sender_email'], 'alice@example.com')
        self.assertEqual(parsed['subject'], 'Project Meeting Tomorrow')
        self.assertEqual(parsed['body_text'], body_text)
        self.assertFalse(parsed['is_read'])  # UNREAD label present
        self.assertFalse(parsed['is_starred'])
        self.assertFalse(parsed['gmail_is_important'])
        self.assertFalse(parsed['has_attachments'])

    def test_parse_multipart_with_attachments_and_html(self):
        body_plain = "Please review the attached invoice."
        body_html = "<p>Please review the <b>attached invoice</b>.</p>"
        raw_msg = {
            'id': 'msg_002',
            'threadId': 'th_002',
            'historyId': '12346',
            'labelIds': ['INBOX', 'STARRED', 'IMPORTANT'],
            'internalDate': '1700000050000',
            'snippet': 'Please review the attached invoice.',
            'payload': {
                'mimeType': 'multipart/mixed',
                'headers': [
                    {'name': 'From', 'value': 'Billing Team <billing@company.com>'},
                    {'name': 'To', 'value': 'parsertest@gmail.com'},
                    {'name': 'Cc', 'value': 'accounting@company.com'},
                    {'name': 'Subject', 'value': 'Invoice #99281'},
                    {'name': 'Date', 'value': 'Tue, 14 Nov 2023 14:00:00 +0000'},
                ],
                'parts': [
                    {
                        'mimeType': 'multipart/alternative',
                        'parts': [
                            {
                                'mimeType': 'text/plain',
                                'body': {'data': make_b64url(body_plain)}
                            },
                            {
                                'mimeType': 'text/html',
                                'body': {'data': make_b64url(body_html)}
                            }
                        ]
                    },
                    {
                        'mimeType': 'application/pdf',
                        'filename': 'Invoice_99281.pdf',
                        'body': {
                            'attachmentId': 'att_pdf_123',
                            'size': 1048576
                        }
                    }
                ]
            }
        }

        parsed = self.service.parse_message_payload(raw_msg, self.account)
        self.assertEqual(parsed['gmail_message_id'], 'msg_002')
        self.assertEqual(parsed['sender_name'], 'Billing Team')
        self.assertEqual(parsed['sender_email'], 'billing@company.com')
        self.assertEqual(parsed['cc'], 'accounting@company.com')
        self.assertEqual(parsed['subject'], 'Invoice #99281')
        self.assertEqual(parsed['body_text'], body_plain)
        self.assertIn("<b>attached invoice</b>", parsed['body_html'])
        self.assertTrue(parsed['is_read'])  # UNREAD label absent
        self.assertTrue(parsed['is_starred'])  # STARRED label present
        self.assertTrue(parsed['gmail_is_important'])  # IMPORTANT label present
        self.assertTrue(parsed['has_attachments'])
        self.assertEqual(len(parsed['attachments']), 1)
        self.assertEqual(parsed['attachments'][0]['filename'], 'Invoice_99281.pdf')
        self.assertEqual(parsed['attachments'][0]['mime_type'], 'application/pdf')
        self.assertEqual(parsed['attachments'][0]['gmail_attachment_id'], 'att_pdf_123')
        self.assertEqual(parsed['attachments'][0]['size'], 1048576)


class GmailSyncIdempotencyAndStorageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='synctestuser',
            email='synctest@example.com',
            password='Password123!'
        )
        self.account = GmailAccount.objects.create(
            user=self.user,
            email_address='synctest@gmail.com',
            is_connected=True
        )
        self.account.set_access_token('access_tok')
        self.account.set_refresh_token('refresh_tok')
        self.account.save()
        self.sync_service = GmailSyncService()

    def test_save_or_update_creates_and_then_updates(self):
        parsed = {
            'gmail_message_id': 'unique_msg_100',
            'gmail_thread_id': 'th_100',
            'gmail_history_id': '555',
            'sender_name': 'Boss',
            'sender_email': 'boss@work.com',
            'recipient_email': 'synctest@gmail.com',
            'cc': '',
            'bcc': '',
            'subject': 'Quarterly Goals',
            'snippet': 'Let us sync on quarterly goals...',
            'body_text': 'Let us sync on quarterly goals this Friday.',
            'body_html': '<p>Let us sync on quarterly goals this Friday.</p>',
            'received_at': timezone.now(),
            'gmail_labels': ['INBOX', 'UNREAD'],
            'is_read': False,
            'is_starred': False,
            'gmail_is_important': True,
            'has_attachments': False,
            'attachments': []
        }

        # First save -> created = True
        is_new = self.sync_service._save_or_update_email(self.account, parsed)
        self.assertTrue(is_new)
        self.assertEqual(Email.objects.filter(gmail_account=self.account).count(), 1)

        email = Email.objects.get(gmail_account=self.account, gmail_message_id='unique_msg_100')
        self.assertFalse(email.is_read)
        self.assertFalse(email.is_pinned)
        self.assertTrue(email.gmail_is_important)

        # User pins email locally
        email.is_pinned = True
        email.save(update_fields=['is_pinned'])

        # Next sync: Gmail message marked read on Gmail side
        parsed['is_read'] = True
        parsed['gmail_labels'] = ['INBOX']
        is_new_second = self.sync_service._save_or_update_email(self.account, parsed)
        self.assertFalse(is_new_second)  # Was an update, not a new email
        self.assertEqual(Email.objects.filter(gmail_account=self.account).count(), 1)

        email.refresh_from_db()
        self.assertTrue(email.is_read)
        # Verify user local state 'is_pinned' was NOT overridden
        self.assertTrue(email.is_pinned)

    def test_attachments_creation(self):
        parsed = {
            'gmail_message_id': 'msg_with_att',
            'gmail_thread_id': 'th_att',
            'gmail_history_id': '777',
            'sender_name': 'Designer',
            'sender_email': 'designer@studio.com',
            'recipient_email': 'synctest@gmail.com',
            'cc': '',
            'bcc': '',
            'subject': 'Design assets',
            'snippet': 'Assets attached',
            'body_text': 'Here are the assets.',
            'body_html': '<p>Here are the assets.</p>',
            'received_at': timezone.now(),
            'gmail_labels': ['INBOX'],
            'is_read': True,
            'is_starred': True,
            'gmail_is_important': False,
            'has_attachments': True,
            'attachments': [
                {
                    'gmail_attachment_id': 'att_id_1',
                    'filename': 'mockup.png',
                    'mime_type': 'image/png',
                    'size': 204800
                },
                {
                    'gmail_attachment_id': 'att_id_2',
                    'filename': 'specs.pdf',
                    'mime_type': 'application/pdf',
                    'size': 512000
                }
            ]
        }

        self.sync_service._save_or_update_email(self.account, parsed)
        email = Email.objects.get(gmail_account=self.account, gmail_message_id='msg_with_att')
        self.assertEqual(email.attachments.count(), 2)

        att1 = email.attachments.get(gmail_attachment_id='att_id_1')
        self.assertEqual(att1.filename, 'mockup.png')
        self.assertIn('KB', att1.size_formatted)

        # Re-syncing should not duplicate attachments
        self.sync_service._save_or_update_email(self.account, parsed)
        self.assertEqual(email.attachments.count(), 2)


class GmailSyncFullServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='fullsyncuser',
            email='fullsync@example.com',
            password='Password123!'
        )
        self.account = GmailAccount.objects.create(
            user=self.user,
            email_address='fullsync@gmail.com',
            is_connected=True
        )
        self.account.set_access_token('access_tok_valid')
        self.account.set_refresh_token('refresh_tok_valid')
        self.account.save()

    @patch('gmail_integration.sync.GmailClient')
    def test_sync_gmail_account_success_with_pagination(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_service = MagicMock()
        mock_client.build_service.return_value = mock_service

        # Mock list() returning 2 pages
        list_req1 = MagicMock()
        list_req1.execute.return_value = {
            'messages': [{'id': 'm1'}, {'id': 'm2'}],
            'nextPageToken': 'token_page_2'
        }
        list_req2 = MagicMock()
        list_req2.execute.return_value = {
            'messages': [{'id': 'm3'}],
            # No nextPageToken on final page
        }

        mock_service.users().messages().list.side_effect = [list_req1, list_req2]

        def fake_get(userId, id, format):
            req = MagicMock()
            req.execute.return_value = {
                'id': id,
                'threadId': f'th_{id}',
                'labelIds': ['INBOX'],
                'internalDate': '1700000000000',
                'snippet': f'Snippet for {id}',
                'payload': {
                    'mimeType': 'text/plain',
                    'headers': [
                        {'name': 'From', 'value': f'sender_{id}@example.com'},
                        {'name': 'Subject', 'value': f'Subject {id}'},
                    ],
                    'body': {'data': make_b64url(f'Body content for {id}')}
                }
            }
            return req

        mock_service.users().messages().get.side_effect = fake_get

        service = GmailSyncService(initial_sync_limit=10, batch_size=2)
        stats = service.sync_gmail_account(self.account)

        self.assertEqual(stats['fetched'], 3)
        self.assertEqual(stats['created'], 3)
        self.assertEqual(stats['updated'], 0)
        self.assertEqual(stats['failed'], 0)

        # Verify GmailSyncLog recorded
        log = GmailSyncLog.objects.filter(gmail_account=self.account).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'COMPLETED')
        self.assertEqual(log.fetched_count, 3)
        self.assertEqual(log.created_count, 3)

        # Verify emails in database
        self.assertEqual(Email.objects.filter(gmail_account=self.account).count(), 3)


class GmailSyncViewAndInboxTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='viewuser',
            email='viewuser@example.com',
            password='Password123!'
        )
        self.account = GmailAccount.objects.create(
            user=self.user,
            email_address='viewuser@gmail.com',
            is_connected=True
        )
        self.account.set_access_token('access_view')
        self.account.set_refresh_token('refresh_view')
        self.account.save()

    def test_sync_view_requires_login(self):
        response = self.client.post(reverse('gmail:sync'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_sync_view_get_method_not_allowed(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('gmail:sync'))
        self.assertEqual(response.status_code, 405)

    @patch('gmail_integration.views.sync_service')
    def test_sync_view_post_success_redirects_inbox(self, mock_sync_service):
        self.client.force_login(self.user)
        mock_sync_service.sync_gmail_account.return_value = {
            'fetched': 5,
            'created': 4,
            'updated': 1,
            'failed': 0
        }

        response = self.client.post(reverse('gmail:sync'))
        self.assertRedirects(response, reverse('inbox'))
        mock_sync_service.sync_gmail_account.assert_called_once_with(self.account)

    def test_inbox_displays_synced_emails_and_filter(self):
        self.client.force_login(self.user)

        # Create sample emails
        e1 = Email.objects.create(
            user=self.user,
            gmail_account=self.account,
            gmail_message_id='m1',
            sender_name='Alice',
            sender_email='alice@example.com',
            subject='Urgent: Q4 Roadmap',
            body_text='Important roadmap details',
            is_read=False,
            is_starred=True,
            gmail_is_important=True
        )
        e2 = Email.objects.create(
            user=self.user,
            gmail_account=self.account,
            gmail_message_id='m2',
            sender_name='Bob',
            sender_email='bob@example.com',
            subject='Lunch on Thursday',
            body_text='Tacos or sushi?',
            is_read=True,
            is_starred=False,
            gmail_is_important=False
        )

        # 1. Default inbox
        resp = self.client.get(reverse('emails:inbox'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Urgent: Q4 Roadmap')
        self.assertContains(resp, 'Lunch on Thursday')

        # 2. Filter unread
        resp_unread = self.client.get(reverse('emails:inbox') + '?filter=unread')
        self.assertEqual(resp_unread.status_code, 200)
        self.assertContains(resp_unread, 'Urgent: Q4 Roadmap')
        self.assertNotContains(resp_unread, 'Lunch on Thursday')

        # 3. Filter starred
        resp_starred = self.client.get(reverse('emails:inbox') + '?filter=starred')
        self.assertEqual(resp_starred.status_code, 200)
        self.assertContains(resp_starred, 'Urgent: Q4 Roadmap')
        self.assertNotContains(resp_starred, 'Lunch on Thursday')

        # 4. Search query
        resp_search = self.client.get(reverse('emails:inbox') + '?q=sushi')
        self.assertEqual(resp_search.status_code, 200)
        self.assertContains(resp_search, 'Lunch on Thursday')
        self.assertNotContains(resp_search, 'Urgent: Q4 Roadmap')

    def test_email_detail_view_marks_read(self):
        self.client.force_login(self.user)
        email = Email.objects.create(
            user=self.user,
            gmail_account=self.account,
            gmail_message_id='m_detail',
            sender_name='Charlie',
            sender_email='charlie@example.com',
            subject='Contract Agreement',
            body_text='Please see contract.',
            body_html='<p>Please see <b>contract</b>.</p>',
            is_read=False
        )
        # Detail view
        resp = self.client.get(reverse('emails:detail', kwargs={'email_id': email.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Contract Agreement')
        self.assertContains(resp, 'Charlie')
        self.assertContains(resp, 'Please see <b>contract</b>.')

        # Verify marked as read in database
        email.refresh_from_db()
        self.assertTrue(email.is_read)

    def test_dashboard_stats_accurate(self):
        self.client.force_login(self.user)
        Email.objects.create(
            user=self.user,
            gmail_account=self.account,
            gmail_message_id='d1',
            sender_email='test1@example.com',
            subject='Test 1',
            body_text='Body 1',
            is_read=False,
            is_starred=True,
            gmail_is_important=True
        )
        Email.objects.create(
            user=self.user,
            gmail_account=self.account,
            gmail_message_id='d2',
            sender_email='test2@example.com',
            subject='Test 2',
            body_text='Body 2',
            is_read=True,
            is_starred=False,
            gmail_is_important=False
        )

        stats = get_dashboard_stats(self.user)
        self.assertEqual(stats['total_emails'], 2)
        self.assertEqual(stats['unread_emails'], 1)
        self.assertEqual(stats['starred_emails'], 1)
        self.assertEqual(stats['important_emails'], 1)
        # AI metrics remain 0 for Phase 4
        self.assertEqual(stats['ai_analyzed'], 0)
