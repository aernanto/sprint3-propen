from rest_framework import serializers
from savings.models import SavingTransaction, SavingsBalance


class SavingTransactionListSerializer(serializers.ModelSerializer):
    member_name   = serializers.CharField(source='member.full_name', read_only=True)
    member_email  = serializers.EmailField(source='member.user.email', read_only=True)
    member_id     = serializers.CharField(source='member.member_id', read_only=True)
    member_status = serializers.CharField(source='member.status', read_only=True)

    class Meta:
        model  = SavingTransaction
        fields = (
            'id', 'saving_id', 'transaction_id', 'saving_type', 'amount', 'status',
            'member_name', 'member_email', 'member_id', 'member_status', 'submitted_at',
        )


class SavingTransactionDetailSerializer(serializers.ModelSerializer):
    member_name        = serializers.CharField(source='member.full_name', read_only=True)
    member_email       = serializers.EmailField(source='member.user.email', read_only=True)
    member_id          = serializers.CharField(source='member.member_id', read_only=True)
    member_status      = serializers.CharField(source='member.status', read_only=True)
    transfer_proof_url = serializers.SerializerMethodField()
    verified_by_email  = serializers.SerializerMethodField()

    class Meta:
        model  = SavingTransaction
        fields = (
            'id', 'saving_id', 'transaction_id', 'saving_type', 'amount', 'status',
            'member_name', 'member_email', 'member_id', 'member_status',
            'transfer_proof', 'transfer_proof_url',
            'member_bank_name', 'member_account_number',
            'rejection_reason', 'submitted_at', 'verified_by_email',
        )

    def get_transfer_proof_url(self, obj):
        request = self.context.get('request')
        if obj.transfer_proof:
            return request.build_absolute_uri(obj.transfer_proof.url) if request else obj.transfer_proof.url
        return None

    def get_verified_by_email(self, obj):
        return obj.verified_by.email if obj.verified_by else None


class SavingVerifySerializer(serializers.Serializer):
    ACTION_CHOICES = [('approve', 'Approve'), ('reject', 'Reject')]

    action           = serializers.ChoiceField(choices=ACTION_CHOICES)
    rejection_reason = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if data['action'] == 'reject' and not data.get('rejection_reason', '').strip():
            raise serializers.ValidationError(
                {'rejection_reason': 'Alasan penolakan wajib diisi ketika menolak transaksi.'}
            )
        return data


class SavingsBalanceSerializer(serializers.ModelSerializer):
    total        = serializers.SerializerMethodField()
    member_name  = serializers.CharField(source='member.full_name', read_only=True)
    member_id    = serializers.CharField(source='member.member_id', read_only=True)

    class Meta:
        model  = SavingsBalance
        fields = ('member_name', 'member_id', 'total_pokok', 'total_wajib', 'total_sukarela', 'total', 'last_updated')

    def get_total(self, obj):
        return str(obj.total_overall)