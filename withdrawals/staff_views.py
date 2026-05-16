from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from members.permissions import IsStaffOrAbove

from .models import WithdrawalRequest, WithdrawalStatus
from .serializers import WithdrawalRequestSerializer


class StandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_data(self, data):
        return {
            'count': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'current_page': self.page.number,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data,
        }


class StaffWithdrawalListView(APIView):
    """
    GET /api/staff/withdrawals/
    Staff melihat daftar pengajuan penarikan simpanan sukarela.
    """
    permission_classes = [IsStaffOrAbove]

    def _parse_date(self, date_str):
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None

    def get(self, request):
        qs = (
            WithdrawalRequest.objects
            .select_related('member')
            .order_by('-requested_at')
        )

        scope = request.query_params.get('scope', 'pending').strip().lower()
        if scope == 'pending':
            qs = qs.filter(status=WithdrawalStatus.PENDING)
        elif scope == 'history':
            qs = qs.exclude(status=WithdrawalStatus.PENDING)
        elif scope != 'all':
            return Response(
                {'error': 'Scope tidak valid. Gunakan pending, history, atau all.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(member__full_name__icontains=search)
                | Q(member__member_id__icontains=search)
                | Q(withdrawal_id__icontains=search)
            )

        status_filter = request.query_params.get('status', '').strip().upper()
        if status_filter:
            valid = {s for s, _ in WithdrawalStatus.choices}
            if status_filter not in valid:
                return Response(
                    {'error': f'Status tidak valid. Gunakan salah satu dari: {", ".join(sorted(valid))}.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            qs = qs.filter(status=status_filter)

        start_date = self._parse_date(request.query_params.get('start_date', ''))
        if start_date:
            qs = qs.filter(requested_at__date__gte=start_date)

        end_date = self._parse_date(request.query_params.get('end_date', ''))
        if end_date:
            qs = qs.filter(requested_at__date__lte=end_date)

        total_pending = WithdrawalRequest.objects.filter(status=WithdrawalStatus.PENDING).count()
        total_approved = WithdrawalRequest.objects.filter(status=WithdrawalStatus.APPROVED).count()

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)

        rows = []
        for wd in page:
            rows.append({
                'id': wd.id,
                'withdrawal_id': wd.withdrawal_id,
                'member_name': wd.member.full_name,
                'member_id': wd.member.member_id or '',
                'amount': str(wd.amount),
                'status': wd.status,
                'status_display': wd.get_status_display(),
                'bank_name': wd.bank_name,
                'account_number': wd.account_number,
                'account_holder': wd.account_holder,
                'requested_at': wd.requested_at,
                'reviewed_at': wd.reviewed_at,
            })

        return Response({
            'summary': {
                'total_pending': total_pending,
                'total_approved': total_approved,
            },
            **paginator.get_paginated_data(rows),
        })


class StaffWithdrawalStatusUpdateView(APIView):
    """
    POST /api/staff/withdrawals/{id}/status/
    Body: {"action": "approve"} atau {"action": "reject", "reason": "..."}
    """
    permission_classes = [IsStaffOrAbove]

    def post(self, request, pk):
        try:
            withdrawal = WithdrawalRequest.objects.select_related('member', 'member__user').get(pk=pk)
        except WithdrawalRequest.DoesNotExist:
            return Response({'error': 'Pengajuan penarikan tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        if withdrawal.status != WithdrawalStatus.PENDING:
            return Response(
                {'error': f'Hanya pengajuan PENDING yang dapat diproses. Status saat ini: {withdrawal.status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        action = str(request.data.get('action', '')).strip().lower()
        reason = str(request.data.get('reason', '')).strip()

        if action not in {'approve', 'reject'}:
            return Response(
                {'error': 'Action tidak valid. Gunakan approve atau reject.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action == 'reject' and not reason:
            return Response(
                {'error': 'Alasan penolakan wajib diisi untuk aksi reject.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            withdrawal.reviewed_by = request.user
            withdrawal.reviewed_at = timezone.now()

            if action == 'approve':
                from savings.models import SavingsBalance
                balance = SavingsBalance.objects.select_for_update().filter(member=withdrawal.member).first()
                current_sukarela = balance.total_sukarela if balance else 0

                if current_sukarela < withdrawal.amount:
                    return Response(
                        {
                            'error': (
                                'Saldo simpanan sukarela tidak mencukupi untuk memproses penarikan ini. '
                                f'Saldo saat ini: {current_sukarela}.'
                            ),
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                withdrawal.status = WithdrawalStatus.APPROVED
                withdrawal.rejection_reason = ''
                withdrawal.save()

                # Create a refund record for staff to disburse
                try:
                    from refunds.services import create_refund_from_withdrawal
                    create_refund_from_withdrawal(withdrawal)
                except Exception:
                    pass

            else:
                withdrawal.status = WithdrawalStatus.REJECTED
                withdrawal.rejection_reason = reason
                withdrawal.save()

        try:
            if action == 'approve':
                from notifications.service import notify_withdrawal_approved
                notify_withdrawal_approved(withdrawal)
            else:
                from notifications.service import notify_withdrawal_rejected
                notify_withdrawal_rejected(withdrawal, reason)
        except Exception:
            pass

        return Response({
            'message': (
                'Pengajuan penarikan berhasil disetujui.'
                if action == 'approve' else
                'Pengajuan penarikan berhasil ditolak.'
            ),
            'status': withdrawal.status,
        })
