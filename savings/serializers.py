from decimal import Decimal

from rest_framework import serializers

from savings.models import (
    MandatorySavingObligation,
    MandatorySavingPaymentMethod,
    SavingTransaction,
    SavingType,
    SavingsWithdrawal,
)
from savings.services import attach_mandatory_obligation_to_transaction, get_next_mandatory_obligation


class SavingTransactionSerializer(serializers.ModelSerializer):
    transfer_proof_url = serializers.SerializerMethodField()
    mandatory_obligation = serializers.SerializerMethodField()

    class Meta:
        model = SavingTransaction
        fields = (
            'id',
            'saving_id',
            'transaction_id',
            'saving_type',
            'amount',
            'status',
            'transfer_proof',
            'transfer_proof_url',
            'mandatory_obligation',
            'member_bank_name',
            'member_account_number',
            'rejection_reason',
            'submitted_at',
        )
        read_only_fields = ('saving_id', 'transaction_id', 'status', 'rejection_reason', 'submitted_at')

    def get_transfer_proof_url(self, obj):
        if not obj.transfer_proof:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.transfer_proof.url)
        return obj.transfer_proof.url

    def get_mandatory_obligation(self, obj):
        if not obj.mandatory_obligation:
            return None
        return MandatorySavingObligationSerializer(obj.mandatory_obligation, context=self.context).data


class MandatorySavingObligationSerializer(serializers.ModelSerializer):
    period_label = serializers.SerializerMethodField()
    payment_transaction_id = serializers.SerializerMethodField()
    payment_method_display = serializers.SerializerMethodField()

    class Meta:
        model = MandatorySavingObligation
        fields = (
            'id',
            'period_start',
            'period_label',
            'due_date',
            'amount',
            'status',
            'payment_method',
            'payment_method_display',
            'payment_transaction_id',
            'paid_at',
            'reminder_sent_at',
            'overdue_notified_at',
        )

    def get_period_label(self, obj):
        return obj.period_start.strftime('%B %Y')

    def get_payment_transaction_id(self, obj):
        return obj.payment_transaction_id

    def get_payment_method_display(self, obj):
        return dict(MandatorySavingPaymentMethod.choices).get(obj.payment_method, obj.payment_method)


class MandatorySavingsSummarySerializer(serializers.Serializer):
    count = serializers.IntegerField()
    overdue_count = serializers.IntegerField()
    overdue_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    next_due_date = serializers.DateField(allow_null=True)
    available_sukarela = serializers.DecimalField(max_digits=14, decimal_places=2)
    due_soon_count = serializers.IntegerField()
    auto_debit_required = serializers.BooleanField()
    auto_debit_pending = serializers.BooleanField()
    results = MandatorySavingObligationSerializer(many=True)


class InitialDepositCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SavingTransaction
        fields = ('transfer_proof', 'member_bank_name', 'member_account_number')

    def validate_transfer_proof(self, file):
        max_size = 5 * 1024 * 1024
        if file.size > max_size:
            raise serializers.ValidationError('Ukuran file maksimal 5MB')

        allowed_types = {'image/jpeg', 'image/png', 'application/pdf'}
        if hasattr(file, 'content_type') and file.content_type not in allowed_types:
            raise serializers.ValidationError('Format file harus JPG, PNG, atau PDF')

        return file

    def create(self, validated_data):
        return SavingTransaction.objects.create(
            member=self.context['request'].user.member,
            saving_type=SavingType.POKOK,
            amount=Decimal('150000.00'),
            **validated_data,
        )


class DepositCreateSerializer(serializers.ModelSerializer):
    saving_type = serializers.ChoiceField(choices=[SavingType.WAJIB, SavingType.SUKARELA])
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        model = SavingTransaction
        fields = ('saving_type', 'amount', 'transfer_proof', 'member_bank_name', 'member_account_number')

    def validate_transfer_proof(self, file):
        max_size = 5 * 1024 * 1024
        if file.size > max_size:
            raise serializers.ValidationError('Ukuran file maksimal 5MB')

        allowed_types = {'image/jpeg', 'image/png', 'application/pdf'}
        if hasattr(file, 'content_type') and file.content_type not in allowed_types:
            raise serializers.ValidationError('Format file harus JPG, PNG, atau PDF')

        return file

    def validate(self, attrs):
        saving_type = attrs['saving_type']
        amount = attrs['amount']

        if saving_type == SavingType.WAJIB:
            obligation = get_next_mandatory_obligation(self.context['request'].user.member, allow_advance=True)
            self.mandatory_obligation = obligation
            attrs['amount'] = obligation.amount
        elif amount <= 0:
            raise serializers.ValidationError('Jumlah setoran harus lebih dari 0')

        return attrs

    def create(self, validated_data):
        saving = SavingTransaction.objects.create(member=self.context['request'].user.member, **validated_data)
        if getattr(self, 'mandatory_obligation', None):
            attach_mandatory_obligation_to_transaction(saving)
        return saving


# ── Withdrawal serializers ─────────────────────────────────────────────────

class WithdrawalSerializer(serializers.ModelSerializer):
    transfer_proof_url = serializers.SerializerMethodField()

    class Meta:
        model = SavingsWithdrawal
        fields = (
            'id',
            'withdrawal_id',
            'amount',
            'bank_name',
            'account_number',
            'account_holder',
            'notes',
            'transfer_proof_url',
            'status',
            'processed_at',
            'created_at',
        )
        read_only_fields = ('id', 'withdrawal_id', 'status', 'created_at')

    def get_transfer_proof_url(self, obj):
        if not obj.transfer_proof:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.transfer_proof.url)
        return obj.transfer_proof.url


class WithdrawalCreateSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    bank_name = serializers.CharField(max_length=100)
    account_number = serializers.CharField(max_length=50)
    account_holder = serializers.CharField(max_length=150)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)

    class Meta:
        model = SavingsWithdrawal
        fields = ('amount', 'bank_name', 'account_number', 'account_holder', 'notes')

    def validate_account_number(self, value):
        if not value.isdigit():
            raise serializers.ValidationError('Nomor rekening harus berupa angka.')
        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Nominal penarikan harus lebih dari 0.')
        if value < Decimal('50000'):
            raise serializers.ValidationError('Nominal penarikan minimum adalah Rp 50.000.')
        return value

    def validate(self, attrs):
        member = self.context['request'].user.member
        try:
            balance = member.savings_balance
        except Exception:
            raise serializers.ValidationError('Data saldo simpanan tidak ditemukan.')

        if attrs['amount'] > balance.total_sukarela:
            raise serializers.ValidationError(
                f'Nominal penarikan melebihi saldo simpanan sukarela. '
                f'Saldo tersedia: Rp {balance.total_sukarela:,.0f}'
            )
        return attrs

    def create(self, validated_data):
        member = self.context['request'].user.member
        return SavingsWithdrawal.objects.create(member=member, **validated_data)
