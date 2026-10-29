import json
import logging
from datetime import datetime
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.http import require_POST
from django.db.models import Q
from django.conf import settings


from emails.models import Email, AIStatus, EmailSummary, EmailReply, ReplyTemplate, ReplyAuditLog, EmailAnalysis
from gmail_integration.services import gmail_service
from gmail_integration.exceptions import GmailIntegrationError, GmailPermissionError
from .services import ai_service
from .exceptions import AIEngineError, AIConfigurationError, AIValidationError, AIRateLimitError, AIProviderError
from .reply_generator import EmailReplyGenerator

logger = logging.getLogger(__name__)


@login_required
def ai_dashboard_view(request):
    """
    Dedicated AI Management Dashboard at /ai/.
    Displays processing state breakdown, category statistics, and failed analysis retry controls.
    """
    stats = ai_service.get_ai_processing_stats(request.user)
    context = {
        'page_title': 'AI Intelligence Processing',
        'stats': stats,
    }
    return render(request, 'ai_dashboard.html', context)


@login_required
@require_POST
def analyze_single_view(request, email_id):
    """
    Analyzes a single email for the logged-in user using the AI Email Analyzer.
    """
    email = get_object_or_404(Email, id=email_id, user=request.user)
    try:
        analysis = ai_service.analyze_email(email, user=request.user, force=False)
        messages.success(
            request,
            f"AI Analysis Completed: Classified as {analysis.category} ({analysis.priority} Priority)."
        )
    except (AIConfigurationError, AIRateLimitError, AIProviderError, AIEngineError) as exc:
        messages.error(request, f"AI Analysis failed: {exc}")
    except Exception as exc:
        logger.error("AI analysis failed for email id=%s: %s", email.id, exc)
        messages.error(request, f"AI analysis failed: {exc}")

    redirect_url = request.META.get('HTTP_REFERER') or 'emails:detail'
    if 'emails:detail' in redirect_url or 'inbox' in redirect_url:
        return redirect('emails:detail', email_id=email.id)
    return redirect(redirect_url)


@login_required
@require_POST
def reanalyze_single_view(request, email_id):
    """
    Forces deep re-analysis of an already processed email using AI Analyzer.
    """
    email = get_object_or_404(Email, id=email_id, user=request.user)
    try:
        analysis = ai_service.analyze_email(email, user=request.user, force=True)
        messages.success(
            request,
            f"AI Re-analysis Completed: Re-classified as {analysis.category} ({analysis.priority} Priority)."
        )
    except (AIConfigurationError, AIRateLimitError, AIProviderError, AIEngineError) as exc:
        messages.error(request, f"AI Re-analysis failed: {exc}")
    except Exception as exc:
        logger.error("AI re-analysis failed for email id=%s: %s", email.id, exc)
        messages.error(request, f"AI analysis failed: {exc}")

    return redirect('emails:detail', email_id=email.id)



@login_required
@require_POST
def analyze_batch_view(request):
    """
    Bulk analysis for selected emails from the Inbox.
    """
    raw_ids = request.POST.getlist('email_ids')
    if not raw_ids:
        raw_ids_str = request.POST.get('email_ids', '')
        if raw_ids_str:
            raw_ids = [i.strip() for i in raw_ids_str.split(',') if i.strip()]

    if not raw_ids:
        messages.warning(request, "Please select at least one email to analyze.")
        return redirect('inbox')

    emails = Email.objects.filter(user=request.user, id__in=raw_ids)
    if not emails.exists():
        messages.warning(request, "No valid emails found for analysis.")
        return redirect('inbox')

    try:
        stats = ai_service.classify_batch(emails, force=False)
        messages.success(
            request,
            f"AI Batch Processing Complete: {stats['completed']} analyzed, {stats['skipped']} already completed, {stats['failed']} failed."
        )
    except Exception as exc:
        logger.exception("AI batch processing failed: %s", exc)
        messages.error(request, "AI batch analysis encountered an error.")

    return redirect('inbox')


@login_required
@require_POST
def analyze_unprocessed_view(request):
    """
    Analyzes pending or new emails up to the batch limit.
    """
    try:
        stats = ai_service.classify_unprocessed(request.user)
        if stats['total'] == 0:
            messages.info(request, "No pending emails to analyze.")
        else:
            messages.success(
                request,
                f"AI Batch Complete: {stats['completed']} emails analyzed ({stats['failed']} failed)."
            )
    except AIConfigurationError:
        messages.error(request, "AI configuration is incomplete. Please check system settings.")
    except Exception as exc:
        logger.exception("AI unprocessed analysis failed: %s", exc)
        messages.error(request, "AI analysis is temporarily unavailable.")

    return redirect(request.META.get('HTTP_REFERER') or 'inbox')


