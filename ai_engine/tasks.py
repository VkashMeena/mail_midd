"""
Asynchronous Celery tasks for AI classification and daily summarization.
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, ignore_result=True)
def process_email_classification(self, email_id):
    """
    Celery task to automatically classify a newly received email by ID.
    Triggered immediately after Gmail sync saves a new message.
    """
    from emails.models import Email
    from ai_engine.classifier import EmailClassifier

    try:
        email = Email.objects.get(id=email_id)
        classifier = EmailClassifier()
        result = classifier.classify_email(email)
        logger.info(
            "Background AI classification complete for email id=%s (%s): %s [%s]",
            email.id, email.subject, result.category, result.priority
        )
        return {
            'status': 'completed',
            'email_id': email.id,
            'category': result.category,
            'is_important': result.importance,
            'priority': result.priority,
            'objective': result.objective,
        }
    except Email.DoesNotExist:
        logger.warning("Email id=%s not found for background classification", email_id)
        return {'status': 'not_found'}
    except Exception as exc:
        logger.error("Error classifying email id=%s in background task: %s", email_id, exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def classify_unprocessed_emails_task(self, user_id=None, batch_size=10):
    """
    Celery task to classify pending emails in the background.
    """
    from emails.models import Email, AIStatus
    from ai_engine.classifier import EmailClassifier

    classifier = EmailClassifier()
    qs = Email.objects.filter(ai_status=AIStatus.PENDING)
    if user_id:
        qs = qs.filter(user_id=user_id)

    pending_emails = list(qs.order_by('received_at')[:batch_size])
    if not pending_emails:
        logger.info("No pending emails found for AI classification (user_id=%s)", user_id)
        return {'status': 'skipped', 'processed': 0}

    logger.info("Processing background AI classification for %s emails", len(pending_emails))
    processed = 0
    errors = 0

    for email in pending_emails:
        try:
            classifier.classify_email(email)
            processed += 1
        except Exception as exc:
            logger.error("Failed to classify email %s in task: %s", email.id, exc)
            errors += 1

    return {
        'status': 'completed',
        'processed': processed,
        'errors': errors,
        'total': len(pending_emails)
    }


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def generate_daily_summary_task(self, user_id=None, target_date=None, force=False):
    """
    Celery task to generate daily executive briefings for users in the background.
    """
    from django.contrib.auth import get_user_model
    from ai_engine.summarizer import EmailSummarizer

    User = get_user_model()
    summarizer = EmailSummarizer()
    results = []

    if user_id:
        users = User.objects.filter(id=user_id, is_active=True)
    else:
        users = User.objects.filter(is_active=True)

    for user in users:
        try:
            summary = summarizer.summarize_for_user(user, target_date=target_date, force=force)
            results.append({
                'user_id': user.id,
                'email': user.email,
                'status': 'success' if summary else 'no_emails',
                'summary_id': summary.id if summary else None
            })
        except Exception as exc:
            logger.error("Failed background summary generation for user %s: %s", user.email, exc)
            results.append({
                'user_id': user.id,
                'email': user.email,
                'status': 'failed',
                'error': str(exc)
            })

    return {
        'status': 'completed',
        'summaries_generated': len(results),
        'results': results
    }
