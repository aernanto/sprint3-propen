from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db.models import Q

from .models import Loan, LoanStatus
from .serializers import (
    LoanOverviewSerializer,
    LoanListSerializer,
    LoanDetailSerializer,
    LoanCreateSerializer,
    LoanSimulationSerializer,
)
from .services import calculate_credit_score, has_bad_debt, simulate_installment, calculate_max_loan_from_savings
from members.models import BankAccount
from members.serializers import BankAccountSerializer


class LoanOverviewView(APIView):
    """
    PBI-14 - Lihat Pinjaman Overview
    GET /api/loans/
    Returns: summary cards + loan list
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            member = request.user.member
        except Exception:
            return Response({'error': 'Member profile not found'}, status=404)

        loans = member.loans.all()

        # Filter by status
        status_filter = request.query_params.get('status')
        if status_filter:
            loans = loans.filter(status=status_filter)

        # Search by loan ID
        search = request.query_params.get('search')
        if search:
            loans = loans.filter(loan_id__icontains=search)

        # Summary cards
        total_outstanding = sum(
            loan.outstanding_balance
            for loan in member.loans.filter(status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE])
        )

        # Next due date across all active loans
        next_due = None
        next_due_amount = None
        next_due_loan_id = None

        active_loans = member.loans.filter(status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE])
        for loan in active_loans:
            if loan.next_due_date:
                if next_due is None or loan.next_due_date < next_due:
                    next_due = loan.next_due_date
                    next_due_amount = loan.next_installment_amount
                    next_due_loan_id = loan.loan_id

        credit_score = calculate_credit_score(member)

        loan_data = LoanOverviewSerializer(loans, many=True).data

        return Response({
            'summary': {
                'total_outstanding': total_outstanding,
                'next_due_date': next_due,
                'next_due_amount': next_due_amount,
                'next_due_loan_id': next_due_loan_id,
                'credit_score': credit_score,
            },
            'loans': loan_data,
        })


class LoanCreateView(APIView):
    """
    PBI-15 - Tambah Pinjaman
    POST /api/loans/create/
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        """
        Returns form data: bank accounts + loan categories
        """
        try:
            member = request.user.member
        except Exception:
            return Response({'error': 'Member profile not found'}, status=404)

        bank_accounts = member.bank_accounts.all()

        from .models import LoanCategory
        categories = [
            {'value': c.value, 'label': c.label}
            for c in LoanCategory
        ]

        tenor_choices = [6, 12, 24, 36]
        max_amount_by_tenor = {
            t: float(calculate_max_loan_from_savings(member, t))
            for t in tenor_choices
        }

        from .services import calculate_seasoned_savings
        from .models import LoanStatus

        balance = getattr(member, 'savings_balance', None)
        total_savings = float(balance.total_overall) if balance else 0
        seasoned_savings = float(calculate_seasoned_savings(member))

        active_loans = member.loans.filter(status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE])
        current_monthly_obligations = float(
            sum(loan.monthly_installment for loan in active_loans) or 0
        )

        return Response({
            'bank_accounts': BankAccountSerializer(bank_accounts, many=True).data,
            'categories': categories,
            'tenor_choices': tenor_choices,
            'interest_rate': 0.5,
            'min_amount': 1_000_000,
            'max_amount': max_amount_by_tenor[12],
            'max_amount_by_tenor': max_amount_by_tenor,
            'seasoned_savings': seasoned_savings,
            'total_savings': total_savings,
            'current_monthly_obligations': current_monthly_obligations,
            'member_status': member.status,
            'has_bad_debt': has_bad_debt(member),
        })

    def post(self, request):
        try:
            member = request.user.member
        except Exception:
            return Response({'error': 'Member profile not found'}, status=404)

        if member.status != 'ACTIVE':
            return Response(
                {'error': 'Hanya anggota aktif yang dapat mengajukan pinjaman.'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = LoanCreateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        loan = serializer.save(member=member)

        # Trigger notifikasi
        try:
            from notifications.service import notify_loan_submitted
            notify_loan_submitted(loan)
        except Exception:
            pass

        return Response(
            LoanCreateSerializer(loan, context={'request': request}).data,
            status=status.HTTP_201_CREATED
        )


class LoanSimulationView(APIView):
    """
    Preview simulasi cicilan (tanpa login untuk UX yang lebih baik)
    GET /api/loans/simulation/?amount=10000000&tenor=12
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = LoanSimulationSerializer(data=request.query_params)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        result = simulate_installment(
            serializer.validated_data['amount'],
            serializer.validated_data['tenor'],
        )
        return Response(result)


class LoanDetailView(APIView):
    """
    PBI-16 - Lihat Detail Pinjaman (Anggota)
    GET /api/loans/{id}/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            member = request.user.member
            loan = member.loans.get(pk=pk)
        except Loan.DoesNotExist:
            return Response({'error': 'Pinjaman tidak ditemukan'}, status=404)
        except Exception:
            return Response({'error': 'Member profile not found'}, status=404)

        return Response(LoanDetailSerializer(loan).data)