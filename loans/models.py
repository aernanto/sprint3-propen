from django.db import models, transaction
from django.utils import timezone
from decimal import Decimal
from members.models import Member, BankAccount
from users.models import User
from decimal import Decimal

class LoanCategory(models.TextChoices):
    MODAL_USAHA     = 'MODAL_USAHA', 'Modal Usaha'
    PENDIDIKAN      = 'PENDIDIKAN', 'Pendidikan'
    KESEHATAN       = 'KESEHATAN', 'Kesehatan'
    RENOVASI_RUMAH  = 'RENOVASI_RUMAH', 'Renovasi Rumah'
    KENDARAAN       = 'KENDARAAN', 'Kendaraan'
    ELEKTRONIK      = 'ELEKTRONIK', 'Elektronik'
    PERNIKAHAN      = 'PERNIKAHAN', 'Pernikahan'
    DANA_DARURAT    = 'DANA_DARURAT', 'Dana Darurat'
    LAINNYA         = 'LAINNYA', 'Lainnya'


class LoanStatus(models.TextChoices):
    PENDING             = 'PENDING', 'Pending'
    APPROVED            = 'APPROVED', 'Approved'
    REJECTED            = 'REJECTED', 'Rejected'
    ACTIVE              = 'ACTIVE', 'Active'
    LUNAS               = 'LUNAS', 'Lunas'
    OVERDUE             = 'OVERDUE', 'Overdue'
    LUNAS_AFTER_OVERDUE = 'LUNAS_AFTER_OVERDUE', 'Lunas After Overdue'


class InstallmentStatus(models.TextChoices):
    UNPAID  = 'UNPAID', 'Unpaid'
    PENDING = 'PENDING', 'Pending'
    PAID    = 'PAID', 'Paid'


class BadDebtStatus(models.TextChoices):
    # Urutan eskalasi: PENDING → WARNING_SENT → VISIT_SCHEDULED → LEGAL_NOTICE
    # (Surat peringatan hukum sebagai langkah terakhir setelah kunjungan dijadwalkan)
    PENDING          = 'PENDING', 'Belum Ditindaklanjuti'
    WARNING_SENT     = 'WARNING_SENT', 'Peringatan Terkirim'
    VISIT_SCHEDULED  = 'VISIT_SCHEDULED', 'Kunjungan Dijadwalkan'
    LEGAL_NOTICE     = 'LEGAL_NOTICE', 'Surat Peringatan Hukum'


