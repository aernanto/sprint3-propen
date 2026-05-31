from decimal import Decimal

from rest_framework import serializers

from savings.models import SavingTransaction, SavingType, SavingsWithdrawal


class SavingTransactionSerializer(serializers.ModelSerializer):
    transfer_proof_url = serializers.SerializerMethodField()

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
            attrs['amount'] = Decimal('100000.00')
        elif amount <= 0:
            raise serializers.ValidationError('Jumlah setoran harus lebih dari 0')

        return attrs

    def create(self, validated_data):
        return SavingTransaction.objects.create(member=self.context['request'].user.member, **validated_data)


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
