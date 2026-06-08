from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from dateutil.relativedelta import relativedelta


def calculate_credit_score(member) -> dict:
    """
    Simple credit scoring based on payment history.
    Score range: 300 - 850
    """
    score = 700
    loans = member.loans.exclude(status='PENDING')

    has_active_overdue = False

    for loan in loans:
        for installment in loan.installments.all():
            if installment.status == 'PAID':
                score += 10
            elif installment.status == 'UNPAID' and installment.due_date < timezone.now().date():
                score -= 30
                has_active_overdue = True

        if hasattr(loan, 'bad_debt'):
            score -= 100

    if not has_active_overdue:
        score += 50

    score = max(300, min(850, score))

    if score >= 750:
        label = 'Excellent'
    elif score >= 650:
        label = 'Good'
    elif score >= 500:
        label = 'Fair'
    else:
        label = 'Poor'

    return {'score': score, 'label': label}


def has_bad_debt(member) -> bool:
    """Cek apakah member punya kredit macet aktif"""
    from loans.models import BadDebt
    return BadDebt.objects.filter(loan__member=member).exists()


def calculate_seasoned_savings(member) -> Decimal:
    """
    Simpanan yang sudah 'matang' — total simpanan dikurangi deposit yang
    baru diapprove dalam 30 hari terakhir. Mencegah abuse deposit cepat
    sambil tetap menghargai anggota yang memang kaya simpanan genuinely.
    Menggunakan updated_at (tanggal diapprove) bukan submitted_at.
    """
    from django.db.models import Sum
    from savings.models import SavingTransaction, SavingStatus

    balance = getattr(member, 'savings_balance', None)
    if not balance:
        return Decimal('0')

    cutoff = timezone.now() - timedelta(days=30)
    recent = SavingTransaction.objects.filter(
        member=member,
        status=SavingStatus.SUCCESS,
        updated_at__gte=cutoff,
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    return max(balance.total_overall - recent, Decimal('0'))


def calculate_max_loan_from_savings(member, tenor: int = 12) -> Decimal:
    """
    Hitung batas maksimal pinjaman berdasarkan:
    1. Seasoned savings (total simpanan minus deposit <30 hari)
    2. Dikurangi kewajiban cicilan aktif yang sedang berjalan
    3. Max cicilan baru ≤ 20% × seasoned_savings (MONTHLY_CAPACITY_RATIO)
    Back-calculate dari flat-rate: max_loan = net_monthly × tenor / (1 + 0.005 × tenor)
    """
    ABSOLUTE_CAP = Decimal('50000000')
    MONTHLY_CAPACITY_RATIO = Decimal('0.20')
    INTEREST_RATE = Decimal('0.005')

    seasoned = calculate_seasoned_savings(member)
    max_monthly = seasoned * MONTHLY_CAPACITY_RATIO

    from loans.models import LoanStatus
    active_loans = member.loans.filter(status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE])
    current_obligations = sum(
        (loan.monthly_installment for loan in active_loans),
        Decimal('0')
    )

    net_monthly = max_monthly - current_obligations
    if net_monthly <= 0:
        return Decimal('0')

    tenor_d = Decimal(str(tenor))
    max_loan = net_monthly * tenor_d / (1 + INTEREST_RATE * tenor_d)

    return min(max_loan, ABSOLUTE_CAP)


def simulate_installment(amount: Decimal, tenor: int) -> dict:
    """
    Simulasi cicilan flat rate 0.5% per bulan
    """
    INTEREST_RATE = Decimal('0.005')
    total_interest = amount * INTEREST_RATE * tenor
    total_repayment = amount + total_interest
    monthly = total_repayment / tenor
    principal_per_month = amount / tenor
    interest_per_month = amount * INTEREST_RATE

    return {
        'principal': amount,
        'interest_rate': float(INTEREST_RATE * 100),
        'interest_per_month': round(interest_per_month, 2),
        'principal_per_month': round(principal_per_month, 2),
        'monthly_installment': round(monthly, 2),
        'total_interest': round(total_interest, 2),
        'total_repayment': round(total_repayment, 2),
        'tenor': tenor,
    }


def generate_installment_schedule(loan) -> list:
    """
    Generate jadwal cicilan berdasarkan loan.
    Disbursed date = hari ini, cicilan pertama = 1 bulan setelah pencairan.
    """
    INTEREST_RATE = Decimal('0.005')
    
    total_interest = loan.amount * INTEREST_RATE * loan.tenor
    total_repayment = loan.amount + total_interest

    # 1. Hitung base cicilan bulanan dibulatkan ke int (tanpa koma)
    base_principal = int(loan.amount / loan.tenor)
    base_interest = int(total_interest / loan.tenor)
    base_monthly_amount = base_principal + base_interest

    start_date = loan.disbursed_at.date() if loan.disbursed_at else timezone.now().date()

    schedule = []
    
    # Track akumulasi untuk penyesuaian di bulan terakhir
    accumulated_principal = Decimal('0')
    accumulated_interest = Decimal('0')
    accumulated_total = Decimal('0')

    for i in range(1, loan.tenor + 1):
        due_date = start_date + relativedelta(months=i)
        
        if i == loan.tenor:
            # 2. BULAN TERAKHIR: Sisa dari total tagihan dikurangi akumulasi
            final_principal = loan.amount - accumulated_principal
            final_interest = total_interest - accumulated_interest
            final_monthly_amount = total_repayment - accumulated_total
            
            schedule.append({
                'installment_number': i,
                'due_date': due_date,
                'amount': final_monthly_amount,
                'principal_component': final_principal,
                'interest_component': final_interest,
            })
        else:
            # BULAN 1 s/d N-1: Pakai base bulat
            schedule.append({
                'installment_number': i,
                'due_date': due_date,
                'amount': Decimal(base_monthly_amount),
                'principal_component': Decimal(base_principal),
                'interest_component': Decimal(base_interest),
            })
            
            # Tambahkan ke akumulasi
            accumulated_principal += Decimal(base_principal)
            accumulated_interest += Decimal(base_interest)
            accumulated_total += Decimal(base_monthly_amount)

    return schedule


def create_installments(loan):
    """Buat record Installment setelah loan dicairkan"""
    from loans.models import Installment

    schedule = generate_installment_schedule(loan)
    installments = []

    for item in schedule:
        installments.append(Installment(
            loan=loan,
            installment_number=item['installment_number'],
            due_date=item['due_date'],
            amount=item['amount'],
            principal_component=item['principal_component'],
            interest_component=item['interest_component'],
        ))

    Installment.objects.bulk_create(installments)
    return installments