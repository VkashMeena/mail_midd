from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse, Http404, HttpResponse
from django.views.decorators.http import require_POST

from .models import Email, PrioritySender, EmailCategory, EmailPriority, AIStatus
from .forms import PrioritySenderForm
from . import services
from ai_engine.constants import EMAIL_CATEGORIES, EMAIL_CATEGORIES_LOOKUP, CATEGORY_META
from gmail_integration.services import gmail_service


@login_required
def inbox_view(request):
    filter_type = request.GET.get('filter', 'all')
    search_query = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort', 'newest')

    # Valid whitelist sort mapping
    valid_sorts = {
        'newest': '-received_at',
        'oldest': 'received_at',
        'sender': 'sender_name',
        'unread': ['is_read', '-received_at'],
        'priority': 'priority',
    }
    order_field = valid_sorts.get(sort_by, '-received_at')

    emails_qs = services.get_user_emails(
        user=request.user,
        filter_type=filter_type,
        search_query=search_query
    )
    if isinstance(order_field, list):
        emails_qs = emails_qs.order_by(*order_field)
    else:
        emails_qs = emails_qs.order_by(order_field)

    paginator = Paginator(emails_qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    connected_account = gmail_service.get_active_account(request.user)

    context = {
        'page_title': 'Inbox',
        'emails': page_obj,
        'current_filter': filter_type,
        'search_query': search_query,
        'current_sort': sort_by,
        'total_count': emails_qs.count(),
        'unread_count': Email.objects.filter(user=request.user, is_read=False).count(),
        'starred_count': Email.objects.filter(user=request.user, is_starred=True).count(),
        'connected_account': connected_account,
    }
    return render(request, 'inbox.html', context)


@login_required
def email_detail_view(request, email_id):
    email = get_object_or_404(
        Email.objects.prefetch_related('attachments'),
        id=email_id,
        user=request.user
    )
    if not email.is_read:
        email.is_read = True
        email.save(update_fields=['is_read'])

    # Check if sender is in PrioritySenders
    priority_sender = email.matched_priority_sender

    cleaned_html = email.clean_body_html
    cleaned_text = email.clean_body_text
    html_document = email.clean_body_html_document
    has_html = bool(cleaned_html and cleaned_html.strip())

    # Code tab stats
    html_code = cleaned_html if has_html else cleaned_text
    code_size_bytes = len(html_code.encode('utf-8')) if html_code else 0
    if code_size_bytes < 1024:
        code_size_str = f"{code_size_bytes} B"
    else:
        code_size_str = f"{code_size_bytes / 1024:.1f} KB"
    code_lines_count = len(html_code.splitlines()) if html_code else 0

    context = {
        'page_title': email.subject,
        'email': email,
        'attachments': email.attachments.all(),
        'labels': email.label_list,
        'formatted_labels': email.formatted_labels,
        'priority_sender': priority_sender,
        'allowed_categories': EMAIL_CATEGORIES,
        'cleaned_html': cleaned_html,
        'cleaned_text': cleaned_text,
        'html_document': html_document,
        'has_html': has_html,
        'html_code': html_code,
        'code_size_str': code_size_str,
        'code_lines_count': code_lines_count,
    }
    return render(request, 'emails/detail.html', context)


@login_required
def email_raw_html_view(request, email_id):
    """
    Renders the email HTML document directly in an isolated view or full-window tab.
    """
    email = get_object_or_404(Email, id=email_id, user=request.user)
    doc = email.clean_body_html_document
    if not doc:
        escaped_text = (email.clean_body_text or '').replace('<', '&lt;').replace('>', '&gt;')
        doc = f"<!DOCTYPE html><html><body style='font-family:monospace;padding:20px;white-space:pre-wrap;'>{escaped_text}</body></html>"
    return HttpResponse(doc, content_type='text/html; charset=utf-8')


@login_required
@require_POST
def override_email_ai_view(request, email_id):
    """
    Allows user to manually override category, importance, and priority.
    Preserves AI classification values separately.
    """
    email = get_object_or_404(Email, id=email_id, user=request.user)

    user_cat = request.POST.get('user_category', '').strip()
    user_imp = request.POST.get('user_is_important', '').strip()
    user_prio = request.POST.get('user_priority', '').strip()

    update_fields = []

    # Category override
    if user_cat in EMAIL_CATEGORIES:
        email.user_category = user_cat
        update_fields.append('user_category')
    elif user_cat == 'clear':
        email.user_category = None
        update_fields.append('user_category')

    # Importance override
    if user_imp.lower() in ('true', '1', 'yes', 'important'):
        email.user_is_important = True
        update_fields.append('user_is_important')
    elif user_imp.lower() in ('false', '0', 'no', 'normal'):
        email.user_is_important = False
        update_fields.append('user_is_important')
    elif user_imp == 'clear':
        email.user_is_important = None
        update_fields.append('user_is_important')

    # Priority override
    if user_prio in ('High', 'Medium', 'Low'):
        email.user_priority = user_prio
        update_fields.append('user_priority')
    elif user_prio == 'clear':
        email.user_priority = None
        update_fields.append('user_priority')

    if update_fields:
        email.save(update_fields=update_fields)
        messages.success(request, "Email tags updated successfully.")
    else:
        messages.info(request, "No changes made to email tags.")

    return redirect('emails:detail', email_id=email.id)


@login_required
def important_view(request):
    priority_tab = request.GET.get('priority', 'all')
    search_query = request.GET.get('q', '').strip()

    emails_qs = services.get_user_emails(
        user=request.user,
        filter_type='important',
        search_query=search_query,
        priority=priority_tab if priority_tab in [EmailPriority.HIGH, EmailPriority.MEDIUM, EmailPriority.LOW] else None
    )

    paginator = Paginator(emails_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_title': 'Important Emails',
        'emails': page_obj,
        'current_priority': priority_tab,
        'search_query': search_query,
        'total_count': emails_qs.count(),
    }
    return render(request, 'important.html', context)


@login_required
def pinned_view(request):
    search_query = request.GET.get('q', '').strip()
    emails_qs = services.get_user_emails(
        user=request.user,
        filter_type='pinned',
        search_query=search_query
    )

    paginator = Paginator(emails_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'page_title': 'Pinned Emails',
        'emails': page_obj,
        'search_query': search_query,
        'total_count': emails_qs.count(),
    }
    return render(request, 'pinned.html', context)


@login_required
def categories_view(request):
    categories_data = services.get_category_counts(request.user)
    context = {
        'page_title': 'Email Categories',
        'categories': categories_data,
    }
    return render(request, 'categories.html', context)


@login_required
def category_detail_view(request, category_name):
    """
    Category email list. Strictly validates against EMAIL_CATEGORIES.
    Rejects unknown or arbitrary categories with 404 per Section 41.
    """
    clean_cat = category_name.strip()
    matched_cat = EMAIL_CATEGORIES_LOOKUP.get(clean_cat.lower())

    if not matched_cat:
        from ai_engine.constants import CATEGORY_ALIASES
        if clean_cat.lower() in CATEGORY_ALIASES:
            matched_cat = CATEGORY_ALIASES[clean_cat.lower()]
        else:
            legacy_choice = next((c[0] for c in EmailCategory.CHOICES if c[0].lower() == clean_cat.lower()), None)
            if legacy_choice:
                matched_cat = normalize_category(legacy_choice)

    if not matched_cat:
        raise Http404(f"Category '{category_name}' not found. Allowed categories are predefined.")

    emails_qs = services.get_user_emails(user=request.user, category=clean_cat)

    paginator = Paginator(emails_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    category_meta = CATEGORY_META.get(matched_cat, CATEGORY_META['Other'])

    context = {
        'page_title': f"{matched_cat} Emails",
        'category_name': matched_cat,
        'category_meta': category_meta,
        'emails': page_obj,
        'total_count': emails_qs.count(),
    }
    return render(request, 'category_detail.html', context)


@login_required
def priority_senders_view(request):
    senders = services.get_priority_senders_for_user(request.user)
    form = PrioritySenderForm()

    context = {
        'page_title': 'Important & Priority Senders',
        'senders': senders,
        'form': form,
    }
    return render(request, 'priority_senders.html', context)


@login_required
def add_priority_sender_view(request):
    if request.method == 'POST':
        form = PrioritySenderForm(request.POST)
        if form.is_valid():
            sender = form.save(commit=False)
            sender.user = request.user
            sender.email_address = sender.email_address.strip().lower()
            # Handle unique per user
            existing = PrioritySender.objects.filter(user=request.user, email_address=sender.email_address).first()
            if existing:
                existing.display_name = sender.display_name
                existing.priority = sender.priority
                existing.is_important = sender.is_important
                existing.notification_enabled = sender.notification_enabled
                existing.save()
                messages.success(request, f"Important sender '{existing.display_name}' updated successfully!")
            else:
                sender.save()
                messages.success(request, f"Important sender '{sender.display_name}' added successfully!")
        else:
            messages.error(request, "Failed to add sender. Please check the inputs.")
    return redirect('emails:priority_senders')


@login_required
def delete_priority_sender_view(request, sender_id):
    sender = get_object_or_404(PrioritySender, id=sender_id, user=request.user)
    if request.method == 'POST':
        name = sender.display_name
        sender.delete()
        messages.success(request, f"Important sender '{name}' removed successfully.")
    return redirect('emails:priority_senders')


@login_required
def toggle_email_action_view(request, email_id, action):
    email = get_object_or_404(Email, id=email_id, user=request.user)
    state = False

    if action == 'star':
        email.is_starred = not email.is_starred
        email.save(update_fields=['is_starred'])
        state = email.is_starred
    elif action == 'pin':
        email.is_pinned = not email.is_pinned
        email.save(update_fields=['is_pinned'])
        state = email.is_pinned
    elif action == 'important':
        # Toggle user override
        if email.user_is_important is not None:
            email.user_is_important = not email.user_is_important
        else:
            email.user_is_important = not email.effective_importance
        email.save(update_fields=['user_is_important'])
        state = email.user_is_important
    elif action == 'read':
        email.is_read = not email.is_read
        email.save(update_fields=['is_read'])
        state = email.is_read

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        return JsonResponse({'success': True, 'action': action, 'state': state})

    return redirect(request.META.get('HTTP_REFERER', 'emails:inbox'))