class Loan(models.Model):
    TENOR_CHOICES = [(6, '6 Bulan'), (12, '12 Bulan'), (24, '24 Bulan'), (36, '36 Bulan')]
    INTEREST_RATE = Decimal('0.005')  # 0.5% flat per bulan

    member              = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='loans')
    loan_id             = models.CharField(max_length=30, unique=True, blank=True)
    category            = models.CharField(max_length=30, choices=LoanCategory.choices)
    amount              = models.DecimalField(max_digits=14, decimal_places=2)
    tenor               = models.IntegerField(choices=TENOR_CHOICES)
    description         = models.TextField(blank=True)
    status              = models.CharField(max_length=30, choices=LoanStatus.choices, default=LoanStatus.PENDING)

    # Bank account tujuan pencairan
    bank_account        = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='loans')

    # Dokumen pendukung
    collateral_image    = models.ImageField(upload_to='loans/collateral/', null=True, blank=True)
    salary_slip         = models.FileField(upload_to='loans/salary/', null=True, blank=True)

    # Approval
    reviewed_by         = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_loans')
    reviewed_at         = models.DateTimeField(null=True, blank=True)
    rejection_reason    = models.TextField(blank=True)

    # Disbursement
    disbursed_by        = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='disbursed_loans')
    disbursed_at        = models.DateTimeField(null=True, blank=True)
    disbursement_proof  = models.ImageField(upload_to='loans/disbursement/', null=True, blank=True)

    # Timestamps
    application_date    = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-application_date']

    def __str__(self):
        return f'{self.loan_id} - {self.member.full_name} ({self.status})'

    def save(self, *args, **kwargs):
        if not self.loan_id:
            year = timezone.now().year
            
            with transaction.atomic():
                last_loan = Loan.objects.filter(
                    application_date__year=year,
                    loan_id__startswith=f'LN-{year}-'
                ).select_for_update().order_by('-loan_id').first()

                if last_loan:
                    last_seq = int(last_loan.loan_id.split('-')[-1])
                    seq = last_seq + 1
                else:
                    seq = 1
                    
                self.loan_id = f'LN-{year}-{seq:03d}'
                
        super().save(*args, **kwargs)

    @property
    def monthly_installment(self):
        """Cicilan per bulan = (pokok + total bunga) / tenor"""
        total_interest = self.amount * self.INTEREST_RATE * self.tenor
        return (self.amount + total_interest) / self.tenor

    @property
    def total_repayment(self):
        total_interest = self.amount * self.INTEREST_RATE * self.tenor
        return self.amount + total_interest

    @property
    def outstanding_balance(self):
        # Loan yg ditolak / belum dicairkan / sudah lunas → tidak ada saldo terutang
        if self.status in (LoanStatus.REJECTED, LoanStatus.PENDING,
                           LoanStatus.LUNAS, LoanStatus.LUNAS_AFTER_OVERDUE):
            return Decimal('0')
        paid = self.installments.filter(
            status=InstallmentStatus.PAID
        ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
        return self.total_repayment - paid

    @property
    def next_due_date(self):
        # Loan yg ditolak/belum cair/lunas tidak punya tagihan aktif
        if self.status in (LoanStatus.REJECTED, LoanStatus.PENDING,
                           LoanStatus.LUNAS, LoanStatus.LUNAS_AFTER_OVERDUE):
            return None
        unpaid = self.installments.filter(
            status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING]
        ).order_by('due_date').first()
        return unpaid.due_date if unpaid else None

    @property
    def next_installment_amount(self):
        if self.status in (LoanStatus.REJECTED, LoanStatus.PENDING,
                           LoanStatus.LUNAS, LoanStatus.LUNAS_AFTER_OVERDUE):
            return None
        unpaid = self.installments.filter(
            status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING]
        ).order_by('due_date').first()
        return unpaid.amount if unpaid else None


class Installment(models.Model):
    loan                = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name='installments')
    installment_number  = models.IntegerField()
    due_date            = models.DateField()
    amount              = models.DecimalField(max_digits=14, decimal_places=2)  # total cicilan
    principal_component = models.DecimalField(max_digits=14, decimal_places=2)  # porsi pokok
    interest_component  = models.DecimalField(max_digits=14, decimal_places=2)  # porsi bunga
    status              = models.CharField(max_length=20, choices=InstallmentStatus.choices, default=InstallmentStatus.UNPAID)

    # Payment
    transaction_id      = models.CharField(max_length=50, unique=True, null=True, blank=True)
    paid_at             = models.DateTimeField(null=True, blank=True)
    payment_method      = models.CharField(max_length=20, null=True, blank=True)  # SAVINGS / BANK_TRANSFER
    transfer_proof      = models.FileField(upload_to='loans/payments/', null=True, blank=True)
    bank_account        = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='installment_payments')
    verified_by         = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_installments')
    rejection_reason    = models.TextField(blank=True)

    submitted_at        = models.DateTimeField(null=True, blank=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['installment_number']
        unique_together = ['loan', 'installment_number']

    def __str__(self):
        return f'{self.loan.loan_id} - Cicilan #{self.installment_number} ({self.status})'

    def save(self, *args, **kwargs):
        if not self.transaction_id and self.status == InstallmentStatus.PENDING:
            seq = Installment.objects.filter(transaction_id__isnull=False).count() + 1
            self.transaction_id = f'TRX-INS-{seq:05d}'
        super().save(*args, **kwargs)


class BadDebt(models.Model):
    loan        = models.OneToOneField(Loan, on_delete=models.CASCADE, related_name='bad_debt')
    status      = models.CharField(max_length=20, choices=BadDebtStatus.choices, default=BadDebtStatus.PENDING)
    notes       = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'BadDebt - {self.loan.loan_id} ({self.status})'