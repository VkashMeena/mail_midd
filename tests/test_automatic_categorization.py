import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from emails.models import Email, PrioritySender, AIStatus, EmailImportance
from emails.services import get_category_counts
from ai_engine.constants import PRIMARY_CATEGORIES
from ai_engine.classifier import EmailClassifier
from ai_engine.schemas import AIClassificationResult

User = get_user_model()


class AutomaticAICategorizationObjectiveTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='auto_ai_user',
            email='auto_ai_user@example.com',
            password='Password123!'
        )
        self.classifier = EmailClassifier()

    def test_example_1_interview_scheduled_job_internship(self):
        email = Email.objects.create(
            user=self.user,
            sender_name="Recruiter Jane",
            sender_email="recruiter@techcorp.com",
            subject="Interview Scheduled for Software Developer Position",
            body_text="Hi, we would like to invite you for a technical interview scheduled for tomorrow at 2 PM.",
            ai_status=AIStatus.PENDING
        )
        payload = self.classifier.prepare_email_payload(email)
        result = self.classifier.classify_by_objective(email, payload)

        self.assertEqual(result.category, "Job/Internship")
        self.assertEqual(result.priority, "High")
        self.assertTrue(result.importance)
        self.assertTrue(result.action_required)
        self.assertIn("Interview", result.objective)

    def test_example_2_dbms_internal_examination_education(self):
        email = Email.objects.create(
            user=self.user,
            sender_name="Prof. Sharma",
            sender_email="examcell@engineering.edu.in",
            subject="Tomorrow's DBMS Internal Examination",
            body_text="Dear students, please be informed that the DBMS internal examination will be held tomorrow at 10 AM in Hall B.",
            ai_status=AIStatus.PENDING
        )
        payload = self.classifier.prepare_email_payload(email)
        result = self.classifier.classify_by_objective(email, payload)

        self.assertEqual(result.category, "Education")
        self.assertEqual(result.priority, "High")
        self.assertTrue(result.importance)
        self.assertTrue(result.action_required)
        self.assertIn("examination", result.objective.lower())

    def test_example_3_sbi_account_transaction_finance(self):
        email = Email.objects.create(
            user=self.user,
            sender_name="SBI Alerts",
            sender_email="alerts@sbi.co.in",
            subject="Your SBI Account Transaction",
            body_text="Dear Customer, your SBI account XX1234 has been debited by INR 2,500 on 06-Oct-2026. Available balance: INR 45,000.",
            ai_status=AIStatus.PENDING
        )
        payload = self.classifier.prepare_email_payload(email)
        result = self.classifier.classify_by_objective(email, payload)

        self.assertEqual(result.category, "Finance")
        self.assertEqual(result.priority, "High")
        self.assertTrue(result.importance)
        self.assertIn("transaction", result.objective.lower())

    def test_example_4_amazon_sale_promotion(self):
        email = Email.objects.create(
            user=self.user,
            sender_name="Amazon Deals",
            sender_email="deals@amazon.in",
            subject="50% Off Amazon Sale",
            body_text="Great Indian Festival is here! Enjoy 50% off on electronics and apparel. Limited time deal, shop now!",
            ai_status=AIStatus.PENDING
        )
        payload = self.classifier.prepare_email_payload(email)
        result = self.classifier.classify_by_objective(email, payload)

        self.assertEqual(result.category, "Promotion")
        self.assertEqual(result.priority, "Low")
        self.assertFalse(result.importance)
        self.assertFalse(result.action_required)

    def test_shopping_order_confirmation(self):
        email = Email.objects.create(
            user=self.user,
            sender_name="Flipkart Orders",
            sender_email="orders@flipkart.com",
            subject="Order Placed Successfully: Order #OD987654321",
            body_text="Your order has been confirmed and shipped via BlueDart. Tracking ID: BD123456.",
            ai_status=AIStatus.PENDING
        )
        payload = self.classifier.prepare_email_payload(email)
        result = self.classifier.classify_by_objective(email, payload)

        self.assertEqual(result.category, "Shopping")
        self.assertEqual(result.priority, "Medium")

    def test_newsletter_digest(self):
        email = Email.objects.create(
            user=self.user,
            sender_name="Python Weekly",
            sender_email="newsletter@pythonweekly.com",
            subject="Python Weekly Newsletter Issue 450",
            body_text="Curated articles, libraries, and discussions from the Python ecosystem this week.",
            ai_status=AIStatus.PENDING
        )
        payload = self.classifier.prepare_email_payload(email)
        result = self.classifier.classify_by_objective(email, payload)

        self.assertEqual(result.category, "Newsletter")
        self.assertEqual(result.priority, "Low")
        self.assertFalse(result.importance)

    def test_security_notification_alert(self):
        email = Email.objects.create(
            user=self.user,
            sender_name="Google Security",
            sender_email="no-reply@accounts.google.com",
            subject="Security Alert: New Sign-in from Windows",
            body_text="We detected a new login to your Google Account from a Windows device. Verification code: 492810.",
            ai_status=AIStatus.PENDING
        )
        payload = self.classifier.prepare_email_payload(email)
        result = self.classifier.classify_by_objective(email, payload)

        self.assertEqual(result.category, "Notification")
        self.assertEqual(result.priority, "High")
        self.assertTrue(result.importance)

    def test_work_sprint_meeting(self):
        email = Email.objects.create(
            user=self.user,
            sender_name="Product Manager",
            sender_email="pm@mycompany.com",
            subject="Sprint Planning & Standup Agenda for Q4",
            body_text="Team, join the sprint planning meeting tomorrow at 10 AM on Zoom. Jira tickets are linked in confluence.",
            ai_status=AIStatus.PENDING
        )
        payload = self.classifier.prepare_email_payload(email)
        result = self.classifier.classify_by_objective(email, payload)

        self.assertEqual(result.category, "Work")
        self.assertEqual(result.priority, "High")
        self.assertTrue(result.importance)

    def test_personal_correspondence(self):
        email = Email.objects.create(
            user=self.user,
            sender_name="Alex Friend",
            sender_email="alex.friend@gmail.com",
            subject="Hey, are we still meeting for dinner tonight?",
            body_text="Hey! Just wanted to catch up and confirm dinner tonight at 7. Let me know!",
            ai_status=AIStatus.PENDING
        )
        payload = self.classifier.prepare_email_payload(email)
        result = self.classifier.classify_by_objective(email, payload)

        self.assertEqual(result.category, "Personal")

    def test_classify_email_with_fallback_persists_objective_and_action_required(self):
        # When external provider fails (e.g. quota exhausted / network down), fallback persists cleanly
        email = Email.objects.create(
            user=self.user,
            sender_name="Campus Placement Cell",
            sender_email="placement@university.edu",
            subject="Interview Scheduled for Software Developer Position",
            body_text="Your interview is scheduled with Google for the Software Engineer role.",
            ai_status=AIStatus.PENDING
        )

        with patch.object(self.classifier.provider, 'classify', side_effect=Exception("API Quota Exhausted")):
            result = self.classifier.classify_email(email)

        self.assertEqual(result.category, "Job/Internship")
        self.assertEqual(result.priority, "High")
        self.assertTrue(result.importance)

        email.refresh_from_db()
        self.assertEqual(email.ai_category, "Job/Internship")
        self.assertEqual(email.ai_status, AIStatus.COMPLETED)
        self.assertEqual(email.ai_priority, "High")
        self.assertTrue(email.ai_is_important)
        self.assertTrue(email.action_required)
        self.assertIn("Interview", email.ai_objective)

    def test_priority_sender_overrides_ai(self):
        PrioritySender.objects.create(
            user=self.user,
            email_address="hod@college.edu",
            display_name="HOD College",
            priority="High",
            is_important=True
        )

        email = Email.objects.create(
            user=self.user,
            sender_name="Dr. Smith",
            sender_email="hod@college.edu",
            subject="Casual note",
            body_text="General check in",
            ai_status=AIStatus.PENDING
        )

        # Provider says Low / not important
        mock_provider = MagicMock()
        mock_provider.classify.return_value = json.dumps({
            "category": "Other",
            "importance": False,
            "priority": "Low",
            "confidence": 0.8,
            "reason": "General check in"
        })
        classifier = EmailClassifier(provider=mock_provider)
        classifier.classify_email(email)

        email.refresh_from_db()
        # Matched priority sender rules take precedence!
        self.assertTrue(email.effective_importance)
        self.assertEqual(email.effective_priority, "High")
        self.assertEqual(email.effective_sender_name, "HOD College")

    def test_category_counts_returns_all_10_primary_categories(self):
        # Create an email in Education
        Email.objects.create(
            user=self.user,
            sender_email="school@edu.com",
            subject="Class",
            ai_category="Education",
            ai_status=AIStatus.COMPLETED
        )

        # Create an email in Job/Internship
        Email.objects.create(
            user=self.user,
            sender_email="hr@jobs.com",
            subject="Offer",
            ai_category="Job/Internship",
            ai_status=AIStatus.COMPLETED
        )

        counts = get_category_counts(self.user)
        self.assertEqual(len(counts), 10)
        category_names = [c['name'] for c in counts]
        self.assertEqual(category_names, PRIMARY_CATEGORIES)

        edu_item = next(c for c in counts if c['name'] == 'Education')
        job_item = next(c for c in counts if c['name'] == 'Job/Internship')
        self.assertEqual(edu_item['count'], 1)
        self.assertEqual(job_item['count'], 1)
