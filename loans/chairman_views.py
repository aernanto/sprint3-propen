from django.utils import timezone
from datetime import date, datetime, timedelta
from django.db.models import Sum, Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from decimal import Decimal

from members.permissions import IsManagerOrAbove
from .models import Loan, LoanStatus, Installment, InstallmentStatus


class ChairmanCashflowView(APIView):
    """
    GET /api/chairman/cashflow/
    
    Mengembalikan:
    - Summary: total debit, total kredit, net cash flow
    - Detail transaction: list transaksi dengan filtering tanggal
    - Support custom date range filtering
    
    Query params:
    - start_date: YYYY-MM-DD (default: first day of current month)
    - end_date: YYYY-MM-DD (default: today)
    """
    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        try:
            # Get date range from query params
            start_date = request.query_params.get('start_date')
            end_date = request.query_params.get('end_date')
            
            # Default date range: current month (full month)
            today = timezone.now().date()
            month_start = date(today.year, today.month, 1)
            month_end = date(today.year, today.month + 1, 1) - timedelta(days=1) if today.month < 12 else date(today.year, 12, 31)
            if not start_date:
                start_date = month_start
            else:
                try:
                    start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                except ValueError:
                    return Response(
                        {'error': 'Invalid start_date format. Use YYYY-MM-DD'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            if not end_date:
                end_date = month_end
            else:
                try:
                    end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                except ValueError:
                    return Response(
                        {'error': 'Invalid end_date format. Use YYYY-MM-DD'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            # Use shared finance util for period calculations
            from .utils import get_period_financials

            period = get_period_financials(start_date, end_date)

            # Build basic transactions list (payments + disbursements) for detail view
            transactions = []
            paid_installments = Installment.objects.filter(
                status=InstallmentStatus.PAID,
                paid_at__date__gte=start_date,
                paid_at__date__lte=end_date,
            ).select_related('loan', 'loan__member').order_by('-paid_at')

            for installment in paid_installments:
                transactions.append({
                    'id': installment.id,
                    'transaction_id': installment.transaction_id,
                    'date': installment.paid_at.strftime('%Y-%m-%d %H:%M:%S') if installment.paid_at else None,
                    'description': f"Angsuran Pinjaman #{installment.installment_number} - {installment.loan.member.full_name}",
                    'category': 'PEMBAYARAN_ANGSURAN',
                    'debit': float(installment.amount),
                    'credit': 0,
                    'member_name': installment.loan.member.full_name,
                    'loan_id': installment.loan.loan_id,
                })

            disbursed_loans = Loan.objects.filter(
                disbursed_at__date__gte=start_date,
                disbursed_at__date__lte=end_date,
            )
            for loan in disbursed_loans:
                transactions.append({
                    'id': f'disburse-{loan.id}',
                    'transaction_id': loan.loan_id,
                    'date': loan.disbursed_at.strftime('%Y-%m-%d %H:%M:%S') if loan.disbursed_at else None,
                    'description': f"Pencairan Pinjaman - {loan.member.full_name}",
                    'category': 'PENCAIRAN_PINJAMAN',
                    'debit': 0,
                    'credit': float(loan.amount),
                    'member_name': loan.member.full_name,
                    'loan_id': loan.loan_id,
                })

            transactions.sort(key=lambda x: x['date'] or '', reverse=True)

            return Response({
                'status': 'success',
                'data': {
                    'summary': {
                        'total_debit': period.get('total_debit', 0),
                        'total_credit': period.get('total_credit', 0),
                        'net_cash_flow': period.get('net_cash_flow', 0),
                        'interest_income_period': period.get('interest_income_period', 0),
                        'estimated_shu_period': period.get('estimated_shu_period', 0),
                    },
                    'date_range': {
                        'start_date': start_date.strftime('%Y-%m-%d'),
                        'end_date': end_date.strftime('%Y-%m-%d'),
                    },
                    'transactions': transactions,
                    'transaction_count': len(transactions),
                }
            })
        
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
