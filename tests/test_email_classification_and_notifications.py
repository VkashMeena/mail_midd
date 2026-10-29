"""
Test Suite for End-to-End AI Email Classification and Real-Time Important Notifications.
Verifies the complete flow:
Gmail Sync -> New Email Detection -> AI Classification / Important Sender Rule
-> Importance Decision -> Notification Creation & Deduplication -> Real-Time Event Dispatch.
"""
import json
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from emails.models import Email, PrioritySender, EmailCategory, EmailPriority, AIStatus
from notifications.models import Notification, NotificationPreference
from notifications.services import create_important_notification, get_effective_notification_source
from ai_engine.classifier import EmailClassifier
from ai_engine.constants import EMAIL_CATEGORIES, normalize_category
from ai_engine.schemas import validate_classification_payload
from gmail_integration.models import GmailAccount
from gmail_integration.sync import GmailSyncService

User = get_user_model()


class EmailClassificationAndNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='user@example.com',
            password='TestPassword123!'
        )
        self.pref = NotificationPreference.get_for_user(self.user)
        self.pref.browser_enabled = True
        self.pref.important_email_enabled = True
        self.pref.important_sender_enabled = True
        self.pref.ai_important_enabled = True
        self.pref.save()

        self.account = GmailAccount.objects.create(
            user=self.user,
            email_address='user@example.com',
            encrypted_access_token='dummy_access',
            encrypted_refresh_token='dummy_refresh',
            is_active=True
        )

    def test_important_sender_rule_hod_college(self):
        """
        Verify that when a priority sender is configured:
        Sender: hod@college.edu, Custom Name: HOD College, Important: YES, Notification: YES
        An incoming email immediately generates an important notification with:
        Title: HOD College
        Message: Important email received: Internal Assessment Submission
        """
        PrioritySender.objects.create(
            user=self.user,
            email_address='hod@college.edu',
            display_name='HOD College',
            is_important=True,
            notification_enabled=True
        )

        email = Email.objects.create(
            user=self.user,
            gmail_account=self.account,
            sender_name='Prof. Sharma',
            sender_email='hod@college.edu',
            recipient_email=self.user.email,
            subject='Internal Assessment Submission',
            body_text='Please submit your internal assessment marks by Friday.',
            gmail_message_id='msg_hod_1'
        )

        # Importance check
        self.assertTrue(email.effective_importance)
        self.assertEqual(email.effective_sender_name, 'HOD College')

        # Trigger notification creation
        notif = create_important_notification(email)
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, 'HOD College')
        self.assertEqual(notif.message, 'Important email received: Internal Assessment Submission')
        self.assertEqual(notif.notification_type, Notification.TYPE_IMPORTANT_SENDER)
        self.assertEqual(notif.importance_source, Notification.SOURCE_IMPORTANT_SENDER)

        # Deduplication check
        dup = create_important_notification(email)
        self.assertEqual(dup.id, notif.id)
        self.assertEqual(Notification.objects.filter(user=self.user).count(), 1)

    @patch('ai_engine.classifier.get_ai_provider')
    def test_ai_important_email_classification_and_notification(self, mock_get_provider):
        """
        Verify that when an email arrives from recruiter@company.com:
        Subject: Interview Schedule
        AI Result:
        Category: Job/Internship
        Important: True
        Priority: High
        Reason: The email contains an interview schedule and requires user attention.
        The system saves category, priority, confidence, reason, and triggers notification.
        """
        mock_provider = MagicMock()
        mock_provider.classify.return_value = json.dumps({
            "category": "Job/Internship",
            "is_important": True,
            "priority": "High",
            "confidence": 0.94,
            "reason": "The email contains an interview schedule and requires user attention."
        })
        mock_get_provider.return_value = mock_provider

        email = Email.objects.create(
            user=self.user,
            gmail_account=self.account,
            sender_name='Tech Recruiter',
            sender_email='recruiter@company.com',
            recipient_email=self.user.email,
            subject='Interview Schedule',
            body_text='We would like to invite you for an interview next Tuesday at 10 AM.',
            gmail_message_id='msg_recruiter_1'
        )

        classifier = EmailClassifier(provider=mock_provider)
        result = classifier.classify_email(email)

        # Verify classification result
        self.assertEqual(result.category, 'Job/Internship')
        self.assertTrue(result.importance)
        self.assertEqual(result.priority, 'High')
        self.assertEqual(result.confidence, 0.94)

        # Verify email updated in database
        email.refresh_from_db()
        self.assertEqual(email.category, 'Job/Internship')
        self.assertEqual(email.ai_category, 'Job/Internship')
        self.assertEqual(email.effective_category, 'Job/Internship')
        self.assertTrue(email.ai_is_important)
        self.assertTrue(email.is_important)
        self.assertEqual(email.priority, 'High')
        self.assertEqual(email.ai_priority, 'High')
        self.assertEqual(email.ai_status, AIStatus.COMPLETED)
        self.assertEqual(email.ai_confidence, 0.94)
        self.assertIn("interview schedule", email.ai_reason)

        # Verify notification created
        notif = Notification.objects.filter(email=email).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.importance_source, Notification.SOURCE_AI)
        self.assertEqual(notif.notification_type, Notification.TYPE_AI_IMPORTANT)
        self.assertEqual(notif.title, 'Tech Recruiter')

    @patch('ai_engine.classifier.get_ai_provider')
    def test_newsletter_classification_no_notification(self, mock_get_provider):
        """
        Verify that newsletters and promotions are categorized correctly
        without creating unwanted notifications.
        """
        mock_provider = MagicMock()
        mock_provider.classify.return_value = json.dumps({
            "category": "Newsletter",
            "is_important": False,
            "priority": "Low",
            "confidence": 0.92,
            "reason": "Weekly engineering digest."
        })
        mock_get_provider.return_value = mock_provider

        email = Email.objects.create(
            user=self.user,
            gmail_account=self.account,
            sender_name='Weekly Tech Digest',
            sender_email='news@techdigest.com',
            recipient_email=self.user.email,
            subject='Issue #142: Future of AI Systems',
            body_text='Here is what happened in tech this week...',
            gmail_message_id='msg_news_1'
        )

        classifier = EmailClassifier(provider=mock_provider)
        result = classifier.classify_email(email)

        self.assertEqual(result.category, 'Newsletter')
        self.assertFalse(result.importance)

        email.refresh_from_db()
        self.assertEqual(email.effective_category, 'Newsletter')
        self.assertFalse(email.is_important)
        self.assertFalse(email.ai_is_important)

        # No notification should be created
        self.assertEqual(Notification.objects.filter(email=email).count(), 0)

    @patch('ai_engine.classifier.get_ai_provider')
    def test_bank_finance_transaction_classification(self, mock_get_provider):
        """
        Verify bank alerts are properly categorized under Finance.
        """
        mock_provider = MagicMock()
        mock_provider.classify.return_value = json.dumps({
            "category": "Finance",
            "is_important": True,
            "priority": "High",
            "confidence": 0.98,
            "reason": "Debit transaction alert."
        })
        mock_get_provider.return_value = mock_provider

        email = Email.objects.create(
            user=self.user,
            gmail_account=self.account,
            sender_name='National Bank',
            sender_email='alerts@nationalbank.com',
            recipient_email=self.user.email,
            subject='Transaction Alert: $250.00 spent',
            body_text='A debit transaction of $250.00 occurred on card ending in 1234.',
            gmail_message_id='msg_bank_1'
        )

        classifier = EmailClassifier(provider=mock_provider)
        result = classifier.classify_email(email)

        self.assertEqual(result.category, 'Finance')
        email.refresh_from_db()
        self.assertEqual(email.effective_category, 'Finance')
        self.assertEqual(email.priority, 'High')

    def test_category_normalization_and_aliases(self):
        """
        Verify that category synonyms/aliases normalize to expected categories.
        """
        self.assertEqual(normalize_category('Job/Internship'), 'Job/Internship')
        self.assertEqual(normalize_category('Jobs'), 'Job/Internship')
        self.assertEqual(normalize_category('job & internship'), 'Job/Internship')
        self.assertEqual(normalize_category('Promotion'), 'Promotion')
        self.assertEqual(normalize_category('Promotions'), 'Promotion')
        self.assertEqual(normalize_category('Newsletter'), 'Newsletter')
        self.assertEqual(normalize_category('Notification'), 'Notification')
        self.assertEqual(normalize_category('Notifications'), 'Notification')
        self.assertEqual(normalize_category('Education'), 'Education')
        self.assertEqual(normalize_category('Finance'), 'Finance')
        self.assertEqual(normalize_category('Personal'), 'Personal')
        self.assertEqual(normalize_category('Shopping'), 'Shopping')
        self.assertEqual(normalize_category('Work'), 'Work')
        self.assertEqual(normalize_category('UnknownDomain'), 'Other')

    @patch('ai_engine.classifier.get_ai_provider')
    def test_gmail_sync_triggers_ai_classification_and_notification(self, mock_get_provider):
        """
        Verify that GmailSyncService._save_or_update_email automatically triggers AI classification
        and creates notifications for important emails upon sync.
        """
        mock_provider = MagicMock()
        mock_provider.classify.return_value = json.dumps({
            "category": "Education",
            "is_important": True,
            "priority": "High",
            "confidence": 0.96,
            "reason": "Final examination schedule released."
        })
        mock_get_provider.return_value = mock_provider

        service = GmailSyncService()
        parsed_data = {
            'gmail_message_id': 'sync_msg_edu_1',
            'gmail_thread_id': 'th_1',
            'gmail_history_id': 'hist_1',
            'sender_name': 'Exam Controller',
            'sender_email': 'exams@university.edu',
            'recipient_email': self.user.email,
            'cc': '',
            'bcc': '',
            'subject': 'Final Examination Timetable Announced',
            'snippet': 'The final timetable has been published.',
            'body_text': 'All students must check their exam timetable.',
            'body_html': '<p>All students must check their exam timetable.</p>',
            'received_at': timezone.now(),
            'is_read': False,
            'is_starred': False,
            'gmail_is_important': False,
            'has_attachments': False,
            'gmail_labels': 'INBOX',
            'attachments': []
        }

        created = service._save_or_update_email(self.account, parsed_data)
        self.assertTrue(created)

        email = Email.objects.get(gmail_message_id='sync_msg_edu_1')
        self.assertEqual(email.category, 'Education')
        self.assertEqual(email.ai_category, 'Education')
        self.assertTrue(email.ai_is_important)
        self.assertTrue(email.is_important)
        self.assertEqual(email.ai_status, AIStatus.COMPLETED)

        # Notification should have been created
        notif = Notification.objects.filter(email=email).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, 'Exam Controller')
        self.assertEqual(notif.importance_source, Notification.SOURCE_AI)
