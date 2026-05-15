import csv
from datetime import datetime

from django.db.models import Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from members.permissions import IsManagerOrAbove

from .models import BadDebt, BadDebtStatus, Installment, InstallmentStatus, Loan, LoanStatus


def _overdue_loan_queryset():
    today = timezone.now().date()
    return (
        Loan.objects
        .filter(
            installments__status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING],
            installments__due_date__lt=today,
        )
        .filter(status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE])
        .select_related('member', 'member__user')
        .distinct()
    )


def _build_overdue_payload(loan, today):
    """Hitung detail tunggakan untuk satu loan."""
    overdue_installments = loan.installments.filter(
        status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING],
        due_date__lt=today,
    ).order_by('due_date')

    earliest_overdue = overdue_installments.first()
    days_late = (today - earliest_overdue.due_date).days if earliest_overdue else 0

    amount_overdue = (
        overdue_installments.aggregate(total=Sum('amount'))['total']
    ) or 0

    bad_debt = getattr(loan, 'bad_debt', None)
    monitoring_status = bad_debt.status if bad_debt else BadDebtStatus.PENDING

    return {
        'id': loan.id,
        'loan_id': loan.loan_id,
        'member_id': loan.member.id,
        'member_name': loan.member.full_name,
        'member_code': loan.member.member_id or '',
        'phone_number': loan.member.phone_number or '',
        'email': loan.member.user.email if loan.member.user else '',
        'days_late': days_late,
        'amount_overdue': amount_overdue,
        'remaining_balance': loan.outstanding_balance,
        'tenor': loan.tenor,
        'status': monitoring_status,
        'status_display': dict(BadDebtStatus.choices).get(monitoring_status, monitoring_status),
        'loan_status': loan.status,
        'loan_status_display': loan.get_status_display(),
        'application_date': loan.application_date,
    }


def _severity(days_late):
    if days_late >= 90:
        return 'CRITICAL'
    if days_late >= 30:
        return 'HIGH'
    if days_late >= 7:
        return 'MEDIUM'
    return 'LOW'


class OverduePagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_data(self, data):
        return {
            'count': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'current_page': self.page.number,
            'page_size': self.get_page_size(self.request),
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data,
        }


class ManagerOverdueLoansView(APIView):
    """GET /api/manager/loans/overdue/"""
    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        today = timezone.now().date()
        search = request.query_params.get('search', '').strip()
        status_filter = request.query_params.get('status', '').strip().upper()

        qs = _overdue_loan_queryset()

        if search:
            qs = qs.filter(
                Q(member__full_name__icontains=search)
                | Q(member__member_id__icontains=search)
                | Q(loan_id__icontains=search)
            )

        valid_statuses = {choice[0] for choice in BadDebtStatus.choices}
        if status_filter and status_filter in valid_statuses:
            if status_filter == BadDebtStatus.PENDING:
                qs = qs.filter(Q(bad_debt__isnull=True) | Q(bad_debt__status=status_filter))
            else:
                qs = qs.filter(bad_debt__status=status_filter)

        qs = qs.order_by('member__full_name', 'loan_id')

        all_overdue = list(_overdue_loan_queryset())
        total_overdue = len(all_overdue)
        total_amount_overdue = sum(
            (
                loan.installments.filter(
                    status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING],
                    due_date__lt=today,
                ).aggregate(total=Sum('amount'))['total'] or 0
            )
            for loan in all_overdue
        )
        total_critical = sum(
            1
            for loan in all_overdue
            if (
                _severity(
                    (
                        today
                        - loan.installments.filter(
                            status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING],
                            due_date__lt=today,
                        ).order_by('due_date').first().due_date
                    ).days
                ) == 'CRITICAL'
            )
        )

        paginator = OverduePagination()
        page = paginator.paginate_queryset(qs, request)
        rows = [_build_overdue_payload(loan, today) for loan in page]
        for row in rows:
            row['severity'] = _severity(row['days_late'])
        payload = paginator.get_paginated_data(rows)

        return Response({
            'summary': {
                'total_overdue': total_overdue,
                'total_amount_overdue': total_amount_overdue,
                'total_critical': total_critical,
            },
            'monitoring_statuses': [
                {'value': value, 'label': label} for value, label in BadDebtStatus.choices
            ],
            'overdue_loans': payload,
        })


