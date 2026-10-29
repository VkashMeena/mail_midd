import io
from PIL import Image
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from accounts.models import UserProfile
from emails.models import Email, PrioritySender, EmailCategory, EmailPriority
from notifications.models import Notification

User = get_user_model()

def create_test_image():
    """Generates a small in-memory valid JPEG image for upload testing."""
    file_obj = io.BytesIO()
    image = Image.new('RGB', (100, 100), color=(37, 99, 235))
    image.save(file_obj, format='JPEG')
    file_obj.seek(0)
    return SimpleUploadedFile('test_avatar.jpg', file_obj.read(), content_type='image/jpeg')


class AuthenticationAndRegistrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='existinguser',
            email='existing@example.com',
            password='InitialPassword123!',
            first_name='Existing',
            last_name='User'
        )

    def test_registration_success(self):
        """User registration with unique email and valid passwords redirects to login"""
        response = self.client.post(reverse('accounts:register'), {
            'full_name': 'New User',
            'email': 'newuser@example.com',
            'password': 'StrongPassword123!',
            'confirm_password': 'StrongPassword123!'
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

        # Verify user created in database with email
        new_user = User.objects.filter(email='newuser@example.com').first()
        self.assertIsNotNone(new_user)
        self.assertEqual(new_user.first_name, 'New')
        self.assertEqual(new_user.last_name, 'User')
        self.assertTrue(hasattr(new_user, 'profile'))

    def test_registration_duplicate_email(self):
        """Registration with an already registered email must be rejected"""
        response = self.client.post(reverse('accounts:register'), {
            'full_name': 'Duplicate Attempt',
            'email': 'existing@example.com',
            'password': 'AnotherPassword123!',
            'confirm_password': 'AnotherPassword123!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'email', "An account with this email address already exists.")

    def test_registration_password_mismatch(self):
        """Registration with mismatched passwords must be rejected"""
        response = self.client.post(reverse('accounts:register'), {
            'full_name': 'Mismatch Test',
            'email': 'mismatch@example.com',
            'password': 'Password12345!',
            'confirm_password': 'DifferentPassword!'
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], 'confirm_password', "Passwords do not match.")

    def test_login_success_with_email(self):
        """User can log in using their email address"""
        response = self.client.post(reverse('accounts:login'), {
            'username': 'existing@example.com',
            'password': 'InitialPassword123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/', response.url)

    def test_login_success_with_username(self):
        """User can log in using their username"""
        response = self.client.post(reverse('accounts:login'), {
            'username': 'existinguser',
            'password': 'InitialPassword123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/', response.url)

    def test_login_invalid_credentials_generic_message(self):
        """Failed login displays generic error message without account enumeration"""
        response = self.client.post(reverse('accounts:login'), {
            'username': 'nonexistent@example.com',
            'password': 'WrongPassword123!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password.")

    def test_logout_clears_session(self):
        """Logout terminates active session and redirects to login"""
        self.client.force_login(self.user)
        response = self.client.get(reverse('accounts:logout'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
        # Attempting to access dashboard must now redirect
        dash_response = self.client.get(reverse('dashboard'))
        self.assertEqual(dash_response.status_code, 302)


class ProfileAndPasswordManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='profileuser',
            email='profile@example.com',
            password='InitialPassword123!',
            first_name='Vikash',
            last_name='Kumar'
        )
        self.client.force_login(self.user)

    def test_profile_view_loads_user_data(self):
        """Profile page renders user details, email as read-only, and timezone"""
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'profile@example.com')
        self.assertContains(response, 'Vikash Kumar')

    def test_profile_edit_and_avatar_upload(self):
        """Profile updates display name, timezone, theme, and valid avatar image"""
        test_image = create_test_image()
        response = self.client.post(reverse('profile'), {
            'display_name': 'Vikash K.',
            'timezone': 'Asia/Kolkata',
            'theme': 'dark',
            'avatar': test_image
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.display_name, 'Vikash K.')
        self.assertEqual(self.user.profile.timezone, 'Asia/Kolkata')
        self.assertEqual(self.user.profile.theme, 'dark')
        self.assertTrue(bool(self.user.profile.avatar))

    def test_profile_avatar_rejects_executable_or_invalid_extension(self):
        """Avatar upload rejects non-image or executable files"""
        fake_executable = SimpleUploadedFile('malicious.exe', b'BINARYEXEC', content_type='application/octet-stream')
        response = self.client.post(reverse('profile'), {
            'display_name': 'Test',
            'timezone': 'UTC',
            'theme': 'light',
            'avatar': fake_executable
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].has_error('avatar'))

    def test_password_change_success_maintains_session(self):
        """Password change updates password hash and preserves session"""
        response = self.client.post(reverse('accounts:password_change'), {
            'old_password': 'InitialPassword123!',
            'new_password1': 'NewSecurePassword123!',
            'new_password2': 'NewSecurePassword123!'
        })
        self.assertEqual(response.status_code, 302)

        # Verify new password works
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewSecurePassword123!'))

        # Verify session is still active
        dash_response = self.client.get(reverse('dashboard'))
        self.assertEqual(dash_response.status_code, 200)


class UserDataIsolationTests(TestCase):
    def setUp(self):
        self.client_a = Client()
        self.client_b = Client()

        self.user_a = User.objects.create_user(
            username='usera',
            email='usera@example.com',
            password='Password123!'
        )
        self.user_b = User.objects.create_user(
            username='userb',
            email='userb@example.com',
            password='Password123!'
        )

        # Seed data for User A
        self.email_a = Email.objects.create(
            user=self.user_a,
            sender_name='Confidential Sender',
            sender_email='secret@company.com',
            recipient_email=self.user_a.email,
            subject='Confidential User A Information',
            body_text='Private body for User A only',
            category=EmailCategory.WORK,
            priority=EmailPriority.HIGH
        )

        self.sender_a = PrioritySender.objects.create(
            user=self.user_a,
            email_address='vip@usera.com',
            display_name='VIP User A Contact',
            priority=EmailPriority.HIGH
        )

        self.notif_a = Notification.objects.create(
            user=self.user_a,
            title='Private Alert User A',
            message='Alert for user A only'
        )

    def test_user_b_cannot_view_user_a_email(self):
        """User B requesting User A's email returns 404"""
        self.client_b.force_login(self.user_b)
        url = reverse('emails:detail', kwargs={'email_id': self.email_a.id})
        response = self.client_b.get(url)
        self.assertEqual(response.status_code, 404)

    def test_user_b_cannot_delete_user_a_priority_sender(self):
        """User B cannot delete User A's priority sender"""
        self.client_b.force_login(self.user_b)
        url = reverse('emails:priority_sender_delete', kwargs={'sender_id': self.sender_a.id})
        response = self.client_b.post(url)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(PrioritySender.objects.filter(id=self.sender_a.id).exists())

    def test_user_b_inbox_does_not_contain_user_a_emails(self):
        """User B inbox query returns only User B records"""
        self.client_b.force_login(self.user_b)
        response = self.client_b.get(reverse('inbox'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Confidential User A Information')
