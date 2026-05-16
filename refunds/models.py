from django.db import models


class RefundSourceType(models.TextChoices):
    RESIGNATION = 'RESIGNATION', 'Pengembalian Pengunduran Diri'
    INSTALLMENT = 'INSTALLMENT', 'Pengembalian Cicilan Ditolak'


class RefundStatus(models.TextChoices):
    PENDING = 'PENDING', 'Menunggu Pencairan'
    COMPLETED = 'COMPLETED', 'Selesai'


class Refund(models.Model):
    source_type = models.CharField(max_length=20, choices=RefundSourceType.choices)

    # Exactly one of these will be non-null depending on source_type
    resignation = models.OneToOneField(
        'resignations.ResignationRequest', on_delete=models.CASCADE,
        null=True, blank=True, related_name='refund',
    )
    installment = models.OneToOneField(
        'loans.Installment', on_delete=models.CASCADE,
        null=True, blank=True, related_name='refund',
    )
    member = models.ForeignKey(
        'members.Member', on_delete=models.CASCADE, related_name='refunds'
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=RefundStatus.choices, default=RefundStatus.PENDING
    )
    approved_at = models.DateTimeField()

    # Disbursement tracking
    disbursed_by = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='disbursed_refunds',
    )
    disbursed_at = models.DateTimeField(null=True, blank=True)
    transfer_proof = models.FileField(upload_to='refunds/proofs/', null=True, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-approved_at']

    def __str__(self):
        return f'Refund [{self.source_type}] - {self.member.full_name} ({self.status})'
