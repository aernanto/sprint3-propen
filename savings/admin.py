from django.contrib import admin

from savings.models import SavingTransaction, SavingStatus
from notifications.service import notify_saving_verified, notify_saving_rejected


@admin.register(SavingTransaction)
class SavingTransactionAdmin(admin.ModelAdmin):
	list_display = ('transaction_id', 'member', 'saving_type', 'amount', 'status', 'submitted_at')
	list_filter = ('saving_type', 'status')
	search_fields = ('transaction_id', 'saving_id', 'member__user__email', 'member__full_name')

	def save_model(self, request, obj, form, change):
		if change and 'status' in form.changed_data:
			original = SavingTransaction.objects.get(pk=obj.pk)
			if original.status == SavingStatus.PENDING:
				if obj.status == SavingStatus.SUCCESS:
					SavingTransaction.approve_transaction(original, request.user)
					notify_saving_verified(original)
					return
				elif obj.status == SavingStatus.REJECTED:
					super().save_model(request, obj, form, change)
					notify_saving_rejected(obj)
					return
		super().save_model(request, obj, form, change)

# Register your models here.
