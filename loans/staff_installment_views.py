from datetime import datetime
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from members.permissions import IsStaffOrAbove
from savings.models import SavingsBalance

from .models import Installment, InstallmentStatus, LoanStatus


class StandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'current_page': self.page.number,
            'page_size': self.get_page_size(self.request),
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data,
        })


class StaffPendingInstallmentListView(APIView):
    permission_classes = [IsStaffOrAbove]

    def _extract_date(self, date_str: str):
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return None

    def get(self, request):
        queryset = (
            Installment.objects
            .select_related('loan', 'loan__member')
            .order_by('-updated_at', '-submitted_at')
        )

        scope = request.query_params.get('scope', 'pending').strip().lower()
        valid_scopes = {'pending', 'history', 'all'}
        if scope not in valid_scopes:
            return Response(
                {'error': f'Scope tidak valid. Gunakan salah satu dari: {", ".join(sorted(valid_scopes))}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if scope == 'pending':
            queryset = queryset.filter(status=InstallmentStatus.PENDING)
        elif scope == 'history':
            queryset = queryset.exclude(status=InstallmentStatus.PENDING).exclude(transaction_id__isnull=True)
        elif scope == 'all':
            queryset = queryset.exclude(transaction_id__isnull=True)

        search = request.query_params.get('search', '').strip()
        if search:
            search_query = (
                Q(loan__member__full_name__icontains=search)
                | Q(loan__loan_id__icontains=search)
                | Q(transaction_id__icontains=search)
            )
            parsed_search_date = self._extract_date(search)
            if parsed_search_date:
                search_query |= Q(submitted_at__date=parsed_search_date) | Q(updated_at__date=parsed_search_date)
            queryset = queryset.filter(search_query)

        status_filter = request.query_params.get('status', '').strip().upper()
        if status_filter:
            valid_statuses = {choice for choice, _ in InstallmentStatus.choices}
            if status_filter not in valid_statuses:
                return Response(
                    {'error': f'Status tidak valid. Gunakan salah satu dari: {", ".join(sorted(valid_statuses))}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(status=status_filter)

        rejected_only = request.query_params.get('rejected_only', '').strip().lower() in {'1', 'true', 'yes'}
        if rejected_only:
            queryset = queryset.filter(
                status=InstallmentStatus.UNPAID,
                rejection_reason__isnull=False,
            ).exclude(rejection_reason='')

        start_date = request.query_params.get('start_date', '').strip()
        if start_date:
            parsed_start = self._extract_date(start_date)
            if not parsed_start:
                return Response(
                    {'error': 'Format start_date tidak valid. Gunakan format YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if scope == 'history':
                queryset = queryset.filter(updated_at__date__gte=parsed_start)
            else:
                queryset = queryset.filter(submitted_at__date__gte=parsed_start)

        end_date = request.query_params.get('end_date', '').strip()
        if end_date:
            parsed_end = self._extract_date(end_date)
            if not parsed_end:
                return Response(
                    {'error': 'Format end_date tidak valid. Gunakan format YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if scope == 'history':
                queryset = queryset.filter(updated_at__date__lte=parsed_end)
            else:
                queryset = queryset.filter(submitted_at__date__lte=parsed_end)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)

        rows = []
        for installment in page:
            rows.append({
                'id': installment.id,
                'loan_pk': installment.loan_id,
                'transaction_id': installment.transaction_id,
                'submitted_at': installment.submitted_at,
                'paid_at': installment.paid_at,
                'updated_at': installment.updated_at,
                'member_name': installment.loan.member.full_name,
                'loan_id': installment.loan.loan_id,
                'amount': str(installment.amount),
                'status': installment.status,
                'status_display': installment.get_status_display(),
            })

        return paginator.get_paginated_response(rows)


class StaffPendingInstallmentDetailView(APIView):
    permission_classes = [IsStaffOrAbove]

    def get(self, request, pk):
        try:
            installment = Installment.objects.select_related(
                'loan',
                'loan__member',
                'verified_by',
                'bank_account',
            ).get(pk=pk)
        except Installment.DoesNotExist:
            return Response({'error': 'Cicilan tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            'id': installment.id,
            'transaction_id': installment.transaction_id,
            'installment_number': installment.installment_number,
            'due_date': installment.due_date,
            'submitted_at': installment.submitted_at,
            'paid_at': installment.paid_at,
            'amount': str(installment.amount),
            'principal_component': str(installment.principal_component),
            'interest_component': str(installment.interest_component),
            'payment_method': installment.payment_method,
            'status': installment.status,
            'status_display': installment.get_status_display(),
            'rejection_reason': installment.rejection_reason,
            'member_name': installment.loan.member.full_name,
            'member_email': installment.loan.member.user.email,
            'member_id': installment.loan.member.member_id,
            'loan_pk': installment.loan_id,
            'loan_id': installment.loan.loan_id,
            'transfer_proof_url': (
                request.build_absolute_uri(installment.transfer_proof.url)
                if installment.transfer_proof else None
            ),
            'verified_by_email': installment.verified_by.email if installment.verified_by else None,
            'bank_name': installment.bank_account.bank_name if installment.bank_account else None,
            'account_number': installment.bank_account.account_number if installment.bank_account else None,
            'account_holder': installment.bank_account.account_holder if installment.bank_account else None,
        }, status=status.HTTP_200_OK)


class StaffInstallmentStatusUpdateView(APIView):
    permission_classes = [IsStaffOrAbove]

    def post(self, request, pk):
        try:
            installment = Installment.objects.select_related('loan', 'loan__member').get(pk=pk)
        except Installment.DoesNotExist:
            return Response({'error': 'Cicilan tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        if installment.status != InstallmentStatus.PENDING:
            return Response(
                {
                    'error': (
                        f'Hanya cicilan dengan status PENDING yang bisa diverifikasi. '
                        f'Status saat ini: {installment.get_status_display()}.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        action = str(request.data.get('action', '')).strip().lower()
        rejection_reason = str(request.data.get('rejection_reason', '')).strip()

        if action not in {'approve', 'reject'}:
            return Response(
                {'error': 'Action tidak valid. Gunakan approve atau reject.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action == 'reject' and not rejection_reason:
            return Response(
                {'error': 'Alasan penolakan wajib diisi untuk aksi reject.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        loan = installment.loan
        if loan.status in {LoanStatus.LUNAS, LoanStatus.LUNAS_AFTER_OVERDUE}:
            return Response(
                {'error': 'Pinjaman sudah lunas. Verifikasi pembayaran tidak dapat dilakukan.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action == 'approve':
            with transaction.atomic():
                installment.status = InstallmentStatus.PAID
                installment.paid_at = installment.paid_at or timezone.now()
                installment.verified_by = request.user
                installment.rejection_reason = ''

                has_non_paid_other_installments = loan.installments.exclude(pk=installment.pk).exclude(
                    status=InstallmentStatus.PAID
                ).exists()
                if not has_non_paid_other_installments:
                    if loan.status == LoanStatus.OVERDUE:
                        loan.status = LoanStatus.LUNAS_AFTER_OVERDUE
                    else:
                        loan.status = LoanStatus.LUNAS
                    loan.save(update_fields=['status', 'updated_at'])

                installment.save(update_fields=['status', 'paid_at', 'verified_by', 'rejection_reason', 'updated_at'])

            return Response(
                {
                    'message': 'Pembayaran cicilan berhasil diverifikasi dan disetujui.',
                    'installment': {
                        'id': installment.id,
                        'transaction_id': installment.transaction_id,
                        'loan_pk': loan.id,
                        'status': installment.status,
                        'status_display': installment.get_status_display(),
                        'submitted_at': installment.submitted_at,
                        'paid_at': installment.paid_at,
                        'member_name': loan.member.full_name,
                        'member_id': loan.member.member_id,
                        'loan_id': loan.loan_id,
                        'amount': str(installment.amount),
                        'transfer_proof_url': (
                            request.build_absolute_uri(installment.transfer_proof.url)
                            if installment.transfer_proof else None
                        ),
                    },
                    'payment_breakdown': {
                        'principal_component': str(installment.principal_component),
                        'interest_component': str(installment.interest_component),
                    },
                    'loan_status': loan.status,
                    'cash_in_recorded': True,
                },
                status=status.HTTP_200_OK,
            )

        refund_amount = Decimal('0')
        with transaction.atomic():
            if installment.payment_method == 'SAVINGS':
                balance = SavingsBalance.objects.select_for_update().filter(member=loan.member).first()
                if balance:
                    refund_amount = Decimal(str(installment.amount))
                    balance.total_sukarela = Decimal(str(balance.total_sukarela or 0)) + refund_amount
                    balance.save(update_fields=['total_sukarela', 'last_updated'])

            installment.status = InstallmentStatus.UNPAID
            installment.rejection_reason = rejection_reason
            installment.verified_by = request.user
            installment.submitted_at = None
            installment.save(update_fields=['status', 'rejection_reason', 'verified_by', 'submitted_at', 'updated_at'])

            # For BANK_TRANSFER rejections, create a refund record so staff can return the money
            if installment.payment_method == 'BANK_TRANSFER':
                try:
                    from refunds.services import create_refund_from_installment
                    create_refund_from_installment(installment)
                except Exception:
                    pass

        return Response(
            {
                'message': 'Pembayaran cicilan ditolak. Status dikembalikan ke UNPAID.',
                'installment': {
                    'id': installment.id,
                    'transaction_id': installment.transaction_id,
                    'loan_pk': loan.id,
                    'status': installment.status,
                    'status_display': installment.get_status_display(),
                    'submitted_at': installment.submitted_at,
                    'paid_at': installment.paid_at,
                    'member_name': loan.member.full_name,
                    'member_id': loan.member.member_id,
                    'loan_id': loan.loan_id,
                    'amount': str(installment.amount),
                    'rejection_reason': installment.rejection_reason,
                    'transfer_proof_url': (
                        request.build_absolute_uri(installment.transfer_proof.url)
                        if installment.transfer_proof else None
                    ),
                },
                'refunded_sukarela': str(refund_amount),
            },
            status=status.HTTP_200_OK,
        )
