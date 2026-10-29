from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from emails.models import Email, EmailCategory, EmailPriority

User = get_user_model()

class ViewRoutesTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='activeuser',
            email='active@example.com',
            password='Password123!',
            first_name='Active',
            last_name='User'
        )
        self.email = Email.objects.create(
            user=self.user,
            sender_name='Company HR',
            sender_email='hr@company.com',
            recipient_email=self.user.email,
            subject='Offer Letter Discussion',
            body_text='We are delighted to extend this offer.',
            category=EmailCategory.JOB_INTERNSHIP,
            priority=EmailPriority.HIGH,
            is_important=True
        )

    def test_anonymous_user_redirects_to_login(self):
        """Anonymous requests to protected endpoints must redirect to login"""
        protected_routes = [
            'dashboard',
            'inbox',
            'important',
            'pinned',
            'categories',
            'priority_senders',
            'notifications',
            'ai_summary',
            'ai_reply',
            'settings',
            'profile',
            'password_change',
        ]
        for route_name in protected_routes:
            url = reverse(route_name)
            response = self.client.get(url)
            self.assertEqual(
                response.status_code, 302,
                f"Route '{route_name}' ({url}) should redirect anonymous users"
            )
            self.assertIn('/login/', response.url)

    def test_auth_pages_load_for_anonymous_users(self):
        """Login and Register pages must load with HTTP 200"""
        login_res = self.client.get('/login/')
        self.assertEqual(login_res.status_code, 200)
        self.assertContains(login_res, 'Sign in with Google')

        register_res = self.client.get('/register/')
        self.assertEqual(register_res.status_code, 200)
        self.assertContains(register_res, 'Sign up with Google')

    def test_authenticated_user_access(self):
        """Authenticated users should be able to access all major workspace views"""
        self.client.force_login(self.user)

        views_to_test = [
            ('dashboard', 200, 'intelligent email workspace'),
            ('inbox', 200, 'Inbox'),
            ('important', 200, 'Important Emails'),
            ('pinned', 200, 'Pinned Emails'),
            ('categories', 200, 'Email Categories'),
            ('priority_senders', 200, 'Priority Senders'),
            ('notifications', 200, 'Notification Center'),
            ('ai_summary', 200, "Today's Email Summary"),
            ('ai_reply', 200, 'AI Reply Assistant'),
            ('settings', 200, 'Settings & Configurations'),
        ]

        for route_name, expected_status, content_snippet in views_to_test:
            url = reverse(route_name)
            response = self.client.get(url)
            self.assertEqual(
                response.status_code, expected_status,
                f"Route {route_name} failed with status {response.status_code}"
            )
            self.assertContains(
                response, content_snippet,
                msg_prefix=f"Expected snippet '{content_snippet}' in route {route_name}"
            )

    def test_email_detail_view(self):
        """Verify email detail page loads and marks email as read"""
        self.client.force_login(self.user)
        url = reverse('emails:detail', kwargs={'email_id': self.email.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Offer Letter Discussion')
        self.email.refresh_from_db()
        self.assertTrue(self.email.is_read)

    def test_inbox_email_detail_view(self):
        """Verify /inbox/<id>/ loads the email detail page with HTTP 200"""
        self.client.force_login(self.user)
        response = self.client.get(f'/inbox/{self.email.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Offer Letter Discussion')
        self.email.refresh_from_db()
        self.assertTrue(self.email.is_read)

    def test_category_detail_view(self):
        """Verify category detail view displays emails under that category"""
        self.client.force_login(self.user)
        url = reverse('category_detail', kwargs={'category_name': 'Job & Internship'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Offer Letter Discussion')

    @override_settings(GOOGLE_CLIENT_ID='', GOOGLE_OAUTH_CLIENT_ID='')
    def test_google_login_unconfigured_guidance(self):
        """Verify Google login redirects cleanly with guidance when client_id is empty"""
        response = self.client.get(reverse('accounts:google_login'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_inbox_email_detail_view_tabs_and_code(self):
        """Verify email detail page includes interactive tabs, iframe container, and HTML source code"""
        self.client.force_login(self.user)
        # Create an email with leaked outlook CSS block to test cleaning
        dirty_email = Email.objects.create(
            user=self.user,
            subject='Internshala Web Dev Update',
            sender_name='Internshala Trainings',
            sender_email='jos@mail.internshala.com',
            recipient_email=self.user.email,
            body_html="""#outlook a { padding:0; } body { width:100%!important; }
<div class="content"><p>Ready to build skills for Web Development roles?</p></div>""",
            body_text="""#outlook a { padding:0; } body { width:100%!important; }
Ready to build skills for Web Development roles?""",
            received_at=timezone.now(),
            gmail_labels='INBOX,UNREAD,IMPORTANT,CATEGORY_UPDATES'
        )

        response = self.client.get(reverse('inbox_detail', kwargs={'email_id': dirty_email.id}))
        self.assertEqual(response.status_code, 200)

        # Tab navigation checks
        self.assertContains(response, 'Formatted Email')
        self.assertContains(response, 'Plain Text')
        self.assertContains(response, 'HTML Source Code')
        self.assertContains(response, 'Headers & Meta')

        # Sandboxed iframe checks
        self.assertContains(response, 'id="emailContentFrame"')
        self.assertContains(response, 'sandbox="allow-popups allow-popups-to-escape-sandbox allow-same-origin"')

        # Ensure raw leaked CSS header is stripped from display
        self.assertNotContains(response, '#outlook a { padding:0; }')

        # Ensure code block contains clean HTML and copy button
        self.assertContains(response, 'id="rawHtmlCodeBlock"')
        self.assertContains(response, 'Ready to build skills for Web Development roles?')
        self.assertContains(response, 'Copy HTML Code')

        # Ensure formatted labels badges are present
        self.assertContains(response, 'Updates')
        self.assertContains(response, 'Important')

    def test_email_raw_html_endpoint(self):
        """Verify email_raw_html_view returns standalone clean HTML document"""
        self.client.force_login(self.user)
        url_inbox = reverse('inbox_raw_html', kwargs={'email_id': self.email.id})
        url_emails = reverse('emails:raw_html', kwargs={'email_id': self.email.id})

        resp_inbox = self.client.get(url_inbox)
        self.assertEqual(resp_inbox.status_code, 200)
        self.assertIn('text/html', resp_inbox['Content-Type'])
        self.assertContains(resp_inbox, 'We are delighted to extend this offer.')

        resp_emails = self.client.get(url_emails)
        self.assertEqual(resp_emails.status_code, 200)
        self.assertIn('text/html', resp_emails['Content-Type'])


