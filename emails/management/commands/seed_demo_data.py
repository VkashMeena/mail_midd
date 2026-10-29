from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from emails.models import Email, PrioritySender, EmailCategory, EmailPriority, EmailImportance
from notifications.models import Notification
from gmail_integration.models import GmailAccount

User = get_user_model()

class Command(BaseCommand):
    help = 'Populates the database with realistic demo emails, priority senders, notifications, and Gmail account for UI preview'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default='demo',
            help='Username of the account to associate demo data with (default: demo)'
        )
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Remove existing demo data before seeding'
        )

    def handle(self, *args, **options):
        username = options['username']
        clean = options['clean']
        email_addr = f"{username}@example.com"

        # Get or create demo user
        user, created = User.objects.get_or_create(
            email=email_addr,
            defaults={
                'username': username,
                'first_name': 'Alex',
                'last_name': 'Morgan'
            }
        )
        if created:
            user.set_password('demo12345')
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created demo user: '{username}' ({email_addr}, Password: demo12345)"))
        else:
            # Ensure password is demo12345
            user.set_password('demo12345')
            user.save()
            self.stdout.write(self.style.NOTICE(f"Using existing user: '{username}' ({email_addr})"))

        if clean:
            Email.objects.filter(user=user, is_demo=True).delete()
            PrioritySender.objects.filter(user=user, is_demo=True).delete()
            Notification.objects.filter(user=user, is_demo=True).delete()
            GmailAccount.objects.filter(user=user).delete()
            self.stdout.write(self.style.WARNING("Cleaned previous demo records."))

        now = timezone.now()

        # Seed Priority Senders
        priority_senders_data = [
            {
                'display_name': 'HOD College',
                'email_address': 'hod@college.edu',
                'priority': EmailPriority.HIGH,
                'notification_enabled': True
            },
            {
                'display_name': 'Company HR',
                'email_address': 'hr@company.com',
                'priority': EmailPriority.HIGH,
                'notification_enabled': True
            },
            {
                'display_name': 'Dr. Sarah Jenkins (Thesis Advisor)',
                'email_address': 's.jenkins@university.org',
                'priority': EmailPriority.HIGH,
                'notification_enabled': True
            },
            {
                'display_name': 'Apex Cloud Billing',
                'email_address': 'billing@apexcloud.io',
                'priority': EmailPriority.MEDIUM,
                'notification_enabled': False
            },
        ]

        for s_data in priority_senders_data:
            PrioritySender.objects.update_or_create(
                user=user,
                email_address=s_data['email_address'],
                defaults={
                    'display_name': s_data['display_name'],
                    'priority': s_data['priority'],
                    'notification_enabled': s_data['notification_enabled'],
                    'is_active': True,
                    'is_demo': True
                }
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(priority_senders_data)} Priority Senders."))

        # Seed Demo Emails across 7 days
        emails_dataset = [
            {
                'sender_name': 'HOD College',
                'sender_email': 'hod@college.edu',
                'recipient_email': user.email,
                'subject': 'Internal Assessment Deadline & Submission Guidelines',
                'body_text': (
                    "Dear Students,\n\n"
                    "This is an urgent reminder that the submission window for the Phase 1 Internal Assessment "
                    "closes this Friday at 5:00 PM IST. Please make sure that your reports, system architecture diagrams, "
                    "and repository links are uploaded strictly via the campus student portal.\n\n"
                    "No extensions will be granted past the deadline. Reach out to the lab coordinator if you encounter "
                    "any submission portal errors.\n\n"
                    "Regards,\nProf. R. Vance\nHead of Department"
                ),
                'snippet': 'This is an urgent reminder that the submission window for the Phase 1 Internal Assessment closes this Friday...',
                'category': EmailCategory.EDUCATION,
                'priority': EmailPriority.HIGH,
                'is_important': True,
                'is_read': False,
                'is_starred': True,
                'is_pinned': True,
                'time_delta': timedelta(minutes=25)
            },
            {
                'sender_name': 'Company HR',
                'sender_email': 'hr@company.com',
                'recipient_email': user.email,
                'subject': 'Interview Schedule Confirmation — Senior Fullstack Engineer',
                'body_text': (
                    "Hi Alex,\n\n"
                    "We were thoroughly impressed with your profile and technical screening. We would love to invite you to "
                    "the next stage: the System Design and Architectural Deep Dive interview.\n\n"
                    "Details:\n"
                    "Date: Tomorrow at 2:00 PM\n"
                    "Format: Google Meet (video enabled)\n"
                    "Interviewers: VP of Engineering & Principal Architect\n\n"
                    "Please confirm your availability by responding to this email or selecting an alternate slot.\n\n"
                    "Best regards,\nTalent Acquisition Team"
                ),
                'snippet': 'We would love to invite you to the next stage: the System Design and Architectural Deep Dive interview...',
                'category': EmailCategory.JOB_INTERNSHIP,
                'priority': EmailPriority.HIGH,
                'is_important': True,
                'is_read': False,
                'is_starred': True,
                'is_pinned': True,
                'time_delta': timedelta(hours=1, minutes=15)
            },
            {
                'sender_name': 'Marcus Vance (Engineering Lead)',
                'sender_email': 'm.vance@techcorp.io',
                'recipient_email': user.email,
                'subject': 'Q3 Core Infrastructure Sprint Review & Release Notes',
                'body_text': (
                    "Team,\n\n"
                    "Great work on closing Sprint 42. Highlights include migrating our query services to indexed read replicas, "
                    "reducing p99 response times from 340ms to 48ms, and deploying the new containerized event listeners.\n\n"
                    "Let's review retro action items on Thursday morning.\n\n"
                    "Cheers,\nMarcus"
                ),
                'snippet': 'Great work on closing Sprint 42. Highlights include migrating query services to indexed read replicas...',
                'category': EmailCategory.WORK,
                'priority': EmailPriority.HIGH,
                'is_important': True,
                'is_read': True,
                'is_starred': False,
                'is_pinned': False,
                'time_delta': timedelta(hours=3, minutes=45)
            },
            {
                'sender_name': 'Apex Cloud Services',
                'sender_email': 'billing@apexcloud.io',
                'recipient_email': user.email,
                'subject': 'Monthly Invoice #INV-2026-9081 & Cost Breakdown',
                'body_text': (
                    "Hello Alex,\n\n"
                    "Your monthly invoice for account #AC-88219 has been generated. Total amount charged: $42.50.\n\n"
                    "Services used: Compute Instances, Managed Redis, Object Storage.\n"
                    "The charge will be automatically settled against your primary payment method.\n\n"
                    "Apex Cloud Finance"
                ),
                'snippet': 'Your monthly invoice for account #AC-88219 has been generated. Total amount charged: $42.50...',
                'category': EmailCategory.FINANCE,
                'priority': EmailPriority.MEDIUM,
                'is_important': False,
                'is_read': False,
                'is_starred': False,
                'is_pinned': False,
                'time_delta': timedelta(hours=6)
            },
            {
                'sender_name': 'PowerGrid Utilities',
                'sender_email': 'no-reply@powergrid.com',
                'recipient_email': user.email,
                'subject': 'Upcoming Electricity Bill Notice: Account 102941',
                'body_text': (
                    "Dear Customer,\n\n"
                    "Your electricity bill for the billing cycle ending Sept 25 is $84.20. Due date is Oct 10.\n"
                    "Avoid late fee charges by opting for automatic bank deduction or UPI autopay.\n\n"
                    "Customer Care, PowerGrid"
                ),
                'snippet': 'Your electricity bill for the billing cycle ending Sept 25 is $84.20. Due date is Oct 10...',
                'category': EmailCategory.BILLS_PAYMENTS,
                'priority': EmailPriority.MEDIUM,
                'is_important': True,
                'is_read': True,
                'is_starred': False,
                'is_pinned': False,
                'time_delta': timedelta(days=1, hours=2)
            },
            {
                'sender_name': 'SkyWing Airlines',
                'sender_email': 'itinerary@skywing.com',
                'recipient_email': user.email,
                'subject': 'Booking Confirmation: Flight SW-402 to San Francisco',
                'body_text': (
                    "Alex Morgan,\n\n"
                    "Your flight booking is confirmed! Departure: JFK Terminal 4, Oct 14 at 08:30 AM.\n"
                    "E-ticket and mobile boarding pass QR code will be available 24 hours prior to departure.\n\n"
                    "Safe travels,\nSkyWing Airlines"
                ),
                'snippet': 'Your flight booking is confirmed! Departure: JFK Terminal 4, Oct 14 at 08:30 AM...',
                'category': EmailCategory.TRAVEL,
                'priority': EmailPriority.MEDIUM,
                'is_important': True,
                'is_read': True,
                'is_starred': True,
                'is_pinned': False,
                'time_delta': timedelta(days=2, hours=4)
            },
            {
                'sender_name': 'Prime Goods Delivery',
                'sender_email': 'shipments@primegoods.com',
                'recipient_email': user.email,
                'subject': 'Your Order #PG-99214 Has Shipped',
                'body_text': (
                    "Good news! Your package containing 'Ergonomic Mechanical Keyboard' has left the fulfillment hub.\n"
                    "Estimated delivery: Tomorrow by 8:00 PM via Express Logistics.\n\n"
                    "Track package in real time using the tracking ID PG-99214-EX."
                ),
                'snippet': 'Good news! Your package containing Ergonomic Mechanical Keyboard has left the fulfillment hub...',
                'category': EmailCategory.SHOPPING,
                'priority': EmailPriority.LOW,
                'is_important': False,
                'is_read': True,
                'is_starred': False,
                'is_pinned': False,
                'time_delta': timedelta(days=2, hours=10)
            },
            {
                'sender_name': 'Clara Oswald',
                'sender_email': 'clara.oswald@gmail.com',
                'recipient_email': user.email,
                'subject': 'Weekend Hiking Trip & Cabin Reservation',
                'body_text': (
                    "Hey Alex,\n\n"
                    "I just booked the lakeside cabin for next Saturday! Let me know if you can bring the camp grill and "
                    "hiking gear. Can't wait to catch up.\n\n"
                    "Talk soon,\nClara"
                ),
                'snippet': 'I just booked the lakeside cabin for next Saturday! Let me know if you can bring the camp grill...',
                'category': EmailCategory.PERSONAL,
                'priority': EmailPriority.MEDIUM,
                'is_important': False,
                'is_read': False,
                'is_starred': True,
                'is_pinned': False,
                'time_delta': timedelta(days=3, hours=1)
            },
            {
                'sender_name': 'LinkedIn Updates',
                'sender_email': 'notifications@linkedin.com',
                'recipient_email': user.email,
                'subject': 'Sarah Lin and 4 others viewed your profile this week',
                'body_text': (
                    "Alex, see who visited your profile and who is searching for software architects with your skillset.\n"
                    "Upgrade to LinkedIn Premium to view complete profile viewer identities."
                ),
                'snippet': 'Sarah Lin and 4 others viewed your profile this week. See who visited your profile...',
                'category': EmailCategory.SOCIAL,
                'priority': EmailPriority.LOW,
                'is_important': False,
                'is_read': True,
                'is_starred': False,
                'is_pinned': False,
                'time_delta': timedelta(days=4)
            },
            {
                'sender_name': 'GitHub Security',
                'sender_email': 'no-reply@github.com',
                'recipient_email': user.email,
                'subject': '[Security Alert] Personal Access Token Expiry Notice',
                'body_text': (
                    "Hello @alex-dev,\n\n"
                    "Your personal access token 'CI/CD Deploy Token' will expire in 7 days.\n"
                    "Please regenerate a new token and update your secrets to ensure deployment workflows continue unimpeded."
                ),
                'snippet': 'Your personal access token CI/CD Deploy Token will expire in 7 days. Please regenerate a new token...',
                'category': EmailCategory.NOTIFICATIONS,
                'priority': EmailPriority.HIGH,
                'is_important': True,
                'is_read': False,
                'is_starred': True,
                'is_pinned': True,
                'time_delta': timedelta(days=4, hours=8)
            },
            {
                'sender_name': 'Python Weekly',
                'sender_email': 'newsletter@pythonweekly.com',
                'recipient_email': user.email,
                'subject': 'Python Weekly — Issue #640: Django 5.x & Agentic AI Tooling',
                'body_text': (
                    "Welcome to Issue #640 of Python Weekly.\n\n"
                    "Articles of the week:\n"
                    "- Building Agentic Workflows with Python 3.12+\n"
                    "- Optimizing Django Database Connections for High-Throughput APIs\n"
                    "- Modern UI Best Practices with Bootstrap 5 and Chart.js\n\n"
                    "Happy coding!"
                ),
                'snippet': 'Welcome to Issue #640 of Python Weekly. Building Agentic Workflows with Python 3.12+...',
                'category': EmailCategory.NEWSLETTER,
                'priority': EmailPriority.LOW,
                'is_important': False,
                'is_read': True,
                'is_starred': False,
                'is_pinned': False,
                'time_delta': timedelta(days=5)
            },
            {
                'sender_name': 'Cloudflare Developer Perks',
                'sender_email': 'deals@cloudflare-news.com',
                'recipient_email': user.email,
                'subject': 'Flash Sale: 50% Off Cloudflare Workers & Vectorize Annual Plan',
                'body_text': (
                    "Deploy edge AI and vector databases faster with Cloudflare Workers. Claim your 50% discount coupon "
                    "valid until the end of the month."
                ),
                'snippet': 'Deploy edge AI and vector databases faster with Cloudflare Workers. Claim your 50% discount...',
                'category': EmailCategory.PROMOTIONS,
                'priority': EmailPriority.LOW,
                'is_important': False,
                'is_read': True,
                'is_starred': False,
                'is_pinned': False,
                'time_delta': timedelta(days=6)
            },
            {
                'sender_name': 'Open Source Community',
                'sender_email': 'organizer@os-meetup.org',
                'recipient_email': user.email,
                'subject': 'Saturday Hackathon: Agentic Systems & LLM Integrations',
                'body_text': (
                    "Join 150+ engineers this Saturday for a collaborative hackathon building autonomous tools and "
                    "intelligent email assistants. Food and swag provided!"
                ),
                'snippet': 'Join 150+ engineers this Saturday for a collaborative hackathon building autonomous tools...',
                'category': EmailCategory.OTHER,
                'priority': EmailPriority.MEDIUM,
                'is_important': False,
                'is_read': True,
                'is_starred': False,
                'is_pinned': False,
                'time_delta': timedelta(days=6, hours=14)
            }
        ]

        created_emails = []
        for em in emails_dataset:
            obj, _ = Email.objects.update_or_create(
                user=user,
                subject=em['subject'],
                defaults={
                    'sender_name': em['sender_name'],
                    'sender_email': em['sender_email'],
                    'recipient_email': em['recipient_email'],
                    'body_text': em['body_text'],
                    'snippet': em['snippet'],
                    'category': em['category'],
                    'priority': em['priority'],
                    'importance': EmailImportance.IMPORTANT if em['is_important'] else EmailImportance.NORMAL,
                    'is_important': em['is_important'],
                    'is_read': em['is_read'],
                    'is_starred': em['is_starred'],
                    'is_pinned': em['is_pinned'],
                    'received_at': now - em['time_delta'],
                    'is_demo': True
                }
            )
            created_emails.append(obj)

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(created_emails)} Demo Emails across all categories."))

        # Seed Notifications
        notifications_data = [
            {
                'title': 'Important Email Received',
                'message': 'HOD College sent an important email regarding Internal Assessment Deadline.',
                'notification_type': Notification.TYPE_IMPORTANT_EMAIL,
                'priority': Notification.PRIORITY_HIGH,
                'is_read': False,
                'email': created_emails[0] if created_emails else None,
                'action_url': f'/emails/{created_emails[0].id}/' if created_emails else '/inbox/'
            },
            {
                'title': 'Interview Invitation',
                'message': 'Company HR confirmed your Senior Fullstack Engineer interview schedule.',
                'notification_type': Notification.TYPE_IMPORTANT_EMAIL,
                'priority': Notification.PRIORITY_HIGH,
                'is_read': False,
                'email': created_emails[1] if len(created_emails) > 1 else None,
                'action_url': f'/emails/{created_emails[1].id}/' if len(created_emails) > 1 else '/inbox/'
            },
            {
                'title': 'AI Daily Summary Preview Ready',
                'message': "Your AI daily digest preview for today is ready to view.",
                'notification_type': Notification.TYPE_AI_SUMMARY,
                'priority': Notification.PRIORITY_MEDIUM,
                'is_read': False,
                'action_url': '/ai-summary/'
            },
            {
                'title': 'Security Alert',
                'message': 'GitHub personal access token expiring in 7 days.',
                'notification_type': Notification.TYPE_SECURITY,
                'priority': Notification.PRIORITY_HIGH,
                'is_read': True,
                'action_url': '/inbox/'
            },
            {
                'title': 'System Status Healthy',
                'message': 'All email queue listeners and cache workers operating normally.',
                'notification_type': Notification.TYPE_SYSTEM,
                'priority': Notification.PRIORITY_LOW,
                'is_read': True,
                'action_url': '/dashboard/'
            }
        ]

        for notif in notifications_data:
            Notification.objects.create(
                user=user,
                title=notif['title'],
                message=notif['message'],
                notification_type=notif['notification_type'],
                priority=notif['priority'],
                is_read=notif['is_read'],
                email=notif.get('email'),
                action_url=notif['action_url'],
                is_demo=True
            )

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(notifications_data)} Notifications."))

        # Seed Demo Connected Gmail Account
        GmailAccount.objects.update_or_create(
            user=user,
            email_address='alex.morgan.workspace@gmail.com',
            defaults={
                'provider': 'google',
                'is_connected': True,
                'is_active': True,
                'scopes': 'https://www.googleapis.com/auth/gmail.readonly',
                'access_token': 'mock_demo_access_token',
                'refresh_token': 'mock_demo_refresh_token',
            }
        )
        if hasattr(user, 'profile'):
            user.profile.is_google_connected = True
            user.profile.save(update_fields=['is_google_connected'])
        self.stdout.write(self.style.SUCCESS("Seeded Demo Connected Gmail Account (alex.morgan.workspace@gmail.com)."))

        self.stdout.write(self.style.SUCCESS("[OK] Seed complete! You can log in with email: 'demo@example.com' or username: 'demo' (Password: 'demo12345')"))
