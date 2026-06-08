from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from members.models import Member
from notifications.service import notify_mandatory_saving_reminder
from savings.models import MandatorySavingObligation, MandatorySavingObligationStatus
from savings.services import sync_member_mandatory_savings


class Command(BaseCommand):
    help = 'Sync mandatory savings obligations and send due/overdue reminders.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reference-date',
            type=str,
            help='Optional ISO date to use instead of today (YYYY-MM-DD).',
        )

    def handle(self, *args, **options):
        reference_date = timezone.localdate()
        if options.get('reference_date'):
            reference_date = date.fromisoformat(options['reference_date'])

        active_members = Member.objects.filter(status='ACTIVE')
        self.stdout.write(f'Syncing mandatory savings for {active_members.count()} active member(s)...')

        reminder_cutoff = reference_date + timedelta(days=7)
        synced = 0
        reminders_sent = 0
        overdue_sent = 0

        for member in active_members:
            with transaction.atomic():
                sync_member_mandatory_savings(member, reference_date=reference_date)
                synced += 1

                obligations = MandatorySavingObligation.objects.filter(member=member).order_by('period_start')
                for obligation in obligations:
                    if obligation.status == MandatorySavingObligationStatus.PAID:
                        continue

                    if obligation.due_date < reference_date and obligation.overdue_notified_at is None:
                        notify_mandatory_saving_reminder(obligation, overdue=True)
                        obligation.overdue_notified_at = timezone.now()
                        obligation.status = MandatorySavingObligationStatus.OVERDUE
                        obligation.save(update_fields=['status', 'overdue_notified_at', 'updated_at'])
                        overdue_sent += 1
                        continue

                    if (
                        obligation.status == MandatorySavingObligationStatus.UNPAID
                        and obligation.due_date <= reminder_cutoff
                        and obligation.reminder_sent_at is None
                    ):
                        notify_mandatory_saving_reminder(obligation, overdue=False)
                        obligation.reminder_sent_at = timezone.now()
                        obligation.save(update_fields=['reminder_sent_at', 'updated_at'])
                        reminders_sent += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Done. synced={synced}, reminders_sent={reminders_sent}, overdue_sent={overdue_sent}'
            )
        )
