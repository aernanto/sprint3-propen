import re
from decimal import Decimal
from django.db import transaction, IntegrityError
from django.utils import timezone

from savings.models import SavingTransaction, SavingsBalance, SavingType, SavingStatus
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

    notify_saving_rejected(saving, reason)