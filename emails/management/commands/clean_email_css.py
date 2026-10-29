from django.core.management.base import BaseCommand
from emails.models import Email
from emails.utils import clean_leaked_css_from_html, clean_leaked_css_from_text


class Command(BaseCommand):
    help = "Cleans leaked CSS blocks from body_html and body_text in stored emails."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report changes without updating the database',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        emails = Email.objects.all()
        total = emails.count()
        cleaned_count = 0

        self.stdout.write(f"Scanning {total} emails for leaked CSS...")

        for email in emails:
            changed = False
            orig_html = email.body_html or ''
            orig_text = email.body_text or ''

            cleaned_html = clean_leaked_css_from_html(orig_html)
            cleaned_text = clean_leaked_css_from_text(orig_text)

            if cleaned_html != orig_html:
                email.body_html = cleaned_html
                changed = True

            if cleaned_text != orig_text:
                email.body_text = cleaned_text
                changed = True

            if changed:
                cleaned_count += 1
                if not dry_run:
                    email.save(update_fields=['body_html', 'body_text'])
                safe_subject = (email.subject or '')[:50].encode('ascii', errors='replace').decode('ascii')
                self.stdout.write(self.style.SUCCESS(f"Cleaned email {email.id}: {safe_subject}"))

        mode_str = " (DRY RUN - no changes saved)" if dry_run else ""
        self.stdout.write(
            self.style.SUCCESS(f"Finished! Cleaned {cleaned_count} of {total} emails{mode_str}.")
        )
