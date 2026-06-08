from django.db.models import Sum
from rest_framework import serializers
from .models import Loan, Installment, BadDebt, LoanCategory, LoanStatus, InstallmentStatus
from .services import simulate_installment
from members.models import BankAccount


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = ['id', 'bank_name', 'account_number', 'account_holder', 'is_primary']


class InstallmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Installment
        fields = [
            'id', 'installment_number', 'due_date', 'amount',
            'principal_component', 'interest_component',
            'status', 'transaction_id', 'paid_at',
            'payment_method', 'transfer_proof', 'rejection_reason',
            'submitted_at',
        ]


# ── Staff Serializers ────────────────────────────────────────────────────────

class StaffApprovedLoanSerializer(serializers.ModelSerializer):
    """Serializer untuk list pinjaman yang berstatus APPROVED - untuk staff cairkan"""
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    approved_at = serializers.DateTimeField(source='reviewed_at', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id',
            'loan_id',
            'member_name',
            'category',
            'category_display',
            'amount',
            'tenor',
            'status',
            'status_display',
            'approved_at',
            'application_date',
        ]
        read_only_fields = fields


class StaffDisbursedLoanSerializer(serializers.ModelSerializer):
    """Serializer untuk riwayat pinjaman yang sudah dicairkan - untuk staff"""
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    disbursed_by_name = serializers.CharField(source='disbursed_by.get_full_name', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    approved_at = serializers.DateTimeField(source='reviewed_at', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id',
            'loan_id',
            'member_name',
            'category',
            'category_display',
            'amount',
            'tenor',
            'status',
            'status_display',
            'approved_at',
            'disbursed_at',
            'disbursed_by_name',
        ]
        read_only_fields = fields


# ── Member Serializers ───────────────────────────────────────────────────────

class LoanListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for loan list/overview table"""
    class Meta:
        model = Loan
        fields = [
            'id', 'loan_id', 'category', 'amount',
            'outstanding_balance', 'status', 'application_date',
        ]

    outstanding_balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)


class LoanOverviewSerializer(serializers.ModelSerializer):
    """Full serializer for loan overview page (PBI-14)"""
    outstanding_balance     = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    next_due_date           = serializers.DateField(read_only=True)
    next_installment_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    category_display        = serializers.CharField(source='get_category_display', read_only=True)
    status_display          = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id', 'loan_id', 'category', 'category_display',
            'amount', 'tenor', 'status', 'status_display',
            'outstanding_balance', 'next_due_date', 'next_installment_amount',
            'application_date',
        ]


class LoanDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for loan detail page (PBI-16)"""
    installments            = InstallmentSerializer(many=True, read_only=True)
    outstanding_balance     = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    next_due_date           = serializers.DateField(read_only=True)
    next_installment_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    category_display        = serializers.CharField(source='get_category_display', read_only=True)
    status_display          = serializers.CharField(source='get_status_display', read_only=True)
    bank_account            = BankAccountSerializer(read_only=True)
    progress_percent        = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = [
            'id', 'loan_id', 'category', 'category_display',
            'amount', 'tenor', 'status', 'status_display',
            'outstanding_balance', 'next_due_date', 'next_installment_amount',
            'progress_percent', 'bank_account',
            'application_date', 'disbursed_at', 'description', 'rejection_reason',
            'installments',
        ]

    def get_progress_percent(self, obj):
        # Loan ditolak / belum cair → progress 0 (bukan 100)
        if obj.status in ('REJECTED', 'PENDING'):
            return 0
        if obj.amount == 0:
            return 100
        paid = obj.amount - obj.outstanding_balance
        return round(float(paid / obj.amount) * 100, 1)


class LoanCreateSerializer(serializers.ModelSerializer):
    """Serializer for loan application (PBI-15)"""
    simulation = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = [
            'id', 'loan_id', 'category', 'amount', 'tenor',
            'description', 'bank_account',
            'collateral_image', 'salary_slip',
            'status', 'application_date', 'simulation',
        ]
        read_only_fields = ['loan_id', 'status', 'application_date']

    def get_simulation(self, obj):
        return simulate_installment(obj.amount, obj.tenor)

    def validate_amount(self, value):
        if value < 1_000_000:
            raise serializers.ValidationError('Minimal pinjaman Rp 1.000.000')
        if value > 50_000_000:
            raise serializers.ValidationError('Maksimal pinjaman Rp 50.000.000')
        return value

    def validate_tenor(self, value):
        if value not in [6, 12, 24, 36]:
            raise serializers.ValidationError('Tenor harus 6, 12, 24, atau 36 bulan')
        return value

    def validate_bank_account(self, value):
        member = self.context['request'].user.member
        if value and value.member != member:
            raise serializers.ValidationError('Bank account bukan milik member ini')
        return value

    def validate(self, attrs):
        from .services import has_bad_debt, calculate_max_loan_from_savings
        member = self.context['request'].user.member
        if has_bad_debt(member):
            raise serializers.ValidationError(
                'Anda memiliki kredit macet dan tidak dapat mengajukan pinjaman baru.'
            )
        tenor = attrs.get('tenor', 12)
        max_loan = calculate_max_loan_from_savings(member, tenor)
        if max_loan < 1_000_000:
            raise serializers.ValidationError(
                'Simpanan Anda belum mencukupi untuk mengajukan pinjaman.'
            )
        if attrs.get('amount', 0) > max_loan:
            formatted = f"Rp {int(max_loan):,}".replace(',', '.')
            raise serializers.ValidationError(
                f'Jumlah pinjaman melebihi batas maksimal berdasarkan simpanan Anda ({formatted}).'
            )
        return attrs


class LoanSimulationSerializer(serializers.Serializer):
    """Serializer for installment simulation preview"""
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    tenor  = serializers.IntegerField()

    def validate_tenor(self, value):
        if value not in [6, 12, 24, 36]:
            raise serializers.ValidationError('Tenor harus 6, 12, 24, atau 36 bulan')
        return value


# ── Manager Serializers ──────────────────────────────────────────────────────

class ManagerPendingLoanSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id',
            'loan_id',
            'member_name',
            'category',
            'category_display',
            'amount',
            'tenor',
            'application_date',
            'status',
        ]


class ManagerLoanHistorySerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    reviewed_by_email = serializers.EmailField(source='reviewed_by.email', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id',
            'loan_id',
            'member_name',
            'category',
            'category_display',
            'amount',
            'tenor',
            'application_date',
            'status',
            'reviewed_at',
            'reviewed_by_email',
            'rejection_reason',
        ]


class ManagerAllLoanSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    remaining_balance = serializers.SerializerMethodField()
    due_date = serializers.DateField(source='next_due_date', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id',
            'member_name',
            'loan_id',
            'remaining_balance',
            'due_date',
            'status',
            'status_display',
        ]

    def get_remaining_balance(self, obj):
        total_remaining = (
            obj.installments
            .filter(status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING])
            .aggregate(total=Sum('amount'))['total']
        )
        if total_remaining is not None:
            return total_remaining
        return obj.outstanding_balance


class ManagerMemberLoanHistoryItemSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id',
            'loan_id',
            'amount',
            'status',
            'status_display',
            'application_date',
        ]


class ManagerLoanDetailSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    credit_score = serializers.SerializerMethodField()
    total_savings = serializers.SerializerMethodField()
    active_loans_count = serializers.SerializerMethodField()
    bad_debt_history_count = serializers.SerializerMethodField()
    collateral_image_url = serializers.SerializerMethodField()
    salary_slip_url = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = [
            'id',
            'loan_id',
            'member_name',
            'application_date',
            'status',
            'status_display',
            'rejection_reason',
            'amount',
            'tenor',
            'category',
            'category_display',
            'description',
            'credit_score',
            'total_savings',
            'active_loans_count',
            'bad_debt_history_count',
            'collateral_image_url',
            'salary_slip_url',
        ]

    def _build_file_url(self, file_field):
        if not file_field:
            return None
        request = self.context.get('request')
        url = file_field.url
        return request.build_absolute_uri(url) if request else url

    def get_credit_score(self, obj):
        from .services import calculate_credit_score
        return calculate_credit_score(obj.member)

    def get_total_savings(self, obj):
        balance = getattr(obj.member, 'savings_balance', None)
        return balance.total_overall if balance else 0

    def get_active_loans_count(self, obj):
        return obj.member.loans.filter(status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE]).count()

    def get_bad_debt_history_count(self, obj):
        return BadDebt.objects.filter(loan__member=obj.member).count()

    def get_collateral_image_url(self, obj):
        return self._build_file_url(obj.collateral_image)

    def get_salary_slip_url(self, obj):
        return self._build_file_url(obj.salary_slip)
    """Lightweight serializer for loan list/overview table"""
    class Meta:
        model = Loan
        fields = [
            'id', 'loan_id', 'category', 'amount',
            'outstanding_balance', 'status', 'application_date',
        ]

    outstanding_balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)


