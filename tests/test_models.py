from django.test import TestCase
from django.contrib.auth import get_user_model
from emails.models import Email, PrioritySender, EmailCategory, EmailPriority, EmailImportance
from notifications.models import Notification
from accounts.models import UserProfile

User = get_user_model()

class ModelFoundationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='TestPassword123!',
            first_name='Test',
            last_name='User'
        )

    def test_user_profile_signal(self):
        """Verify UserProfile is automatically generated on User creation"""
        self.assertTrue(hasattr(self.user, 'profile'))
        self.assertEqual(self.user.profile.get_display_name(), 'Test User')
        self.assertEqual(self.user.profile.theme, 'light')

    def test_email_model_creation(self):
        """Verify Email model fields and helper metadata"""
        email = Email.objects.create(
            user=self.user,
            sender_name='HOD College',
            sender_email='hod@college.edu',
            recipient_email=self.user.email,
            subject='Exam Schedule Notice',
            body_text='Please review the schedule attached.',
            category=EmailCategory.EDUCATION,
            priority=EmailPriority.HIGH,
            is_important=True
        )
        self.assertEqual(email.category, 'Education')
        self.assertEqual(email.priority, 'High')
        self.assertEqual(email.importance, EmailImportance.IMPORTANT)
        self.assertEqual(email.category_meta['icon'], 'bi-mortarboard')
        self.assertIn('danger', email.priority_meta['badge'])

    def test_priority_sender_model(self):
        """Verify PrioritySender model creation and priority meta"""
        sender = PrioritySender.objects.create(
            user=self.user,
            email_address='dean@university.edu',
            display_name='Dean Office',
            priority=EmailPriority.HIGH,
            notification_enabled=True
        )
        self.assertEqual(str(sender), 'Dean Office <dean@university.edu> (High)')
        self.assertTrue(sender.notification_enabled)

    def test_notification_model(self):
        """Verify Notification model creation and dynamic icon mapping"""
        notif = Notification.objects.create(
            user=self.user,
            title='New Alert',
            message='System alert message',
            notification_type=Notification.TYPE_IMPORTANT_EMAIL,
            priority=Notification.PRIORITY_HIGH
        )
        self.assertIn('bi-exclamation-triangle-fill', notif.icon_class)
        self.assertFalse(notif.is_read)
