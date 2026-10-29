"""
Automated Test Suite for Phase 6: Real-Time Important Email Notification System.
Covers:
- Notification model, types, sources, deduplication, and email preservation.
- Notification preferences and selective suppression.
- Priority sender alerts with custom display name (HOD College).
- AI Important alerts and User Override alerts.
- Zero-leakage data minimization, content limits (<=100 title, <=250 message), and XSS sanitization.
- API endpoints: mark read, mark all read, delete, unread count, test notification, preferences.
- Push subscription model, endpoint, and ownership isolation.
- WebSocket authentication and user-isolated channel groups.
- Gmail sync and AI classifier integration hooks.
- Notification retention cleanup.
"""
import json
from unittest.mock import patch, MagicMock
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse

from emails.models import Email, PrioritySender, EmailCategory, EmailPriority
from notifications.models import Notification, NotificationPreference, PushSubscription
from notifications.services import (
    create_important_notification,
    get_effective_notification_source,
    mark_notification_read,
    mark_all_read,
    delete_notification,
    get_unread_count,
    create_test_notification,
    cleanup_old_notifications,
    send_push_notification,
    sanitize_text
)
from gmail_integration.models import GmailAccount
from gmail_integration.sync import GmailSyncService

User = get_user_model()


class Phase6NotificationModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='notifuser',
            email='notifuser@example.com',
            password='TestPassword123!'
        )
        self.email = Email.objects.create(
            user=self.user,
            sender_name='Dean Office',
            sender_email='dean@university.edu',
            recipient_email=self.user.email,
            subject='Urgent Meeting Required',
            body_text='Please be present in conference room 3.',
            is_important=True
        )

    def test_notification_creation_and_fields(self):
        """Verify Notification model fields, priority, and source tracking."""
        notif = Notification.objects.create(
            user=self.user,
            email=self.email,
            title='Dean Office',
            message='Important email received: Urgent Meeting Required',
            notification_type=Notification.TYPE_IMPORTANT_EMAIL,
            importance_source=Notification.SOURCE_IMPORTANT_SENDER,
            priority=Notification.PRIORITY_HIGH,
            deduplication_key=f"important_email_{self.email.id}"
        )
        self.assertEqual(notif.user, self.user)
        self.assertEqual(notif.email, self.email)
        self.assertEqual(notif.priority, Notification.PRIORITY_HIGH)
        self.assertEqual(notif.importance_source, Notification.SOURCE_IMPORTANT_SENDER)
        self.assertFalse(notif.is_read)
        self.assertIsNone(notif.read_at)
        self.assertIn('bi-person-star', notif.icon_class)
        self.assertIn('bg-danger', notif.badge_class)

    def test_delete_notification_preserves_email(self):
        """CRITICAL: Deleting a notification must NOT delete the associated Email."""
        notif = Notification.objects.create(
            user=self.user,
            email=self.email,
            title='Dean Office',
            message='Alert',
            notification_type=Notification.TYPE_SYSTEM
        )
        email_id = self.email.id
        notif_id = notif.id

        notif.delete()
        self.assertFalse(Notification.objects.filter(id=notif_id).exists())
        # Email must still exist
        self.assertTrue(Email.objects.filter(id=email_id).exists())

    def test_notification_preferences_defaults(self):
        """Verify NotificationPreference default settings."""
        pref = NotificationPreference.get_for_user(self.user)
        self.assertTrue(pref.browser_enabled)
        self.assertTrue(pref.important_email_enabled)
        self.assertTrue(pref.important_sender_enabled)
        self.assertTrue(pref.ai_important_enabled)
        self.assertTrue(pref.sound_enabled)
        self.assertFalse(pref.push_enabled)
        self.assertFalse(pref.gmail_important_enabled)
        self.assertFalse(pref.notify_pinned_enabled)


