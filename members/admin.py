from django.contrib import admin

from .models import Member, BankAccount
from notifications.service import notify_registration_verified, notify_registration_rejected


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ('member_id', 'full_name', 'status', 'registration_date')
    list_filter = ('status',)
    search_fields = ('member_id', 'full_name', 'user__email')

    def save_model(self, request, obj, form, change):
        if change and 'status' in form.changed_data:
            original = Member.objects.get(pk=obj.pk)
            super().save_model(request, obj, form, change)
            if original.status == 'PENDING':
                if obj.status == 'VERIFIED':
                    notify_registration_verified(obj)
                elif obj.status == 'REJECTED':
                    notify_registration_rejected(obj, obj.rejection_reason or '')
            return
        super().save_model(request, obj, form, change)


admin.site.register(BankAccount)