@login_required
@require_POST
def retry_failed_view(request):
    """
    Retries emails that previously failed analysis.
    """
    try:
        stats = ai_service.retry_failed(request.user)
        if stats['total'] == 0:
            messages.info(request, "No failed emails found to retry.")
        else:
            messages.success(
                request,
                f"AI Retry Complete: {stats['completed']} recovered ({stats['failed']} failed)."
            )
    except Exception as exc:
        logger.exception("Retry failed emails error: %s", exc)
        messages.error(request, "AI retry operation failed.")

    return redirect('ai_engine:dashboard')


# --- Phase 7: Real AI Daily Email Summary Views ---
@login_required
def ai_summary_view(request, date_str=None):
    """
    Renders the Daily Email Summary page.
    Supports viewing today's summary or past summaries by date.
    Displays metrics, category distribution, important email highlights, and action items.
    """
    target_date = None
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            target_date = None

    start_of_day, start_of_tomorrow, local_date = ai_service.summarizer.get_date_boundaries(request.user, target_date=target_date)

    try:
        summary = ai_service.get_daily_summary(request.user, target_date=local_date, force=False)
    except Exception as exc:
        logger.error("Failed to load/generate daily summary for %s: %s", request.user, exc)
        summary = None

    # Load recent summary dates for sidebar / history tabs
    summary_history = EmailSummary.objects.filter(user=request.user).order_by('-summary_date')[:10]

    # Query important emails from this day for direct quick actions
    today_emails = Email.objects.filter(
        user=request.user,
        received_at__gte=start_of_day,
        received_at__lt=start_of_tomorrow
    )
    important_emails = today_emails.filter(
        Q(is_important=True) | Q(ai_is_important=True)
    ).order_by('-received_at')[:10]

    context = {
        'page_title': f"AI Daily Summary - {local_date.strftime('%B %d, %Y')}",
        'summary': summary,
        'summary_history': summary_history,
        'important_emails': important_emails,
        'today_date': local_date,
        'selected_date_str': local_date.strftime('%Y-%m-%d'),
        'total_emails_count': today_emails.count(),
    }
    return render(request, 'ai_summary.html', context)


@login_required
@require_POST
def generate_summary_view(request):
    """
    Forces AI daily summary regeneration for the specified or current day.
    """
    date_str = request.POST.get('date_str')
    target_date = None
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            target_date = None

    try:
        summary = ai_service.generate_daily_summary(request.user, target_date=target_date)
        messages.success(request, f"Daily summary for {summary.summary_date.strftime('%B %d, %Y')} has been regenerated.")
        return redirect('summary_date', date_str=summary.summary_date.strftime('%Y-%m-%d'))
    except AIConfigurationError:
        messages.error(request, "AI configuration is missing. Please check your AI API key.")
    except Exception as exc:
        logger.exception("Daily summary generation failed: %s", exc)
        messages.error(request, "Unable to generate daily summary at this time.")

    if date_str:
        return redirect('summary_date', date_str=date_str)
    return redirect('summary_today')


# --- Phase 7: Real AI Smart Reply Views ---
@login_required
def ai_reply_view(request, email_id=None):
    """
    Renders the AI Reply Studio.
    Provides context-aware drafting, tone selection, static template quick-buttons,
    draft saving, and Gmail send verification.
    """
    user_emails = Email.objects.filter(user=request.user).order_by('-received_at')

    selected_email = None
    if email_id:
        selected_email = get_object_or_404(Email, id=email_id, user=request.user)
    elif request.GET.get('email_id'):
        selected_email = user_emails.filter(id=request.GET.get('email_id')).first()
        if not selected_email and user_emails.exists():
            selected_email = user_emails.first()
    elif user_emails.exists():
        selected_email = user_emails.first()

    gmail_account = gmail_service.get_active_account(request.user)
    has_send_permission = bool(gmail_account and gmail_account.has_send_permission)

    templates = ReplyTemplate.get_templates_for_user(request.user)

    replies = []
    latest_reply = None
    if selected_email:
        replies = selected_email.replies.all().order_by('-created_at')
        latest_reply = replies.first()

    active_tones = [
        ('Professional', 'Professional'),
        ('Polite', 'Polite'),
        ('Friendly', 'Friendly'),
        ('Formal', 'Formal'),
        ('Casual', 'Casual'),
    ]
    active_lengths = [
        ('Short', 'Short'),
        ('Medium', 'Medium'),
        ('Long', 'Long'),
    ]

    context = {
        'page_title': 'AI Smart Reply Studio',
        'emails': user_emails[:20],
        'selected_email': selected_email,
        'gmail_account': gmail_account,
        'has_send_permission': has_send_permission,
        'templates': templates,
        'replies': replies,
        'latest_reply': latest_reply,
        'predefined_formats': EmailReplyGenerator.PREDEFINED_FORMATS,
        'default_format_key': 'medium_professional',
        'tones': active_tones,
        'lengths': active_lengths,
    }
    return render(request, 'ai_reply.html', context)