class Phase6NotificationEngineTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='student',
            email='student@college.edu',
            password='Password123!'
        )
        self.pref = NotificationPreference.get_for_user(self.user)

    def test_important_sender_notification_with_custom_display_name(self):
        """
        Scenario: User configures hod@college.edu with display name 'HOD College'.
        Email arrives -> triggers IMPORTANT_SENDER notification with Title 'HOD College'.
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
            sender_name='hod@college.edu',
            sender_email='hod@college.edu',
            recipient_email=self.user.email,
            subject='Internal Assessment Submission',
            body_text='Submit marks by 5 PM.'
        )

        notif = create_important_notification(email)
        self.assertIsNotNone(notif)
        self.assertEqual(notif.notification_type, Notification.TYPE_IMPORTANT_SENDER)
        self.assertEqual(notif.importance_source, Notification.SOURCE_IMPORTANT_SENDER)
        self.assertEqual(notif.title, 'HOD College')  # Custom display name verified!
        self.assertIn('Internal Assessment Submission', notif.message)
        self.assertEqual(notif.action_url, f"/inbox/{email.id}/")

    def test_duplicate_prevention_on_same_email(self):
        """Verify that an email can never produce duplicate notifications."""
        PrioritySender.objects.create(
            user=self.user,
            email_address='admin@college.edu',
            display_name='Admin Office',
            is_important=True,
            notification_enabled=True
        )
        email = Email.objects.create(
            user=self.user,
            sender_name='Admin',
            sender_email='admin@college.edu',
            recipient_email=self.user.email,
            subject='Notice 1',
            body_text='Notice body'
        )

        notif1 = create_important_notification(email)
        notif2 = create_important_notification(email)

        self.assertEqual(notif1.id, notif2.id)
        self.assertEqual(Notification.objects.filter(email=email).count(), 1)

    def test_ai_important_notification(self):
        """Verify notification generation when an email is classified as AI-important."""
        email = Email.objects.create(
            user=self.user,
            sender_name='Google Recruiter',
            sender_email='recruiter@google.com',
            recipient_email=self.user.email,
            subject='Interview Schedule Confirmation',
            body_text='We would like to invite you for an interview.',
            ai_is_important=True,
            ai_priority='High',
            ai_category='Jobs'
        )

        notif = create_important_notification(email)
        self.assertIsNotNone(notif)
        self.assertEqual(notif.notification_type, Notification.TYPE_AI_IMPORTANT)
        self.assertEqual(notif.importance_source, Notification.SOURCE_AI)
        self.assertIn('AI detected an important email', notif.message)
        self.assertEqual(notif.title, 'Google Recruiter')

    def test_user_override_notification(self):
        """Verify notification when user manually overrides email as important."""
        email = Email.objects.create(
            user=self.user,
            sender_name='Friend',
            sender_email='friend@example.com',
            recipient_email=self.user.email,
            subject='Project Notes',
            body_text='Here are the notes.',
            user_is_important=True
        )

        notif = create_important_notification(email)
        self.assertIsNotNone(notif)
        self.assertEqual(notif.importance_source, Notification.SOURCE_USER_OVERRIDE)
        self.assertEqual(notif.notification_type, Notification.TYPE_USER_IMPORTANT)

    def test_normal_email_does_not_trigger_notification(self):
        """Standard newsletter email must not trigger notification."""
        email = Email.objects.create(
            user=self.user,
            sender_name='Weekly Newsletter',
            sender_email='newsletter@news.com',
            recipient_email=self.user.email,
            subject='Top Tech Trends',
            body_text='Check out this week’s news.',
            ai_is_important=False
        )

        notif = create_important_notification(email)
        self.assertIsNone(notif)
        self.assertEqual(Notification.objects.filter(email=email).count(), 0)

    def test_preference_suppression_important_sender(self):
        """If user disables important sender alerts, notifications are suppressed."""
        self.pref.important_sender_enabled = False
        self.pref.save()

        PrioritySender.objects.create(
            user=self.user,
            email_address='dean@college.edu',
            is_important=True,
            notification_enabled=True
        )
        email = Email.objects.create(
            user=self.user,
            sender_name='Dean',
            sender_email='dean@college.edu',
            subject='Notice',
            body_text='Body'
        )

        notif = create_important_notification(email)
        self.assertIsNone(notif)

    def test_content_length_limits(self):
        """Verify Title <= 100 chars and Message <= 250 chars."""
        long_sender = "A" * 150
        long_subject = "B" * 300
        email = Email.objects.create(
            user=self.user,
            sender_name=long_sender,
            sender_email='long@example.com',
            recipient_email=self.user.email,
            subject=long_subject,
            body_text='Test',
            user_is_important=True
        )

        notif = create_important_notification(email)
        self.assertLessEqual(len(notif.title), 100)
        self.assertLessEqual(len(notif.message), 250)

    def test_xss_protection_in_notification_message(self):
        """Verify HTML script injection in subject/sender is completely sanitized."""
        xss_subject = "<script>alert('pwned')</script>Congratulations on Winning!"
        xss_sender = "<b>Malicious</b> <script>steal()</script>"
        email = Email.objects.create(
            user=self.user,
            sender_name=xss_sender,
            sender_email='attacker@bad.com',
            recipient_email=self.user.email,
            subject=xss_subject,
            body_text='Body',
            user_is_important=True
        )

        notif = create_important_notification(email)
        self.assertNotIn('<script>', notif.title)
        self.assertNotIn('<script>', notif.message)
        self.assertNotIn('<b>', notif.title)

    def test_create_test_notification(self):
        """Verify test notification creation and distinct label."""
        notif = create_test_notification(self.user)
        self.assertIn('Test Alert', notif.title)
        self.assertEqual(notif.importance_source, Notification.SOURCE_SYSTEM)
        self.assertEqual(notif.user, self.user)


class Phase6NotificationAPITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user1 = User.objects.create_user(
            username='userone',
            email='userone@example.com',
            password='Password123!'
        )
        self.user2 = User.objects.create_user(
            username='usertwo',
            email='usertwo@example.com',
            password='Password123!'
        )
        self.client.force_login(self.user1)

        self.notif1 = Notification.objects.create(
            user=self.user1,
            title='User 1 Alert',
            message='Alert for user 1',
            notification_type=Notification.TYPE_IMPORTANT_EMAIL,
            priority=Notification.PRIORITY_HIGH
        )
        self.notif2 = Notification.objects.create(
            user=self.user2,
            title='User 2 Alert',
            message='Alert for user 2',
            notification_type=Notification.TYPE_IMPORTANT_EMAIL,
            priority=Notification.PRIORITY_HIGH
        )

    def test_notifications_center_page_loads(self):
        """GET /notifications/ returns HTTP 200 with tab counts."""
        res = self.client.get('/notifications/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'User 1 Alert')
        self.assertNotContains(res, 'User 2 Alert')  # Cross-user isolation!

    def test_notifications_search(self):
        """Verify searching notifications by keyword."""
        res = self.client.get('/notifications/?q=Alert')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context['notifications']), 1)
        self.assertEqual(res.context['notifications'][0].title, 'User 1 Alert')

        res_none = self.client.get('/notifications/?q=NonExistentKeywordXYZ')
        self.assertEqual(res_none.status_code, 200)
        self.assertEqual(len(res_none.context['notifications']), 0)
        self.assertContains(res_none, 'There are no notifications matching your current filter')

    def test_mark_as_read_endpoint(self):
        """POST /notifications/<id>/read/ marks is_read=True with timestamp."""
        res = self.client.post(
            f'/notifications/{self.notif1.id}/read/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])

        self.notif1.refresh_from_db()
        self.assertTrue(self.notif1.is_read)
        self.assertIsNotNone(self.notif1.read_at)

    def test_mark_as_read_cross_user_forbidden(self):
        """User 1 cannot mark User 2's notification as read (HTTP 404)."""
        res = self.client.post(f'/notifications/{self.notif2.id}/read/')
        self.assertEqual(res.status_code, 404)
        self.notif2.refresh_from_db()
        self.assertFalse(self.notif2.is_read)

    def test_mark_all_read_endpoint(self):
        """POST /notifications/read-all/ marks only caller's notifications."""
        # Create second unread for user 1
        Notification.objects.create(
            user=self.user1,
            title='Second Alert',
            message='Msg',
            is_read=False
        )
        self.assertEqual(get_unread_count(self.user1), 2)
        self.assertEqual(get_unread_count(self.user2), 1)

        res = self.client.post('/notifications/read-all/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(get_unread_count(self.user1), 0)
        self.assertEqual(get_unread_count(self.user2), 1)  # User 2 unaffected!

    def test_delete_notification_endpoint(self):
        """POST /notifications/<id>/delete/ deletes notification record."""
        res = self.client.post(
            f'/notifications/{self.notif1.id}/delete/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(Notification.objects.filter(id=self.notif1.id).exists())

    def test_delete_notification_cross_user_forbidden(self):
        """User 1 cannot delete User 2's notification."""
        res = self.client.post(
            f'/notifications/{self.notif2.id}/delete/',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 404)
        self.assertTrue(Notification.objects.filter(id=self.notif2.id).exists())

    def test_unread_count_endpoint(self):
        """GET /notifications/unread-count/ returns accurate JSON."""
        res = self.client.get('/notifications/unread-count/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['unread_count'], 1)

    def test_update_notification_preferences_endpoint(self):
        """POST /settings/notifications/ updates preferences."""
        payload = {
            'important_sender_enabled': 'on',
            'sound_enabled': 'on',
            # Leaving 'ai_important_enabled' and 'browser_enabled' unchecked
        }
        res = self.client.post('/settings/notifications/', data=payload)
        self.assertEqual(res.status_code, 302)

        pref = NotificationPreference.get_for_user(self.user1)
        self.assertTrue(pref.important_sender_enabled)
        self.assertTrue(pref.sound_enabled)
        self.assertFalse(pref.ai_important_enabled)
        self.assertFalse(pref.browser_enabled)

    def test_test_notification_endpoint(self):
        """POST /notifications/test/ creates and broadcasts test alert."""
        res = self.client.post('/notifications/test/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(Notification.objects.filter(user=self.user1, title__icontains='Test Alert').exists())


class Phase6PushSubscriptionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='pushuser',
            email='pushuser@example.com',
            password='Password123!'
        )
        self.client.force_login(self.user)

    def test_push_subscribe_endpoint(self):
        """POST /notifications/push/subscribe/ persists PushSubscription."""
        payload = {
            'endpoint': 'https://fcm.googleapis.com/fcm/send/fake-endpoint-token',
            'p256dh': 'fake-p256dh-key',
            'auth': 'fake-auth-key',
            'user_agent': 'Mozilla/5.0 Test Browser'
        }
        res = self.client.post(
            '/notifications/push/subscribe/',
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])

        sub = PushSubscription.objects.get(user=self.user)
        self.assertEqual(sub.endpoint, payload['endpoint'])
        self.assertEqual(sub.p256dh, payload['p256dh'])
        self.assertEqual(sub.auth, payload['auth'])

    def test_push_notification_service_handles_expired_subscription(self):
        """Verify web push prunes subscription when provider returns 410 Gone."""
        sub = PushSubscription.objects.create(
            user=self.user,
            endpoint='https://push.example.com/expired-sub',
            p256dh='fake_key',
            auth='fake_auth'
        )
        notif = Notification.objects.create(
            user=self.user,
            title='Push Alert',
            message='Push body'
        )

        with patch('django.conf.settings.WEB_PUSH_ENABLED', True), \
             patch('django.conf.settings.VAPID_PRIVATE_KEY', 'fake_vapid_key'), \
             patch('pywebpush.webpush') as mock_webpush:
            from pywebpush import WebPushException
            mock_resp = MagicMock()
            mock_resp.status_code = 410  # 410 Gone indicates expired endpoint
            mock_webpush.side_effect = WebPushException("Subscription expired", response=mock_resp)

            send_push_notification(notif)
            # The expired subscription should be pruned from the database
            self.assertFalse(PushSubscription.objects.filter(id=sub.id).exists())


class Phase6GmailAndAISyncIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='integrationuser',
            email='intuser@example.com',
            password='Password123!'
        )
        self.account = GmailAccount.objects.create(
            user=self.user,
            email_address='intuser@gmail.com',
            is_connected=True
        )
        self.account.set_access_token('access_token')
        self.account.set_refresh_token('refresh_token')
        self.account.save()

        # Configure VIP Sender
        PrioritySender.objects.create(
            user=self.user,
            email_address='professor@college.edu',
            display_name='Prof. Smith',
            is_important=True,
            notification_enabled=True
        )

    def test_gmail_sync_creates_important_sender_notification(self):
        """Newly synced email matching an important sender creates notification."""
        parsed_email = {
            'gmail_message_id': 'msg_sync_1',
            'gmail_thread_id': 'th_1',
            'gmail_history_id': 'hist_1',
            'sender_name': 'Prof. Smith',
            'sender_email': 'professor@college.edu',
            'recipient_email': 'intuser@gmail.com',
            'cc': '',
            'bcc': '',
            'subject': 'Exam Schedule Change',
            'snippet': 'Exam rescheduled to next week',
            'body_text': 'Exam rescheduled to next week Monday.',
            'body_html': '<p>Exam rescheduled to next week Monday.</p>',
            'received_at': timezone.now(),
            'gmail_labels': ['INBOX', 'UNREAD'],
            'is_read': False,
            'is_starred': False,
            'gmail_is_important': False,
            'has_attachments': False,
            'attachments': []
        }

        sync_service = GmailSyncService()
        is_new = sync_service._save_or_update_email(self.account, parsed_email)
        self.assertTrue(is_new)

        email = Email.objects.get(gmail_message_id='msg_sync_1')
        notif = Notification.objects.filter(email=email).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.importance_source, Notification.SOURCE_IMPORTANT_SENDER)
        self.assertEqual(notif.title, 'Prof. Smith')

    def test_gmail_sync_updating_existing_email_does_not_duplicate_notification(self):
        """Syncing an existing email updates record without creating a second notification."""
        parsed_email = {
            'gmail_message_id': 'msg_sync_2',
            'gmail_thread_id': 'th_2',
            'gmail_history_id': 'hist_2',
            'sender_name': 'Prof. Smith',
            'sender_email': 'professor@college.edu',
            'recipient_email': 'intuser@gmail.com',
            'cc': '',
            'bcc': '',
            'subject': 'Syllabus Review',
            'snippet': 'Review attached.',
            'body_text': 'Review attached.',
            'body_html': '<p>Review attached.</p>',
            'received_at': timezone.now(),
            'gmail_labels': ['INBOX', 'UNREAD'],
            'is_read': False,
            'is_starred': False,
            'gmail_is_important': False,
            'has_attachments': False,
            'attachments': []
        }

        sync_service = GmailSyncService()
        is_new_1 = sync_service._save_or_update_email(self.account, parsed_email)
        self.assertTrue(is_new_1)
        self.assertEqual(Notification.objects.filter(email__gmail_message_id='msg_sync_2').count(), 1)

        # Subsequent sync (e.g. read status changed)
        parsed_email['is_read'] = True
        is_new_2 = sync_service._save_or_update_email(self.account, parsed_email)
        self.assertFalse(is_new_2)
        # Still exactly 1 notification
        self.assertEqual(Notification.objects.filter(email__gmail_message_id='msg_sync_2').count(), 1)

    def test_ai_classifier_triggers_notification_when_important(self):
        """AI Classifier setting ai_is_important triggers notification."""
        from ai_engine.classifier import EmailClassifier

        mock_payload = {
            "category": "Education",
            "priority": "High",
            "is_important": True,
            "confidence": 0.95,
            "reason": "Midterm test schedule announcement"
        }
        mock_provider = MagicMock()
        mock_provider.classify.return_value = json.dumps(mock_payload)
        classifier = EmailClassifier(provider=mock_provider)

        email = Email.objects.create(
            user=self.user,
            sender_name='Registrar',
            sender_email='registrar@college.edu',
            recipient_email=self.user.email,
            subject='Fall Midterm Dates',
            body_text='Midterm dates are now released.'
        )

        classifier.classify_email(email)
        email.refresh_from_db()
        self.assertTrue(email.ai_is_important)

        notif = Notification.objects.filter(email=email).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.notification_type, Notification.TYPE_AI_IMPORTANT)
        self.assertEqual(notif.importance_source, Notification.SOURCE_AI)

    def test_notification_retention_cleanup(self):
        """cleanup_old_notifications deletes notifications older than retention days."""
        old_notif = Notification.objects.create(
            user=self.user,
            title='Old Alert',
            message='Old body',
            notification_type=Notification.TYPE_SYSTEM
        )
        # Artificially age the notification past 90 days
        cutoff = timezone.now() - timedelta(days=95)
        Notification.objects.filter(id=old_notif.id).update(created_at=cutoff)

        recent_notif = Notification.objects.create(
            user=self.user,
            title='Fresh Alert',
            message='Fresh body',
            notification_type=Notification.TYPE_SYSTEM
        )

        deleted_count = cleanup_old_notifications(days=90)
        self.assertEqual(deleted_count, 1)
        self.assertFalse(Notification.objects.filter(id=old_notif.id).exists())
        self.assertTrue(Notification.objects.filter(id=recent_notif.id).exists())


