from django.contrib import admin

from .models import Refund


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ('id', 'source_type', 'member', 'amount', 'status', 'approved_at', 'disbursed_at')
    list_filter = ('source_type', 'status')
    search_fields = ('member__full_name', 'member__member_id')
    readonly_fields = ('created_at', 'updated_at')
