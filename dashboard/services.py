from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from emails.models import Email, EmailCategory, PrioritySender, AIStatus
from emails.services import get_category_counts
from ai_engine.constants import EMAIL_CATEGORIES, CATEGORY_META


def get_dashboard_stats(user):
    """
    Computes dashboard analytics for the current user using real database records.
    Reflects AI classification, effective importance, and category distribution.
    """
    if not user.is_authenticated:
        return {
            'is_preview': True,
            'total_emails': 0,
            'unread_emails': 0,
            'starred_emails': 0,
            'important_emails': 0,
            'ai_analyzed': 0,
            'ai_pending': 0,
            'ai_failed': 0,
            'high_priority_emails': 0,
            'uncategorized_emails': 0,
            'recent_emails': [],
            'category_cards': [],
            'chart_labels': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            'chart_data': [0, 0, 0, 0, 0, 0, 0],
        }

    user_emails = Email.objects.filter(user=user)
    total = user_emails.count()

    if total > 0:
        unread = user_emails.filter(is_read=False).count()
        starred = user_emails.filter(is_starred=True).count()

        important_sender_emails = list(
            PrioritySender.objects.filter(user=user, is_important=True).values_list('email_address', flat=True)
        )

        important = user_emails.filter(
            Q(user_is_important=True) |
            (
                Q(user_is_important__isnull=True) & (
                    Q(is_pinned=True) |
                    Q(ai_is_important=True) |
                    Q(gmail_is_important=True) |
                    Q(is_important=True) |
                    Q(sender_email__in=important_sender_emails)
                )
            )
        ).count()

        ai_analyzed = user_emails.filter(ai_status=AIStatus.COMPLETED).count()
        ai_pending = user_emails.filter(Q(ai_status=AIStatus.PENDING) | Q(ai_status__isnull=True)).count()
        ai_failed = user_emails.filter(ai_status=AIStatus.FAILED).count()

        high_priority = user_emails.filter(
            Q(user_priority='High') |
            (Q(user_priority__isnull=True) & Q(ai_priority='High')) |
            (Q(user_priority__isnull=True) & Q(ai_priority__isnull=True) & Q(priority='High'))
        ).count()

        uncategorized = user_emails.filter(
            Q(ai_status__isnull=True) |
            Q(ai_status=AIStatus.PENDING) |
            (Q(user_category__isnull=True) & Q(ai_category__isnull=True) & (Q(category__isnull=True) | Q(category=EmailCategory.OTHER)))
        ).count()

        recent_emails = user_emails.order_by('-received_at')[:5]
        category_cards = get_category_counts(user)

        # 7-day activity counts
        now = timezone.now()
        chart_labels = []
        chart_data = []
        for i in range(6, -1, -1):
            day = now - timedelta(days=i)
            chart_labels.append(day.strftime('%a'))
            day_count = user_emails.filter(
                received_at__year=day.year,
                received_at__month=day.month,
                received_at__day=day.day
            ).count()
            chart_data.append(day_count)

        is_preview = False
    else:
        unread = 0
        starred = 0
        important = 0
        ai_analyzed = 0
        ai_pending = 0
        ai_failed = 0
        high_priority = 0
        uncategorized = 0
        recent_emails = []
        category_cards = [
            {'name': cat_name, 'count': 0, 'meta': CATEGORY_META.get(cat_name, CATEGORY_META['Other'])}
            for cat_name in EMAIL_CATEGORIES[:8]
        ]
        chart_labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        chart_data = [0, 0, 0, 0, 0, 0, 0]
        is_preview = False

    return {
        'is_preview': is_preview,
        'total_emails': total,
        'unread_emails': unread,
        'starred_emails': starred,
        'important_emails': important,
        'ai_analyzed': ai_analyzed,
        'ai_pending': ai_pending,
        'ai_failed': ai_failed,
        'high_priority_emails': high_priority,
        'uncategorized_emails': uncategorized,
        'recent_emails': recent_emails,
        'category_cards': category_cards,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
    }
