from decimal import Decimal

from django.db.models import Sum

from loans.models import InstallmentStatus, Loan, LoanStatus


def get_total_savings(member):
    """Return dict simpanan member berdasarkan SavingsBalance."""
    balance = getattr(member, 'savings_balance', None)
    if balance is None:
        zero = Decimal('0')
        return {
            'total_pokok': zero,
            'total_wajib': zero,
            'total_sukarela': zero,
            'total_overall': zero,
        }
    return {
        'total_pokok': balance.total_pokok or Decimal('0'),
        'total_wajib': balance.total_wajib or Decimal('0'),
        'total_sukarela': balance.total_sukarela or Decimal('0'),
        'total_overall': balance.total_overall or Decimal('0'),
    }


def get_total_loan_outstanding(member):
    """
    Sisa pinjaman aktif member (pokok + bunga belum dibayar).
    Dipakai untuk perhitungan settlement penutupan akun.
    """
    active_loans = member.loans.filter(
        status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE, LoanStatus.APPROVED]
    )
    total = Decimal('0')
    for loan in active_loans:
        remaining = (
            loan.installments
            .filter(status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING])
            .aggregate(total=Sum('amount'))['total']
        )
        total += remaining if remaining is not None else loan.outstanding_balance
    return total


def calculate_settlement(member):
    """
    Hitung settlement: total simpanan - total pinjaman.
    Return dict berisi snapshot dan estimasi payout.
    """
    savings = get_total_savings(member)
    total_loan = get_total_loan_outstanding(member)
    estimated_payout = savings['total_overall'] - total_loan
    return {
        'total_pokok': savings['total_pokok'],
        'total_wajib': savings['total_wajib'],
        'total_sukarela': savings['total_sukarela'],
        'total_savings': savings['total_overall'],
        'total_loan_outstanding': total_loan,
        'estimated_payout': estimated_payout,
    }
