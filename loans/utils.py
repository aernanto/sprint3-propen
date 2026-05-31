from datetime import date
from decimal import Decimal

from django.db.models import Sum, Q
from django.utils import timezone


def safe_decimal(val):
    try:
        return Decimal(val or 0)
    except Exception:
        try:
            return Decimal(float(val or 0))
        except Exception:
            return Decimal('0')


def get_snapshot_financials():
    """Return snapshot totals used by Manager dashboard.

    Returns dict:
      - total_liquidity
      - total_outstanding_loans
      - interest_income_total (realized interest to date)
      - estimated_shu (interest_income - operational_expenses; expenses assumed 0 if not available)
      - npl_count, npl_amount
    """
    total_liquidity = Decimal('0')
    total_outstanding = Decimal('0')
    interest_income = Decimal('0')
    npl_count = 0
    npl_amount = Decimal('0')

    # Savings balances
    try:
        from savings.models import SavingsBalance

        qs = SavingsBalance.objects.all()
        for acc in qs:
            total_liquidity += safe_decimal(getattr(acc, 'total_pokok', 0))
            total_liquidity += safe_decimal(getattr(acc, 'total_wajib', 0))
            total_liquidity += safe_decimal(getattr(acc, 'total_sukarela', 0))
    except Exception:
        # model missing or error, leave as zero
        pass

    # Outstanding from unpaid installments
    try:
        from .models import Installment, InstallmentStatus, Loan, LoanStatus

        unpaid_total = Installment.objects.filter(
            status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING]
        ).aggregate(total=Sum('amount'))['total'] or 0
        total_outstanding = safe_decimal(unpaid_total)

        # Realized interest = sum interest_component of PAID installments
        paid_interest = Installment.objects.filter(
            status=InstallmentStatus.PAID
        ).aggregate(total=Sum('interest_component'))['total'] or 0
        interest_income = safe_decimal(paid_interest)

        # NPL: align with overdue monitoring (ACTIVE/OVERDUE loans only)
        today = timezone.now().date()
        overdue_installments = Installment.objects.filter(
            status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING],
            due_date__lt=today,
            loan__status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE],
        )
        npl_count = overdue_installments.values('loan_id').distinct().count()
        npl_amount = safe_decimal(
            overdue_installments.aggregate(total=Sum('amount'))['total'] or 0
        )

    except Exception:
        pass

    # Estimated SHU: interest_income - operational expenses (no expenses model => 0)
    estimated_shu = interest_income

    return {
        'total_liquidity': float(total_liquidity),
        'total_outstanding_loans': float(total_outstanding),
        'interest_income_total': float(interest_income),
        'estimated_shu': float(estimated_shu),
        'npl_count': npl_count,
        'npl_amount': float(npl_amount),
    }


def get_period_financials(start_date, end_date):
    """Return cashflow and SHU components for a given date range.

    Returns dict:
      - total_debit
      - total_credit
      - net_cash_flow
      - interest_income_period
      - estimated_shu_period
    """
    total_debit = Decimal('0')
    total_credit = Decimal('0')
    interest_income = Decimal('0')

    # Debit: paid installments (payments) + successful saving transactions
    try:
        from .models import Installment, InstallmentStatus, Loan
        from savings.models import SavingTransaction

        paid_installments = Installment.objects.filter(
            status=InstallmentStatus.PAID,
            paid_at__date__gte=start_date,
            paid_at__date__lte=end_date,
        )
        paid_sum = paid_installments.aggregate(total=Sum('amount'))['total'] or 0
        total_debit += safe_decimal(paid_sum)

        # interest component in period
        interest_sum = paid_installments.aggregate(total=Sum('interest_component'))['total'] or 0
        interest_income += safe_decimal(interest_sum)

        # savings in (successful transactions)
        saving_in_sum = SavingTransaction.objects.filter(
            status='SUCCESS',
            submitted_at__date__gte=start_date,
            submitted_at__date__lte=end_date,
        ).aggregate(total=Sum('amount'))['total'] or 0
        total_debit += safe_decimal(saving_in_sum)

        # Credit: loan disbursements
        disbursed_sum = Loan.objects.filter(
            disbursed_at__date__gte=start_date,
            disbursed_at__date__lte=end_date,
            status__in=[
                'ACTIVE', 'LUNAS', 'OVERDUE', 'LUNAS_AFTER_OVERDUE'
            ],
        ).aggregate(total=Sum('amount'))['total'] or 0
        total_credit += safe_decimal(disbursed_sum)

    except Exception:
        # If models missing, return zeros
        pass

    net_cash = total_debit - total_credit
    estimated_shu = interest_income

    return {
        'total_debit': float(total_debit),
        'total_credit': float(total_credit),
        'net_cash_flow': float(net_cash),
        'interest_income_period': float(interest_income),
        'estimated_shu_period': float(estimated_shu),
    }