@login_required
@require_POST
def generate_reply_action(request, email_id):
    """
    Generates an AI reply draft for an email.
    Supports both standard form submission and AJAX JSON requests.
    Validates requested format/length/tone strictly against allowed taxonomies.
    """
    email = get_object_or_404(Email, id=email_id, user=request.user)

    # Read data from json payload or form post
    if request.content_type == 'application/json':
        try:
            body_data = json.loads(request.body)
        except Exception:
            body_data = {}
        format_param = body_data.get('reply_format') or body_data.get('format_key') or body_data.get('format')
        raw_tone = body_data.get('reply_tone') or body_data.get('tone')
        raw_length = body_data.get('reply_length') or body_data.get('length')
        instruction = body_data.get('custom_instruction') or body_data.get('instruction') or ''
        provider_name = body_data.get('provider') or body_data.get('provider_name')
    else:
        format_param = request.POST.get('reply_format') or request.POST.get('format_key') or request.POST.get('format')
        raw_tone = request.POST.get('reply_tone') or request.POST.get('tone')
        raw_length = request.POST.get('reply_length') or request.POST.get('length')
        instruction = request.POST.get('custom_instruction') or request.POST.get('instruction') or ''
        provider_name = request.POST.get('provider') or request.POST.get('provider_name')

    norm_length, norm_tone, format_meta = EmailReplyGenerator.resolve_format(
        format_key=format_param,
        length=raw_length,
        tone=raw_tone
    )
    format_key = format_meta.get('key', 'medium_professional')
    format_label = format_meta.get('label', f"{norm_length} + {norm_tone}")

    try:
        reply = ai_service.generate_reply(
            email=email,
            user=request.user,
            tone=norm_tone,
            length=norm_length,
            instruction=instruction,
            format_key=format_key,
            provider_name=provider_name
        )

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({
                'success': True,
                'reply_id': reply.id,
                'subject': reply.subject,
                'recipient': reply.recipient,
                'generated_text': reply.generated_text,
                'final_text': reply.final_text,
                'status': reply.status,
                'tone': reply.tone,
                'reply_tone': reply.tone,
                'length': reply.length,
                'reply_length': reply.length,
                'format_key': format_key,
                'format_label': format_label,
                'instruction': reply.instruction,
                'custom_instruction': reply.instruction,
            })

        messages.success(request, f"AI {format_label} reply draft generated.")
        return redirect(f"/emails/{email.id}/reply/")

    except (AIConfigurationError, AIRateLimitError, AIProviderError, AIEngineError) as exc:
        err = f"AI reply generation failed: {exc}"
    except Exception as exc:
        logger.exception("AI reply generation failed: %s", exc)
        err = f"AI reply generation failed: {exc}"

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({'success': False, 'error': err}, status=400)
    messages.error(request, err)
    return redirect(f"/emails/{email.id}/reply/")



@login_required
@require_POST
def save_reply_draft_action(request, email_id):
    """
    Saves user-modified text into the reply draft.
    """
    email = get_object_or_404(Email, id=email_id, user=request.user)

    if request.content_type == 'application/json':
        try:
            body_data = json.loads(request.body)
        except Exception:
            body_data = {}
        reply_id = body_data.get('reply_id')
        edited_text = body_data.get('edited_text', '')
        subject = body_data.get('subject')
    else:
        reply_id = request.POST.get('reply_id')
        edited_text = request.POST.get('edited_text', '')
        subject = request.POST.get('subject')

    if reply_id:
        reply = get_object_or_404(EmailReply, id=reply_id, user=request.user)
    else:
        # Create manual draft if none exists yet
        subj = subject.strip() if subject else ai_service.reply_generator.format_reply_subject(email.subject)
        reply = EmailReply.objects.create(
            user=request.user,
            email=email,
            reply_type=EmailReply.TYPE_MANUAL,
            recipient=email.sender_email,
            subject=subj,
            generated_text=edited_text,
            edited_text=edited_text,
            status=EmailReply.STATUS_SAVED
        )

    ai_service.save_reply_draft(reply, request.user, edited_text, subject=subject)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({
            'success': True,
            'reply_id': reply.id,
            'status': reply.status,
            'message': "Draft saved successfully."
        })

    messages.success(request, "Draft saved.")
    return redirect(f"/emails/{email.id}/reply/")


