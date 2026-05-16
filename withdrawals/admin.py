from django.contrib import admin

from .models import WithdrawalRequest


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ('withdrawal_id', 'member', 'amount', 'status', 'requested_at')
    list_filter = ('status',)
    search_fields = ('withdrawal_id', 'member__full_name', 'member__member_id')
    readonly_fields = ('withdrawal_id', 'requested_at', 'updated_at')
