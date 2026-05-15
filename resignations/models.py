from django.db import models

from members.models import Member
from users.models import User


class ResignationStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    REJECTED = 'REJECTED', 'Rejected'
    APPROVED = 'APPROVED', 'Approved'
    RESIGNED = 'RESIGNED', 'Resigned'


class ResignationRequest(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='resignation_requests')
    status = models.CharField(max_length=20, choices=ResignationStatus.choices, default=ResignationStatus.PENDING)

    total_savings_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_pokok_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_wajib_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_sukarela_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_loan_outstanding_snapshot = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    estimated_payout = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    rejection_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_resignations'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f'{self.member.full_name} - {self.status}'
