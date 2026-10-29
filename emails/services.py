from django.db.models import Q, Count
from .models import Email, PrioritySender, EmailCategory, EmailPriority, EmailAttachment, AIStatus
from ai_engine.constants import EMAIL_CATEGORIES, PRIMARY_CATEGORIES, CATEGORY_META, normalize_category


def get_user_emails(user, filter_type=None, search_query=None, category=None, priority=None):
    """
    Retrieve and filter user emails cleanly via service layer.
    Strictly isolated to user=user with priority sender and attachment prefetching.
    """
    if not user.is_authenticated:
        return Email.objects.none()

    qs = Email.objects.filter(user=user)

    # Pre-fetch important sender emails for effective importance querying
    important_sender_emails = list(
        PrioritySender.objects.filter(user=user, is_important=True).values_list('email_address', flat=True)
    )

    if filter_type == 'unread':
        qs = qs.filter(is_read=False)
    elif filter_type == 'read':
        qs = qs.filter(is_read=True)
    elif filter_type in ('important', 'effective_important'):
        # Effective importance: User override > Priority sender > Pinned > AI important > Gmail important
        qs = qs.filter(
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
        )
    elif filter_type == 'gmail_important':
        qs = qs.filter(gmail_is_important=True)
    elif filter_type == 'ai_important':
        qs = qs.filter(ai_is_important=True)
    elif filter_type == 'pinned':
        qs = qs.filter(is_pinned=True)
    elif filter_type == 'starred':
        qs = qs.filter(is_starred=True)
    elif filter_type == 'high_priority':
        qs = qs.filter(
            Q(user_priority='High') |
            (Q(user_priority__isnull=True) & Q(ai_priority='High')) |
            (Q(user_priority__isnull=True) & Q(ai_priority__isnull=True) & Q(priority='High'))
        )
    elif filter_type == 'ai_processed':
        qs = qs.filter(ai_status=AIStatus.COMPLETED)
    elif filter_type == 'ai_pending':
        qs = qs.filter(Q(ai_status=AIStatus.PENDING) | Q(ai_status__isnull=True))
    elif filter_type == 'ai_failed':
        qs = qs.filter(ai_status=AIStatus.FAILED)

    if category:
        canonical_cat = normalize_category(category)
        matching_cats = {canonical_cat, category}
        from ai_engine.constants import CATEGORY_ALIASES
        for alias, canon in CATEGORY_ALIASES.items():
            if canon.lower() == canonical_cat.lower() or canon.lower() == category.lower():
                matching_cats.add(alias)
                for choice in EmailCategory.CHOICES:
                    if choice[0].lower() == alias:
                        matching_cats.add(choice[0])
        qs = qs.filter(
            Q(user_category__in=matching_cats) |
            (Q(user_category__isnull=True) & Q(ai_category__in=matching_cats)) |
            (Q(user_category__isnull=True) & Q(ai_category__isnull=True) & Q(category__in=matching_cats))
        )

    if priority:
        cap_priority = priority.capitalize()
        qs = qs.filter(
            Q(user_priority=cap_priority) |
            (Q(user_priority__isnull=True) & Q(ai_priority=cap_priority)) |
            (Q(user_priority__isnull=True) & Q(ai_priority__isnull=True) & Q(priority=cap_priority))
        )

    if search_query:
        qs = qs.filter(
            Q(subject__icontains=search_query) |
            Q(sender_name__icontains=search_query) |
            Q(sender_email__icontains=search_query) |
            Q(body_text__icontains=search_query) |
            Q(snippet__icontains=search_query) |
            Q(category__icontains=search_query) |
            Q(ai_category__icontains=search_query) |
            Q(user_category__icontains=search_query) |
            Q(ai_reason__icontains=search_query)
        )

    return qs.select_related('user', 'gmail_account').prefetch_related('attachments')


def get_email_by_id(user, email_id):
    """
    Fetch single email belonging to user with attachments preloaded.
    """
    try:
        email = Email.objects.prefetch_related('attachments').select_related('gmail_account').get(id=email_id, user=user)
        return email
    except Email.DoesNotExist:
        return None


def get_category_counts(user):
    """
    Returns list of dicts with category name, count, and visual metadata.
    Uses effective category logic (user_category > ai_category > category)
    and maps all categories cleanly into the 10 Primary Objective Categories.
    """
    if not user.is_authenticated:
        return [
            {'name': cat, 'count': 0, 'meta': CATEGORY_META.get(cat, CATEGORY_META['Other'])}
            for cat in PRIMARY_CATEGORIES
        ]

    user_emails = Email.objects.filter(user=user)
    counts_map = {cat: 0 for cat in PRIMARY_CATEGORIES}

    # Count based on effective resolution and canonical normalization
    for email in user_emails.only('user_category', 'ai_category', 'category', 'ai_status'):
        raw_cat = email.effective_category
        cat = normalize_category(raw_cat)
        if cat in counts_map:
            counts_map[cat] += 1
        else:
            counts_map['Other'] = counts_map.get('Other', 0) + 1

    categories_data = []
    for cat_name in PRIMARY_CATEGORIES:
        meta = CATEGORY_META.get(cat_name, CATEGORY_META['Other'])
        categories_data.append({
            'name': cat_name,
            'count': counts_map.get(cat_name, 0),
            'meta': meta,
        })
    return categories_data


def get_priority_senders_for_user(user):
    if not user.is_authenticated:
        return PrioritySender.objects.none()
    return PrioritySender.objects.filter(user=user)


def toggle_email_starred(email_id, user):
    email = get_email_by_id(user, email_id)
    if email:
        email.is_starred = not email.is_starred
        email.save(update_fields=['is_starred'])
        return email.is_starred
    return False


def toggle_email_pinned(email_id, user):
    email = get_email_by_id(user, email_id)
    if email:
        email.is_pinned = not email.is_pinned
        email.save(update_fields=['is_pinned'])
        return email.is_pinned
    return False
