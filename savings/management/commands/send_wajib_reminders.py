"""
Management command untuk mengirim reminder simpanan wajib bulanan.

Aturan (PBI-2 acceptance criteria):
- Reminder H-7 sebelum akhir bulan: anggota ACTIVE yang belum setor simpanan WAJIB
  bulan ini.
- Reminder H+1 setelah akhir bulan: anggota ACTIVE yang sampai akhir bulan
  kemarin belum setor simpanan WAJIB untuk bulan tersebut (overdue).

Cara jalanin:
    python manage.py send_wajib_reminders
    python manage.py send_wajib_reminders --dry-run
    python manage.py send_wajib_reminders --force=upcoming  # paksa kirim H-7
    python manage.py send_wajib_reminders --force=overdue   # paksa kirim H+1

Dijadwalkan via cron / scheduler eksternal (mis. systemd timer atau cron):
    0 8 * * * cd /app && python manage.py send_wajib_reminders
"""

import calendar
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from members.models import Member
from savings.models import SavingTransaction, SavingType, SavingStatus
from notifications.service import (
    notify_wajib_reminder_upcoming,
    notify_wajib_reminder_overdue,
)


REMINDER_DAYS_BEFORE_END = 7  # H-7


def _last_day_of_month(d: date) -> date:
    last_day = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last_day)


def _previous_month(d: date) -> date:
    """Return any date inside the previous month."""
    first_of_this_month = date(d.year, d.month, 1)
    return first_of_this_month - timedelta(days=1)


def _member_has_wajib_in_month(member, year: int, month: int) -> bool:
    """
    Cek apakah anggota sudah punya setoran wajib (status PENDING atau SUCCESS)
    di bulan tertentu. PENDING dianggap "sudah disetor" agar reminder tidak
    spam member yang baru saja submit dan menunggu verifikasi.
    """
    return SavingTransaction.objects.filter(
        member=member,
        saving_type=SavingType.WAJIB,
        submitted_at__year=year,
        submitted_at__month=month,
        status__in=[SavingStatus.PENDING, SavingStatus.SUCCESS],
    ).exists()


class Command(BaseCommand):
    help = 'Kirim reminder simpanan wajib (H-7 sebelum & H+1 setelah jatuh tempo bulanan).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Tampilkan siapa saja yg akan dikirim tanpa benar2 mengirim.')
        parser.add_argument('--force', choices=['upcoming', 'overdue'], default=None,
                            help='Paksa kirim salah satu reminder (override pengecekan tanggal).')

    def handle(self, *args, **opts):
        today = timezone.now().date()
        dry_run = opts['dry_run']
        force = opts['force']

        end_of_month = _last_day_of_month(today)
        days_until_end = (end_of_month - today).days

        run_upcoming = (force == 'upcoming') or (
            force is None and days_until_end == REMINDER_DAYS_BEFORE_END
        )
        run_overdue = (force == 'overdue') or (
            force is None and today.day == 1
        )

        if not run_upcoming and not run_overdue:
            self.stdout.write(self.style.WARNING(
                f'[{today}] Bukan jadwal reminder. '
                f'days_until_end={days_until_end}, today.day={today.day}. '
                'Pakai --force=upcoming/overdue untuk testing.'
            ))
            return

        active_members = Member.objects.filter(status='ACTIVE').select_related('user')
        total_active = active_members.count()

        if run_upcoming:
            self._send_upcoming(active_members, today, dry_run)

        if run_overdue:
            self._send_overdue(active_members, today, dry_run)

        self.stdout.write(self.style.SUCCESS(
            f'[{today}] Selesai. {total_active} anggota ACTIVE diperiksa.'
        ))

    def _send_upcoming(self, active_members, today, dry_run):
        days_left = (_last_day_of_month(today) - today).days
        count = 0
        for member in active_members:
            if _member_has_wajib_in_month(member, today.year, today.month):
                continue
            count += 1
            if dry_run:
                self.stdout.write(f'  [UPCOMING-DRY] {member.full_name} ({member.user.email})')
            else:
                try:
                    notify_wajib_reminder_upcoming(member, days_left)
                except Exception as e:
                    self.stderr.write(f'  [FAIL UPCOMING] {member.full_name}: {e}')
        self.stdout.write(self.style.SUCCESS(
            f'  → {count} reminder UPCOMING (H-{days_left})'
        ))

    def _send_overdue(self, active_members, today, dry_run):
        prev = _previous_month(today)
        month_label = prev.strftime('%B %Y')
        count = 0
        for member in active_members:
            if _member_has_wajib_in_month(member, prev.year, prev.month):
                continue
            count += 1
            if dry_run:
                self.stdout.write(f'  [OVERDUE-DRY] {member.full_name} ({member.user.email})')
            else:
                try:
                    notify_wajib_reminder_overdue(member, month_label)
                except Exception as e:
                    self.stderr.write(f'  [FAIL OVERDUE] {member.full_name}: {e}')
        self.stdout.write(self.style.SUCCESS(
            f'  → {count} reminder OVERDUE (bulan {month_label})'
        ))