@login_required
@require_POST
def send_reply_action(request, email_id):
    """
    Dispatches an approved email reply via GmailSendService.
    Double-send safe, threaded, audited.
    """
    email = get_object_or_404(Email, id=email_id, user=request.user)

    if request.content_type == 'application/json':
        try:
            body_data = json.loads(request.body)
        except Exception:
            body_data = {}
        reply_id = body_data.get('reply_id')
        edited_text = body_data.get('edited_text')
    else:
        reply_id = request.POST.get('reply_id')
        edited_text = request.POST.get('edited_text')

    reply = get_object_or_404(EmailReply, id=reply_id, user=request.user)

    if edited_text is not None:
        reply.edited_text = edited_text
        reply.save(update_fields=['edited_text', 'updated_at'])

    try:
        sent_reply = ai_service.send_reply(reply, request.user)
        msg = f"Reply sent successfully to {sent_reply.recipient}!"

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({
                'success': True,
                'message': msg,
                'reply_id': sent_reply.id,
                'status': sent_reply.status,
                'sent_at': sent_reply.sent_at.isoformat() if sent_reply.sent_at else None,
                'gmail_message_id': sent_reply.gmail_message_id,
            })

        messages.success(request, msg)

    except GmailPermissionError as exc:
        err = str(exc)
        from django.urls import reverse
        grant_url = reverse('gmail:authorize_send')
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({
                'success': False,
                'code': 'GMAIL_SEND_PERMISSION_REQUIRED',
                'error': err,
                'grant_url': grant_url,
            }, status=400)
        messages.error(request, err)

    except GmailIntegrationError as exc:
        err = str(exc)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({'success': False, 'error': err}, status=400)
        messages.error(request, err)

    except Exception as exc:
        logger.exception("Send reply failed: %s", exc)
        err = "Unable to dispatch email reply via Gmail."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({'success': False, 'error': err}, status=500)
        messages.error(request, err)

    return redirect(f"/emails/{email.id}/reply/")


@login_required
@require_POST
def apply_template_action(request, email_id):
    """
    Applies a static reply template to the specified email.
    """
    email = get_object_or_404(Email, id=email_id, user=request.user)

    if request.content_type == 'application/json':
        try:
            body_data = json.loads(request.body)
        except Exception:
            body_data = {}
        template_id = body_data.get('template_id')
    else:
        template_id = request.POST.get('template_id')

    template = get_object_or_404(ReplyTemplate, id=template_id)
    reply = ai_service.apply_template_to_email(template, email, request.user)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({
            'success': True,
            'reply_id': reply.id,
            'subject': reply.subject,
            'recipient': reply.recipient,
            'final_text': reply.final_text,
            'status': reply.status,
        })

    messages.success(request, f"Applied template '{template.name}'.")
    return redirect(f"/emails/{email.id}/reply/")


@login_required
def reply_templates_manage_view(request):
    """
    Template management view: lists templates and creates new user templates.
    """
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        content = request.POST.get('content', '').strip()
        if name and content:
            ReplyTemplate.objects.create(
                user=request.user,
                name=name,
                content=content,
                is_default=False
            )
            messages.success(request, f"Reply template '{name}' created successfully.")
        else:
            messages.error(request, "Template name and content cannot be blank.")
        return redirect('reply_templates_manage')

    templates = ReplyTemplate.get_templates_for_user(request.user)
    context = {
        'page_title': 'Reply Templates',
        'templates': templates,
    }
    return render(request, 'reply_templates.html', context)


@login_required
@require_POST
def reply_template_delete_view(request, template_id):
    """
    Deletes a user's custom reply template.
    """
    template = get_object_or_404(ReplyTemplate, id=template_id, user=request.user)
    name = template.name
    template.delete()
    messages.success(request, f"Template '{name}' was deleted.")
    return redirect('reply_templates_manage')


# Phase 1 preview API preserved for backwards compatibility
@login_required
def ai_reply_preview_api(request):
    email_id = request.GET.get('email_id')
    tone = request.GET.get('tone', 'Professional')
    reply_text = ai_service.get_sample_reply(email_id=email_id, tone=tone, user=request.user)
    return JsonResponse({
        'success': True,
        'tone': tone,
        'reply': reply_text
    })


