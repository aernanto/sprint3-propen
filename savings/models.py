from django.db import models, transaction
from django.core.exceptions import ValidationError

class SavingType(models.TextChoices):
    POKOK = 'POKOK', 'Simpanan Pokok'
    WAJIB = 'WAJIB', 'Simpanan Wajib'
    SUKARELA = 'SUKARELA', 'Simpanan Sukarela'

class SavingStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    SUCCESS = 'SUCCESS', 'Success'
    REJECTED = 'REJECTED', 'Rejected'

class WithdrawalStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    COMPLETED = 'COMPLETED', 'Completed'

class SavingsBalance(models.Model):
    member = models.OneToOneField('members.Member', on_delete=models.CASCADE, related_name='savings_balance')
    total_pokok = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_wajib = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_sukarela = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Balance - {self.member.full_name}"

    @property
    def total_overall(self):
        return self.total_pokok + self.total_wajib + self.total_sukarela

class SavingTransaction(models.Model):
    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='saving_transactions')
    saving_type = models.CharField(max_length=20, choices=SavingType.choices)
    saving_id = models.CharField(max_length=50, unique=True, blank=True)
    transaction_id = models.CharField(max_length=50, unique=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(max_length=20, choices=SavingStatus.choices, default=SavingStatus.PENDING)
    transfer_proof = models.FileField(upload_to='transfer_proofs/')
    member_bank_name = models.CharField(max_length=100)
    member_account_number = models.CharField(max_length=50)
    rejection_reason = models.TextField(blank=True)
    verified_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_savings')
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self) -> str:
        return f'{self.transaction_id} - {self.member.user.email}'

    def save(self, *args, **kwargs):
        if self.pk:
            original = SavingTransaction.objects.get(pk=self.pk)
            if original.status != SavingStatus.PENDING:
                raise ValidationError(f"Transaksi ini sudah {original.status} dan tidak bisa diubah.")
            if original.amount != self.amount or original.member != self.member:
                 raise ValidationError("Data krusial (nominal/member) tidak boleh diubah.")

        if not self.saving_id:
            seq = SavingTransaction.objects.count() + 1
            prefix = {
                SavingType.POKOK: 'SIM-PK', 
                SavingType.WAJIB: 'SIM-WB', 
                SavingType.SUKARELA: 'SIM-SK'
            }
            self.saving_id = f"{prefix.get(self.saving_type, 'SIM')}-{seq:05d}"
            
        if not self.transaction_id:
            seq = SavingTransaction.objects.count() + 1
            self.transaction_id = f'TRX-SV-{seq:05d}'
            
        super().save(*args, **kwargs)

    @classmethod
    def approve_transaction(cls, transaction_obj, admin_user):
        with transaction.atomic():
            transaction_obj.status = SavingStatus.SUCCESS
            transaction_obj.verified_by = admin_user
            transaction_obj.save()

            balance, _ = SavingsBalance.objects.get_or_create(member=transaction_obj.member)
            if transaction_obj.saving_type == SavingType.POKOK:
                balance.total_pokok += transaction_obj.amount
            elif transaction_obj.saving_type == SavingType.WAJIB:
                balance.total_wajib += transaction_obj.amount
            elif transaction_obj.saving_type == SavingType.SUKARELA:
                balance.total_sukarela += transaction_obj.amount
            balance.save()

            member = transaction_obj.member
            activated = False
            if transaction_obj.saving_type == SavingType.POKOK and member.status != 'ACTIVE':
                member.status = 'ACTIVE'
                if not member.member_id:
                    member.member_id = f"MBR-{member.pk:04d}"
                member.save()
                activated = True
            
            return {'member_activated': activated, 'balance': balance}


class SavingsWithdrawal(models.Model):
    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='savings_withdrawals')
    withdrawal_id = models.CharField(max_length=50, unique=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50)
    account_holder = models.CharField(max_length=150)
    notes = models.TextField(blank=True)
    transfer_proof = models.FileField(upload_to='loans/disbursement/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=WithdrawalStatus.choices, default=WithdrawalStatus.PENDING)
    processed_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_withdrawals',
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.withdrawal_id} - {self.member.full_name}'

    def save(self, *args, **kwargs):
        if not self.withdrawal_id:
            from django.utils import timezone
            year = timezone.now().year
            seq = SavingsWithdrawal.objects.filter(created_at__year=year).count() + 1
            self.withdrawal_id = f'WD-{year}-{seq:05d}'
        super().save(*args, **kwargs)