class LoanOverviewSerializer(serializers.ModelSerializer):
    """Full serializer for loan overview page (PBI-14)"""
    outstanding_balance     = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    next_due_date           = serializers.DateField(read_only=True)
    next_installment_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    category_display        = serializers.CharField(source='get_category_display', read_only=True)
    status_display          = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id', 'loan_id', 'category', 'category_display',
            'amount', 'tenor', 'status', 'status_display',
            'outstanding_balance', 'next_due_date', 'next_installment_amount',
            'application_date',
        ]


class LoanDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for loan detail page (PBI-16)"""
    installments            = InstallmentSerializer(many=True, read_only=True)
    outstanding_balance     = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    next_due_date           = serializers.DateField(read_only=True)
    next_installment_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    category_display        = serializers.CharField(source='get_category_display', read_only=True)
    status_display          = serializers.CharField(source='get_status_display', read_only=True)
    bank_account            = BankAccountSerializer(read_only=True)
    progress_percent        = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = [
            'id', 'loan_id', 'category', 'category_display',
            'amount', 'tenor', 'status', 'status_display',
            'outstanding_balance', 'next_due_date', 'next_installment_amount',
            'progress_percent', 'bank_account',
            'application_date', 'disbursed_at', 'description', 'rejection_reason',
            'installments',
        ]

    def get_progress_percent(self, obj):
        # Loan ditolak / belum cair → progress 0 (bukan 100)
        if obj.status in ('REJECTED', 'PENDING'):
            return 0
        if obj.amount == 0:
            return 100
        paid = obj.amount - obj.outstanding_balance
        return round(float(paid / obj.amount) * 100, 1)


class LoanCreateSerializer(serializers.ModelSerializer):
    """Serializer for loan application (PBI-15)"""
    simulation = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = [
            'id', 'loan_id', 'category', 'amount', 'tenor',
            'description', 'bank_account',
            'collateral_image', 'salary_slip',
            'status', 'application_date', 'simulation',
        ]
        read_only_fields = ['loan_id', 'status', 'application_date']

    def get_simulation(self, obj):
        return simulate_installment(obj.amount, obj.tenor)

    def validate_amount(self, value):
        if value < 1_000_000:
            raise serializers.ValidationError('Minimal pinjaman Rp 1.000.000')
        if value > 50_000_000:
            raise serializers.ValidationError('Maksimal pinjaman Rp 50.000.000')
        return value

    def validate_tenor(self, value):
        if value not in [6, 12, 24, 36]:
            raise serializers.ValidationError('Tenor harus 6, 12, 24, atau 36 bulan')
        return value

    def validate_bank_account(self, value):
        member = self.context['request'].user.member
        if value and value.member != member:
            raise serializers.ValidationError('Bank account bukan milik member ini')
        return value

    def validate(self, attrs):
        from .services import has_bad_debt, calculate_max_loan_from_savings
        member = self.context['request'].user.member
        if has_bad_debt(member):
            raise serializers.ValidationError(
                'Anda memiliki kredit macet dan tidak dapat mengajukan pinjaman baru.'
            )
        tenor = attrs.get('tenor', 12)
        max_loan = calculate_max_loan_from_savings(member, tenor)
        if max_loan < 1_000_000:
            raise serializers.ValidationError(
                'Simpanan Anda belum mencukupi untuk mengajukan pinjaman.'
            )
        if attrs.get('amount', 0) > max_loan:
            formatted = f"Rp {int(max_loan):,}".replace(',', '.')
            raise serializers.ValidationError(
                f'Jumlah pinjaman melebihi batas maksimal berdasarkan simpanan Anda ({formatted}).'
            )
        return attrs


class LoanSimulationSerializer(serializers.Serializer):
    """Serializer for installment simulation preview"""
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    tenor  = serializers.IntegerField()

    def validate_tenor(self, value):
        if value not in [6, 12, 24, 36]:
            raise serializers.ValidationError('Tenor harus 6, 12, 24, atau 36 bulan')
        return value


class ManagerPendingLoanSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id',
            'loan_id',
            'member_name',
            'category',
            'category_display',
            'amount',
            'tenor',
            'application_date',
            'status',
        ]


class ManagerLoanHistorySerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    reviewed_by_email = serializers.EmailField(source='reviewed_by.email', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id',
            'loan_id',
            'member_name',
            'category',
            'category_display',
            'amount',
            'tenor',
            'application_date',
            'status',
            'reviewed_at',
            'reviewed_by_email',
            'rejection_reason',
        ]


class ManagerAllLoanSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    remaining_balance = serializers.SerializerMethodField()
    due_date = serializers.DateField(source='next_due_date', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id',
            'member_name',
            'loan_id',
            'remaining_balance',
            'due_date',
            'status',
            'status_display',
        ]

    def get_remaining_balance(self, obj):
        total_remaining = (
            obj.installments
            .filter(status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING])
            .aggregate(total=Sum('amount'))['total']
        )
        if total_remaining is not None:
            return total_remaining
        return obj.outstanding_balance


class ManagerMemberLoanHistoryItemSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Loan
        fields = [
            'id',
            'loan_id',
            'amount',
            'status',
            'status_display',
            'application_date',
        ]


class ManagerLoanDetailSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    credit_score = serializers.SerializerMethodField()
    total_savings = serializers.SerializerMethodField()
    active_loans_count = serializers.SerializerMethodField()
    bad_debt_history_count = serializers.SerializerMethodField()
    collateral_image_url = serializers.SerializerMethodField()
    salary_slip_url = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = [
            'id',
            'loan_id',
            'member_name',
            'application_date',
            'status',
            'status_display',
            'rejection_reason',
            'amount',
            'tenor',
            'category',
            'category_display',
            'description',
            'credit_score',
            'total_savings',
            'active_loans_count',
            'bad_debt_history_count',
            'collateral_image_url',
            'salary_slip_url',
        ]

    def _build_file_url(self, file_field):
        if not file_field:
            return None
        request = self.context.get('request')
        url = file_field.url
        return request.build_absolute_uri(url) if request else url

    def get_credit_score(self, obj):
        from .services import calculate_credit_score
        return calculate_credit_score(obj.member)

    def get_total_savings(self, obj):
        balance = getattr(obj.member, 'savings_balance', None)
        return balance.total_overall if balance else 0

    def get_active_loans_count(self, obj):
        return obj.member.loans.filter(status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE]).count()

    def get_bad_debt_history_count(self, obj):
        return BadDebt.objects.filter(loan__member=obj.member).count()

    def get_collateral_image_url(self, obj):
        return self._build_file_url(obj.collateral_image)

    def get_salary_slip_url(self, obj):
        return self._build_file_url(obj.salary_slip)