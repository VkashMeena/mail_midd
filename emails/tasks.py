"""
Asynchronous Celery tasks for email synchronization and background processing.
"""
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_gmail_account_task(self, user_id=None, account_id=None, query=None):
    """
    Celery task to synchronize Gmail messages in the background.
    Can target a specific GmailAccount by ID, all accounts for a User,
    or all active accounts across the system.
    """
    from gmail_integration.models import GmailAccount
    from gmail_integration.sync import GmailSyncService

    sync_service = GmailSyncService()
    results = []

    try:
        if account_id:
            accounts = GmailAccount.objects.filter(id=account_id, is_active=True)
        elif user_id:
            accounts = GmailAccount.objects.filter(user_id=user_id, is_active=True)
        else:
            accounts = GmailAccount.objects.filter(is_active=True)

        if not accounts.exists():
            logger.info("No active Gmail accounts found to synchronize for query params: user=%s, account=%s", user_id, account_id)
            return {'status': 'skipped', 'message': 'No active Gmail accounts found', 'synced': 0}

        for account in accounts:
            logger.info("Beginning background sync for Gmail account: %s (User ID: %s)", account.email_address, account.user_id)
            try:
                stats = sync_service.sync_gmail_account(account, query=query)
                results.append({
                    'account_id': account.id,
                    'email': account.email_address,
                    'status': 'success',
                    'stats': stats
                })
            except Exception as exc:
                logger.error("Background sync failed for account %s: %s", account.email_address, exc)
                results.append({
                    'account_id': account.id,
                    'email': account.email_address,
                    'status': 'failed',
                    'error': str(exc)
                })

        return {
            'status': 'completed',
            'synced_accounts': len(results),
            'results': results
        }

    except Exception as exc:
        logger.error("Fatal error executing sync_gmail_account_task: %s", exc)
        try:
            raise self.retry(exc=exc)
        except Exception:
            return {'status': 'error', 'error': str(exc)}
