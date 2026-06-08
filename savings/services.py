import re
from decimal import Decimal
from datetime import date, timedelta
import calendar

from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.utils import timezone

from savings.models import (
    MandatorySavingObligation,
    MandatorySavingPaymentMethod,
    MandatorySavingObligationStatus,
    SavingTransaction,
    SavingsBalance,
    SavingStatus,
    SavingType,
)
from notifications.service import notify_saving_verified, notify_saving_rejected


def _generate_unique_member_id(MemberModel) -> str:
    """
    Generate next available MBR-XXXX id berdasarkan MAX angka yg sudah ada
    (bukan COUNT). Aman terhadap gap akibat insert manual via Django admin
    atau hard-delete record.

    Looping naik 1-per-1 sampai ketemu yg belum ada (handle race condition).
    """
    existing_ids = MemberModel.objects.filter(
        member_id__regex=r'^MBR-\d+$'
    ).values_list('member_id', flat=True)

    max_seq = 0
    for mid in existing_ids:
        match = re.match(r'^MBR-(\d+)$', mid or '')
        if match:
            try:
                max_seq = max(max_seq, int(match.group(1)))
            except (ValueError, TypeError):
                continue

    candidate_seq = max_seq + 1
    # safety loop: kalau MBR-(max+1) tabrakan (race condition), naik terus
    while MemberModel.objects.filter(
        member_id=f'MBR-{candidate_seq:04d}'
    ).exists():
        candidate_seq += 1

    return f'MBR-{candidate_seq:04d}'
MANDATORY_MONTHLY_AMOUNT = Decimal('100000.00')
MANDATORY_REMINDER_WINDOW_DAYS = 7


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _month_end(value: date) -> date:
    last_day = calendar.monthrange(value.year, value.month)[1]
    return value.replace(day=last_day)


