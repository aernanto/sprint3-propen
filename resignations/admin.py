from django.contrib import admin

from .models import ResignationRequest, ResignationStatus
from notifications.service import notify_resignation_approved, notify_resignation_rejected


@admin.register(ResignationRequest)
class ResignationRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'member', 'status', 'estimated_payout', 'submitted_at', 'reviewed_at')
    list_filter = ('status',)
    search_fields = ('member__full_name', 'member__member_id')
    readonly_fields = ('submitted_at', 'updated_at', 'reviewed_at', 'resolved_at')

    def save_model(self, request, obj, form, change):
        if change and 'status' in form.changed_data:
            original = ResignationRequest.objects.get(pk=obj.pk)
            super().save_model(request, obj, form, change)
            if original.status == ResignationStatus.PENDING:
                if obj.status == ResignationStatus.APPROVED:
                    notify_resignation_approved(obj)
                elif obj.status == ResignationStatus.REJECTED:
                    notify_resignation_rejected(obj, getattr(obj, 'rejection_reason', '') or '')
            return
        super().save_model(request, obj, form, change)
