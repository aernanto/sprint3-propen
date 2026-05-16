from rest_framework import serializers

from .models import WithdrawalRequest


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = WithdrawalRequest
        fields = [
            'id',
            'withdrawal_id',
            'amount',
            'status',
            'status_display',
            'bank_name',
            'account_number',
            'account_holder',
            'balance_sukarela_snapshot',
            'notes',
            'rejection_reason',
            'requested_at',
            'reviewed_at',
        ]
        read_only_fields = fields