def _next_month_start(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _get_member_balance(member):
    balance, _ = SavingsBalance.objects.select_for_update().get_or_create(member=member)
    return balance


def _get_or_create_next_advance_obligation(member, reference_date: date) -> MandatorySavingObligation:
    latest = (
        MandatorySavingObligation.objects.select_for_update()
        .filter(member=member)
        .order_by('-period_start', '-id')
        .first()
    )

    base_period = latest.period_start if latest else _month_start(reference_date)
    next_period = _next_month_start(base_period)

    obligation, _ = MandatorySavingObligation.objects.get_or_create(
        member=member,
        period_start=next_period,
        defaults={
            'due_date': _month_end(next_period),
            'amount': MANDATORY_MONTHLY_AMOUNT,
        },
    )
    return obligation


@transaction.atomic
def auto_debit_mandatory_savings(member, reference_date: date | None = None):
    today = reference_date or timezone.localdate()
    window_end = today + timedelta(days=MANDATORY_REMINDER_WINDOW_DAYS)

    balance = _get_member_balance(member)
    available_sukarela = Decimal(str(balance.total_sukarela or 0))

    obligations = list(
        MandatorySavingObligation.objects.select_for_update()
        .filter(
            member=member,
            status__in=[
                MandatorySavingObligationStatus.UNPAID,
                MandatorySavingObligationStatus.PENDING,
                MandatorySavingObligationStatus.OVERDUE,
            ],
            due_date__lte=window_end,
        )
        .order_by('period_start', 'due_date', 'id')
    )

    debited = []
    for obligation in obligations:
        if obligation.status == MandatorySavingObligationStatus.PENDING:
            continue

        if available_sukarela < obligation.amount:
            continue

        available_sukarela -= obligation.amount
        obligation.status = MandatorySavingObligationStatus.PAID
        obligation.payment_method = MandatorySavingPaymentMethod.AUTO_DEBIT
        obligation.paid_at = timezone.now()
        obligation.save(update_fields=['status', 'payment_method', 'paid_at', 'updated_at'])
        debited.append(obligation)

    if debited:
        balance.total_sukarela = available_sukarela
        balance.save(update_fields=['total_sukarela', 'last_updated'])

    return debited


@transaction.atomic
def sync_member_mandatory_savings(member, reference_date: date | None = None):
    if member.status != 'ACTIVE':
        return []

    today = reference_date or timezone.localdate()
    period_start = _month_start(today)

    obligation, _ = MandatorySavingObligation.objects.get_or_create(
        member=member,
        period_start=period_start,
        defaults={
            'due_date': _month_end(period_start),
            'amount': MANDATORY_MONTHLY_AMOUNT,
        },
    )

    overdue_qs = MandatorySavingObligation.objects.filter(
        member=member,
        status__in=[MandatorySavingObligationStatus.UNPAID, MandatorySavingObligationStatus.PENDING],
        due_date__lt=today,
    )
    overdue_qs.update(status=MandatorySavingObligationStatus.OVERDUE)

    auto_debit_mandatory_savings(member, reference_date=today)

    return list(
        MandatorySavingObligation.objects.filter(member=member).order_by('-period_start')
    )


@transaction.atomic
def get_next_mandatory_obligation(member, allow_advance: bool = False):
    today = timezone.localdate()
    sync_member_mandatory_savings(member, reference_date=today)

    outstanding = (
        MandatorySavingObligation.objects.select_for_update()
        .filter(
            member=member,
            status__in=[
                MandatorySavingObligationStatus.UNPAID,
                MandatorySavingObligationStatus.PENDING,
                MandatorySavingObligationStatus.OVERDUE,
            ],
        )
        .order_by('period_start', 'due_date', 'id')
    )

    obligation = outstanding.first()
    if not obligation and allow_advance:
        obligation = _get_or_create_next_advance_obligation(member, reference_date=today)

    if not obligation:
        raise ValidationError('Tidak ada kewajiban simpanan wajib yang belum dibayar.')

    if obligation.status == MandatorySavingObligationStatus.PENDING:
        raise ValidationError('Kewajiban simpanan wajib periode ini masih menunggu verifikasi.')

    if obligation.status == MandatorySavingObligationStatus.PAID:
        raise ValidationError('Kewajiban simpanan wajib periode ini sudah lunas.')

    return obligation


@transaction.atomic
def attach_mandatory_obligation_to_transaction(saving: SavingTransaction) -> MandatorySavingObligation | None:
    if saving.saving_type != SavingType.WAJIB:
        return None

    obligation = get_next_mandatory_obligation(saving.member)
    saving.amount = obligation.amount
    saving.mandatory_obligation = obligation
    saving.save(update_fields=['amount', 'mandatory_obligation'])

    obligation.status = MandatorySavingObligationStatus.PENDING
    obligation.payment_method = MandatorySavingPaymentMethod.MANUAL
    obligation.payment_transaction = saving
    obligation.save(update_fields=['status', 'payment_method', 'payment_transaction', 'updated_at'])
    return obligation


@transaction.atomic
def mark_mandatory_obligation_paid(saving: SavingTransaction) -> None:
    if saving.saving_type != SavingType.WAJIB or not saving.mandatory_obligation:
        return

    obligation = MandatorySavingObligation.objects.select_for_update().get(pk=saving.mandatory_obligation_id)
    obligation.status = MandatorySavingObligationStatus.PAID
    obligation.payment_method = MandatorySavingPaymentMethod.MANUAL
    obligation.paid_at = timezone.now()
    obligation.payment_transaction = saving
    obligation.save(update_fields=['status', 'payment_method', 'paid_at', 'payment_transaction', 'updated_at'])


@transaction.atomic
def revert_mandatory_obligation_on_reject(saving: SavingTransaction) -> None:
    if saving.saving_type != SavingType.WAJIB or not saving.mandatory_obligation:
        return

    obligation = MandatorySavingObligation.objects.select_for_update().get(pk=saving.mandatory_obligation_id)
    if obligation.status == MandatorySavingObligationStatus.PAID:
        return

    obligation.status = (
        MandatorySavingObligationStatus.OVERDUE
        if obligation.due_date < timezone.localdate()
        else MandatorySavingObligationStatus.UNPAID
    )
    obligation.payment_method = MandatorySavingPaymentMethod.MANUAL
    obligation.payment_transaction = None
    obligation.save(update_fields=['status', 'payment_method', 'payment_transaction', 'updated_at'])


def get_mandatory_savings_summary(member):
    obligations = list(
        MandatorySavingObligation.objects.filter(member=member).order_by('-period_start')
    )
    active_obligations = [
        item for item in obligations
        if item.status in [
            MandatorySavingObligationStatus.UNPAID,
            MandatorySavingObligationStatus.PENDING,
            MandatorySavingObligationStatus.OVERDUE,
        ]
    ]
    available_sukarela = Decimal('0')
    balance = SavingsBalance.objects.filter(member=member).first()
    if balance:
        available_sukarela = Decimal(str(balance.total_sukarela or 0))

    overdue_obligations = [
        item for item in obligations
        if item.status in [MandatorySavingObligationStatus.UNPAID, MandatorySavingObligationStatus.OVERDUE]
    ]
    overdue_amount = sum((item.amount for item in overdue_obligations), Decimal('0'))
    due_soon_unpaid = [
        item for item in obligations
        if item.status in [MandatorySavingObligationStatus.UNPAID, MandatorySavingObligationStatus.OVERDUE]
        and item.due_date <= (timezone.localdate() + timedelta(days=MANDATORY_REMINDER_WINDOW_DAYS))
    ]
    next_due = next(
        (
            item
            for item in sorted(obligations, key=lambda item: (item.due_date, item.period_start, item.id))
            if item.status in [MandatorySavingObligationStatus.UNPAID, MandatorySavingObligationStatus.PENDING, MandatorySavingObligationStatus.OVERDUE]
        ),
        None,
    )

    return {
        'count': len(active_obligations),
        'overdue_count': len(overdue_obligations),
        'overdue_amount': overdue_amount,
        'next_due_date': next_due.due_date if next_due else None,
        'available_sukarela': available_sukarela,
        'due_soon_count': len(due_soon_unpaid),
        'auto_debit_required': len(overdue_obligations) > 0 and available_sukarela < overdue_amount,
        'auto_debit_pending': len(due_soon_unpaid) > 0 and available_sukarela >= sum((item.amount for item in due_soon_unpaid), Decimal('0')),
        'results': obligations,
    }


@transaction.atomic
def approve_saving_transaction(saving: SavingTransaction, staff_user) -> dict:
    if saving.status == SavingStatus.SUCCESS:
        raise ValueError('Transaksi ini sudah diverifikasi sebelumnya.')

    saving.status           = SavingStatus.SUCCESS
    saving.verified_by      = staff_user
    saving.rejection_reason = ''
    saving.save(update_fields=['status', 'verified_by', 'rejection_reason'])

    balance, _ = SavingsBalance.objects.select_for_update().get_or_create(
        member=saving.member
    )

    member_activated = False

    if saving.saving_type == SavingType.POKOK:
        balance.total_pokok = (balance.total_pokok or Decimal('0')) + saving.amount
        balance.save(update_fields=['total_pokok', 'last_updated'])

        member = saving.member
        if member.status == 'VERIFIED':
            member.status = 'ACTIVE'
            member.save(update_fields=['status'])
            member_activated = True

            if not member.member_id:
                # Retry sampai 5x kalau race condition (dua approval bersamaan)
                for _attempt in range(5):
                    try:
                        member.member_id = _generate_unique_member_id(type(member))
                        member.save(update_fields=['member_id'])
                        break
                    except IntegrityError:
                        member.member_id = None
                        continue

    elif saving.saving_type == SavingType.WAJIB:
        balance.total_wajib = (balance.total_wajib or Decimal('0')) + saving.amount
        balance.save(update_fields=['total_wajib', 'last_updated'])

    elif saving.saving_type == SavingType.SUKARELA:
        balance.total_sukarela = (balance.total_sukarela or Decimal('0')) + saving.amount
        balance.save(update_fields=['total_sukarela', 'last_updated'])

    mark_mandatory_obligation_paid(saving)

    notify_saving_verified(saving)

    return {'member_activated': member_activated, 'balance': balance}


@transaction.atomic
def reject_saving_transaction(saving: SavingTransaction, staff_user, reason: str) -> None:
    """
    Reject transaksi. Member status TIDAK berubah — member bisa resubmit bukti.
    """
    if saving.status == SavingStatus.SUCCESS:
        raise ValueError('Transaksi yang sudah SUCCESS tidak bisa ditolak.')

    saving.status           = SavingStatus.REJECTED
    saving.verified_by      = staff_user
    saving.rejection_reason = reason
    saving.save(update_fields=['status', 'verified_by', 'rejection_reason'])

    revert_mandatory_obligation_on_reject(saving)

    notify_saving_rejected(saving, reason)