# ==============================================================================
# AI Email Analyzer Views (Powered by Groq LPU)
# ==============================================================================

@login_required
def email_analyzer_view(request, email_id):
    """
    Dedicated view for analyzing an individual email or retrieving its analysis.
    Supports GET (view analysis HTML or JSON) and POST (trigger deep AI intelligence analysis via Groq/LLM).
    """
    email = get_object_or_404(Email, id=email_id, user=request.user)

    if request.method == 'POST':
        provider_name = request.POST.get('provider') or request.GET.get('provider')
        if request.content_type == 'application/json':
            try:
                body_data = json.loads(request.body)
                provider_name = body_data.get('provider', provider_name)
            except Exception:
                pass

        try:
            analysis = ai_service.analyze_email(
                email=email,
                user=request.user,
                force=True,
                provider_name=provider_name
            )

            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                return JsonResponse({
                    'success': True,
                    'analysis': {
                        'id': analysis.id,
                        'objective': analysis.objective,
                        'category': analysis.category,
                        'priority': analysis.priority,
                        'is_important': analysis.is_important,
                        'urgency': analysis.urgency,
                        'sentiment': analysis.sentiment,
                        'confidence': analysis.confidence,
                        'reason': analysis.reason,
                        'action_required': analysis.action_required,
                        'key_points': analysis.key_points,
                        'action_items': analysis.action_items,
                        'extracted_deadlines': analysis.extracted_deadlines,
                        'suggested_reply_hooks': analysis.suggested_reply_hooks,
                        'provider': analysis.provider,
                        'model_name': analysis.model_name,
                        'updated_at': analysis.updated_at.strftime('%b %d, %Y %I:%M %p'),
                    }
                })

            messages.success(request, f"AI Analysis complete: {analysis.category} ({analysis.priority} Priority).")
            return redirect('emails:detail', email_id=email.id)

        except (AIConfigurationError, AIRateLimitError, AIProviderError, AIEngineError) as exc:
            err = f"AI analysis failed: {exc}"
        except Exception as exc:
            logger.exception("AI analysis failed: %s", exc)
            err = f"AI analysis failed: {exc}"

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({'success': False, 'error': err}, status=400)
        messages.error(request, err)
        return redirect('emails:detail', email_id=email.id)

    # GET request
    analysis = EmailAnalysis.objects.filter(email=email).first()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        if not analysis:
            return JsonResponse({'success': False, 'error': 'Email has not been analyzed yet.'}, status=404)
        return JsonResponse({
            'success': True,
            'analysis': {
                'id': analysis.id,
                'objective': analysis.objective,
                'category': analysis.category,
                'priority': analysis.priority,
                'is_important': analysis.is_important,
                'urgency': analysis.urgency,
                'sentiment': analysis.sentiment,
                'confidence': analysis.confidence,
                'reason': analysis.reason,
                'action_required': analysis.action_required,
                'key_points': analysis.key_points,
                'action_items': analysis.action_items,
                'extracted_deadlines': analysis.extracted_deadlines,
                'suggested_reply_hooks': analysis.suggested_reply_hooks,
                'provider': analysis.provider,
                'model_name': analysis.model_name,
                'updated_at': analysis.updated_at.strftime('%b %d, %Y %I:%M %p'),
            }
        })

    context = {
        'page_title': f'AI Analysis: {email.subject}',
        'email': email,
        'analysis': analysis,
    }
    return render(request, 'emails/analysis_detail.html', context)


@login_required
def ai_analyzer_hub_view(request):
    """
    Dedicated AI Email Analyzer Hub at /ai/analyzer/.
    Shows recent email analyses, pending emails, insights, and quick intelligence extraction.
    """
    user_emails = Email.objects.filter(user=request.user).order_by('-received_at')
    analyses = EmailAnalysis.objects.filter(user=request.user).select_related('email').order_by('-created_at')

    selected_email = None
    email_id = request.GET.get('email_id')
    if email_id:
        selected_email = user_emails.filter(id=email_id).first()
    elif user_emails.exists():
        selected_email = user_emails.first()

    analysis = None
    if selected_email:
        analysis = EmailAnalysis.objects.filter(email=selected_email).first()

    context = {
        'page_title': 'AI Email Analyzer Hub',
        'emails': user_emails[:30],
        'selected_email': selected_email,
        'analysis': analysis,
        'recent_analyses': analyses[:15],
        'total_analyzed': analyses.count(),
        'groq_model': getattr(settings, 'GROQ_MODEL', 'llama-3.3-70b-versatile'),
    }
    return render(request, 'ai_analyzer_hub.html', context)