class Phase6WebSocketSecurityTests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            username='user_a',
            email='user_a@example.com',
            password='Password123!'
        )
        self.user_b = User.objects.create_user(
            username='user_b',
            email='user_b@example.com',
            password='Password123!'
        )

    async def test_websocket_rejects_unauthenticated_connection(self):
        """Unauthenticated WebSocket client must be immediately disconnected with code 4001."""
        from channels.testing import WebsocketCommunicator
        from notifications.consumers import NotificationConsumer

        communicator = WebsocketCommunicator(NotificationConsumer.as_asgi(), "/ws/notifications/")
        communicator.scope['user'] = MagicMock(is_authenticated=False)

        connected, subprotocol = await communicator.connect()
        self.assertFalse(connected)
        await communicator.disconnect()

    async def test_websocket_accepts_authenticated_connection(self):
        """Authenticated WebSocket client connects and receives initial state."""
        from channels.testing import WebsocketCommunicator
        from notifications.consumers import NotificationConsumer

        communicator = WebsocketCommunicator(NotificationConsumer.as_asgi(), "/ws/notifications/")
        communicator.scope['user'] = self.user_a

        connected, subprotocol = await communicator.connect()
        self.assertTrue(connected)

        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'connection_established')
        self.assertEqual(response['user'], self.user_a.email)

        await communicator.disconnect()

    async def test_websocket_user_isolation(self):
        """User A receives only User A's channel messages; User B's stream never receives them."""
        from channels.testing import WebsocketCommunicator
        from channels.layers import get_channel_layer
        from notifications.consumers import NotificationConsumer

        channel_layer = get_channel_layer()

        comm_a = WebsocketCommunicator(NotificationConsumer.as_asgi(), "/ws/notifications/")
        comm_a.scope['user'] = self.user_a
        await comm_a.connect()
        await comm_a.receive_json_from()  # Handshake

        comm_b = WebsocketCommunicator(NotificationConsumer.as_asgi(), "/ws/notifications/")
        comm_b.scope['user'] = self.user_b
        await comm_b.connect()
        await comm_b.receive_json_from()  # Handshake

        # Broadcast payload targeting User A group only
        payload = {
            "type": "notification_message",
            "title": "Private for User A",
            "message": "Secret message"
        }
        await channel_layer.group_send(
            f"user_{self.user_a.id}_notifications",
            {
                "type": "notification.broadcast",
                "data": payload
            }
        )

        # User A receives message
        received_a = await comm_a.receive_json_from()
        self.assertEqual(received_a['title'], "Private for User A")

        # User B should NOT receive anything
        nothing_received = await comm_b.receive_nothing(timeout=0.2)
        self.assertTrue(nothing_received)

        await comm_a.disconnect()
        await comm_b.disconnect()
