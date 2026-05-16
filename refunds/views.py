from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from members.permissions import IsStaffOrAbove
from resignations.models import ResignationStatus

from .models import Refund, RefundSourceType, RefundStatus


class RefundPagination(PageNumberPagination):
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


def _parse_date(date_str):
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


class StaffRefundListView(APIView):
    """
    GET /api/staff/refunds/
    Staff melihat daftar dana yang perlu dikembalikan.
    """
    permission_classes = [IsStaffOrAbove]

    def get(self, request):
        qs = (
            Refund.objects
            .select_related(
                'member',
                'installment', 'installment__loan',
                'resignation',
            )
            .order_by('-approved_at')
        )

        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(member__full_name__icontains=search)
                | Q(member__member_id__icontains=search)
            )

        start_date = _parse_date(request.query_params.get('start_date', ''))
        if start_date:
            qs = qs.filter(approved_at__date__gte=start_date)

        end_date = _parse_date(request.query_params.get('end_date', ''))
        if end_date:
            qs = qs.filter(approved_at__date__lte=end_date)

        status_filter = request.query_params.get('status', '').strip().upper()
        if status_filter in {RefundStatus.PENDING, RefundStatus.COMPLETED}:
            qs = qs.filter(status=status_filter)

        total_pending = Refund.objects.filter(status=RefundStatus.PENDING).count()
        total_completed = Refund.objects.filter(status=RefundStatus.COMPLETED).count()

        paginator = RefundPagination()
        page = paginator.paginate_queryset(qs, request)

        rows = []
        for refund in page:
            loan_id = None
            if refund.source_type == RefundSourceType.INSTALLMENT and refund.installment:
                loan_id = refund.installment.loan.loan_id

            rows.append({
                'id': refund.id,
                'source_type': refund.source_type,
                'source_type_display': refund.get_source_type_display(),
                'loan_id': loan_id,
                'member_name': refund.member.full_name,
                'member_id': refund.member.member_id or '',
                'amount': str(refund.amount),
                'status': refund.status,
                'status_display': refund.get_status_display(),
                'approved_at': refund.approved_at,
                'disbursed_at': refund.disbursed_at,
            })

        return Response({
            'summary': {
                'total_pending': total_pending,
                'total_completed': total_completed,
            },
            **paginator.get_paginated_data(rows),
        })


class StaffRefundDetailView(APIView):
    """
    GET /api/staff/refunds/{id}/
    Detail refund termasuk info bank tujuan transfer.
    """
    permission_classes = [IsStaffOrAbove]

    def get(self, request, pk):
        try:
            refund = Refund.objects.select_related(
                'member',
                'installment', 'installment__loan', 'installment__bank_account',
                'resignation',
                'disbursed_by',
            ).get(pk=pk)
        except Refund.DoesNotExist:
            return Response({'error': 'Data pengembalian dana tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        member = refund.member
        bank_info = _resolve_bank_info(refund, member)

        loan_id = None
        if refund.source_type == RefundSourceType.INSTALLMENT and refund.installment:
            loan_id = refund.installment.loan.loan_id

        return Response({
            'id': refund.id,
            'source_type': refund.source_type,
            'source_type_display': refund.get_source_type_display(),
            'loan_id': loan_id,
            'member_name': member.full_name,
            'member_id': member.member_id or '',
            'amount': str(refund.amount),
            'status': refund.status,
            'status_display': refund.get_status_display(),
            'approved_at': refund.approved_at,
            'disbursed_at': refund.disbursed_at,
            'disbursed_by_email': refund.disbursed_by.email if refund.disbursed_by else None,
            'notes': refund.notes,
            'bank_info': bank_info,
            'transfer_proof_url': (
                request.build_absolute_uri(refund.transfer_proof.url)
                if refund.transfer_proof else None
            ),
        })


class StaffRefundStatusUpdateView(APIView):
    """
    POST /api/staff/refunds/{id}/status/
    Staff mengkonfirmasi pencairan dana (upload bukti transfer).
    """
    permission_classes = [IsStaffOrAbove]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        try:
            refund = Refund.objects.select_related(
                'member', 'member__user',
                'resignation', 'resignation__member',
                'installment', 'installment__loan',
            ).get(pk=pk)
        except Refund.DoesNotExist:
            return Response({'error': 'Data pengembalian dana tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        if refund.status == RefundStatus.COMPLETED:
            return Response(
                {'error': 'Dana sudah dicairkan sebelumnya.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transfer_proof = request.FILES.get('transfer_proof')
        if not transfer_proof:
            return Response(
                {'error': 'Bukti transfer wajib diunggah.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            refund.status = RefundStatus.COMPLETED
            refund.disbursed_by = request.user
            refund.disbursed_at = timezone.now()
            refund.transfer_proof = transfer_proof
            refund.notes = str(request.data.get('notes', '')).strip()
            refund.save()

            # Source-specific post-disbursement actions
            if refund.source_type == RefundSourceType.RESIGNATION:
                _complete_resignation(refund)

            # INSTALLMENT refund: no balance adjustment needed — the money
            # was a failed bank transfer; balance was already restored in
            # StaffInstallmentStatusUpdateView (SAVINGS method) or was never
            # debited (BANK_TRANSFER method).

        try:
            from notifications.service import notify_refund_completed
            notify_refund_completed(refund)
        except Exception:
            pass

        return Response({
            'message': 'Dana berhasil dicairkan.',
            'id': refund.id,
            'status': refund.status,
            'status_display': refund.get_status_display(),
            'disbursed_at': refund.disbursed_at,
        })


# ── Helpers ────────────────────────────────────────────────────────────────

def _resolve_bank_info(refund, member):
    """Return best available bank account info for the refund recipient."""
    primary = member.bank_accounts.filter(is_primary=True).first()
    if primary:
        return {
            'bank_name': primary.bank_name,
            'account_number': primary.account_number,
            'account_holder': primary.account_holder,
        }

    if refund.source_type == RefundSourceType.INSTALLMENT and refund.installment and refund.installment.bank_account:
        ba = refund.installment.bank_account
        return {
            'bank_name': ba.bank_name,
            'account_number': ba.account_number,
            'account_holder': ba.account_holder,
        }

    return None


def _complete_resignation(refund):
    """Mark resignation RESIGNED, deactivate member account, zero savings."""
    from resignations.models import ResignationStatus

    resignation = refund.resignation
    if not resignation or resignation.status != ResignationStatus.APPROVED:
        return

    resignation.status = ResignationStatus.RESIGNED
    resignation.resolved_at = timezone.now()
    resignation.save(update_fields=['status', 'resolved_at', 'updated_at'])

    member = resignation.member
    member.status = 'INACTIVE'
    member.save(update_fields=['status'])

    if hasattr(member, 'user') and member.user:
        member.user.is_active = False
        member.user.save(update_fields=['is_active'])

    try:
        balance = member.savings_balance
        balance.total_pokok = 0
        balance.total_wajib = 0
        balance.total_sukarela = 0
        balance.save(update_fields=['total_pokok', 'total_wajib', 'total_sukarela', 'last_updated'])
    except Exception:
        pass

