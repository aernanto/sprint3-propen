from decimal import Decimal

from django.db import models

from members.models import Member
from users.models import User


class WithdrawalStatus(models.TextChoices):
    PENDING = 'PENDING', 'Menunggu Verifikasi'
    APPROVED = 'APPROVED', 'Disetujui'
    REJECTED = 'REJECTED', 'Ditolak'


class WithdrawalRequest(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='withdrawal_requests')
    withdrawal_id = models.CharField(max_length=30, unique=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=WithdrawalStatus.choices, default=WithdrawalStatus.PENDING
    )

    # Member's bank account details (snapshot at request time)
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50)
    account_holder = models.CharField(max_length=100)

    # Snapshot of balance at submission time for audit trail
    balance_sukarela_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))

    notes = models.TextField(blank=True)
    rejection_reason = models.TextField(blank=True)

    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_withdrawals'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    requested_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return f'{self.withdrawal_id} - {self.member.full_name} ({self.status})'

    def save(self, *args, **kwargs):
        if not self.withdrawal_id:
            seq = WithdrawalRequest.objects.count() + 1
            self.withdrawal_id = f'WD-{seq:05d}'
        super().save(*args, **kwargs)
