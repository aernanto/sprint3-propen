from django.contrib import admin

from .models import Loan, Installment, BadDebt, LoanStatus, InstallmentStatus
from notifications.service import (
    notify_loan_approved,
    notify_loan_rejected,
    notify_loan_disbursed,
    notify_loan_lunas,
    notify_loan_overdue,
    notify_installment_recorded,
    notify_installment_rejected,
)


class InstallmentInline(admin.TabularInline):
    model = Installment
    extra = 0
    readonly_fields = ['transaction_id', 'paid_at', 'updated_at']


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ['loan_id', 'member', 'category', 'amount', 'tenor', 'status', 'application_date']
    list_filter = ['status', 'category']
    search_fields = ['loan_id', 'member__full_name', 'member__user__email']
    readonly_fields = ['loan_id', 'application_date', 'updated_at']
    inlines = [InstallmentInline]

    def save_model(self, request, obj, form, change):
        if change and 'status' in form.changed_data:
            original = Loan.objects.get(pk=obj.pk)
            super().save_model(request, obj, form, change)
            old, new = original.status, obj.status
            if old == LoanStatus.PENDING and new == LoanStatus.APPROVED:
                notify_loan_approved(obj)
            elif old == LoanStatus.PENDING and new == LoanStatus.REJECTED:
                notify_loan_rejected(obj, getattr(obj, 'rejection_reason', '') or '')
            elif old == LoanStatus.APPROVED and new == LoanStatus.ACTIVE:
                notify_loan_disbursed(obj)
            elif new == LoanStatus.OVERDUE and old != LoanStatus.OVERDUE:
                notify_loan_overdue(obj)
            elif new in (LoanStatus.LUNAS, LoanStatus.LUNAS_AFTER_OVERDUE) and old not in (LoanStatus.LUNAS, LoanStatus.LUNAS_AFTER_OVERDUE):
                notify_loan_lunas(obj)
            return
        super().save_model(request, obj, form, change)


@admin.register(Installment)
class InstallmentAdmin(admin.ModelAdmin):
    list_display = ['transaction_id', 'loan', 'installment_number', 'due_date', 'amount', 'status']
    list_filter = ['status']
    search_fields = ['transaction_id', 'loan__loan_id', 'loan__member__full_name']
    readonly_fields = ['transaction_id', 'updated_at']

    def save_model(self, request, obj, form, change):
        if change and 'status' in form.changed_data:
            original = Installment.objects.get(pk=obj.pk)
            super().save_model(request, obj, form, change)
            if original.status == InstallmentStatus.PENDING:
                if obj.status == InstallmentStatus.PAID:
                    notify_installment_recorded(obj)
                elif obj.status == InstallmentStatus.UNPAID:
                    notify_installment_rejected(obj, getattr(obj, 'rejection_reason', '') or '')
            return
        super().save_model(request, obj, form, change)


@admin.register(BadDebt)
class BadDebtAdmin(admin.ModelAdmin):
    list_display = ['loan', 'status', 'created_at']
    list_filter = ['status']