class ManagerOverdueLoansExportView(APIView):
    """GET /api/manager/loans/overdue/export/"""
    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        today = timezone.now().date()
        search = request.query_params.get('search', '').strip()
        status_filter = request.query_params.get('status', '').strip().upper()

        qs = _overdue_loan_queryset()
        if search:
            qs = qs.filter(
                Q(member__full_name__icontains=search)
                | Q(member__member_id__icontains=search)
                | Q(loan_id__icontains=search)
            )

        valid_statuses = {choice[0] for choice in BadDebtStatus.choices}
        if status_filter and status_filter in valid_statuses:
            if status_filter == BadDebtStatus.PENDING:
                qs = qs.filter(Q(bad_debt__isnull=True) | Q(bad_debt__status=status_filter))
            else:
                qs = qs.filter(bad_debt__status=status_filter)

        response = HttpResponse(content_type='text/csv')
        filename = f'overdue_loans_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([
            'Loan ID', 'Member ID', 'Member Name', 'Phone', 'Email',
            'Days Late', 'Amount Overdue', 'Remaining Balance', 'Status',
        ])
        for loan in qs.order_by('member__full_name'):
            row = _build_overdue_payload(loan, today)
            writer.writerow([
                row['loan_id'],
                row['member_code'],
                row['member_name'],
                row['phone_number'],
                row['email'],
                row['days_late'],
                str(row['amount_overdue']),
                str(row['remaining_balance']),
                row['status_display'],
            ])
        return response


class ManagerOverdueLoanStatusView(APIView):
    """POST /api/manager/loans/overdue/{id}/status/ - update monitoring status."""
    permission_classes = [IsManagerOrAbove]

    def post(self, request, pk):
        try:
            loan = Loan.objects.select_related('member', 'member__user').get(pk=pk)
        except Loan.DoesNotExist:
            return Response({'error': 'Pinjaman tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        new_status = str(request.data.get('status', '')).strip().upper()
        notes = str(request.data.get('notes', '')).strip()

        valid_statuses = {choice[0] for choice in BadDebtStatus.choices}
        if new_status not in valid_statuses:
            return Response(
                {'error': 'Status monitoring tidak valid.',
                 'allowed': sorted(list(valid_statuses))},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bad_debt, _ = BadDebt.objects.get_or_create(loan=loan)
        bad_debt.status = new_status
        if notes:
            bad_debt.notes = notes
        bad_debt.save()

        return Response({
            'message': 'Status monitoring berhasil diperbarui.',
            'status': bad_debt.status,
            'status_display': bad_debt.get_status_display(),
        })


class ManagerOverdueLoanWarningView(APIView):
    """POST /api/manager/loans/overdue/{id}/warning/ - kirim email + notif warning."""
    permission_classes = [IsManagerOrAbove]

    def post(self, request, pk):
        try:
            loan = Loan.objects.select_related('member', 'member__user').get(pk=pk)
        except Loan.DoesNotExist:
            return Response({'error': 'Pinjaman tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            from notifications.service import notify_loan_overdue
            notify_loan_overdue(loan)
        except Exception:
            return Response(
                {'error': 'Gagal mengirim notifikasi.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        bad_debt, _ = BadDebt.objects.get_or_create(loan=loan)
        if bad_debt.status == BadDebtStatus.PENDING:
            bad_debt.status = BadDebtStatus.WARNING_SENT
            bad_debt.save()

        return Response({
            'message': f'Email peringatan berhasil dikirim ke {loan.member.user.email}.',
            'status': bad_debt.status,
        })
