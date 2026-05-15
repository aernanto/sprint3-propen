import csv
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from members.permissions import IsManagerOrAbove

from .models import ResignationRequest, ResignationStatus
from .serializers import (
    ManagerResignationHistoryItemSerializer,
    ManagerResignationListItemSerializer,
)
from .services import calculate_settlement, get_total_loan_outstanding, get_total_savings


class StandardPagination(PageNumberPagination):
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


class HistoryPagination(StandardPagination):
    page_query_param = 'history_page'
    page_size_query_param = 'history_page_size'


class ManagerResignationListView(APIView):
    """
    GET /api/manager/resignations/

    Mengembalikan ringkasan + tabel pengajuan penutupan akun.
    """
    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        search = request.query_params.get('search', '').strip()
        history_search = request.query_params.get('history_search', '').strip()
        status_filter = request.query_params.get('status', '').strip().upper()

        pending_qs = (
            ResignationRequest.objects
            .filter(status=ResignationStatus.PENDING)
            .select_related('member')
            .order_by('-submitted_at')
        )

        if search:
            pending_qs = pending_qs.filter(
                Q(member__full_name__icontains=search) | Q(member__member_id__icontains=search)
            )

        if status_filter and status_filter in {ResignationStatus.PENDING, ResignationStatus.REJECTED}:
            pending_qs = pending_qs.filter(status=status_filter)

        history_qs = (
            ResignationRequest.objects
            .filter(status=ResignationStatus.RESIGNED)
            .select_related('member')
            .order_by('-resolved_at', '-reviewed_at')
        )

        if history_search:
            history_qs = history_qs.filter(
                Q(member__full_name__icontains=history_search)
                | Q(member__member_id__icontains=history_search)
            )

        total_pending = ResignationRequest.objects.filter(status=ResignationStatus.PENDING).count()
        total_inactive = ResignationRequest.objects.filter(status=ResignationStatus.RESIGNED).count()

        paginator = StandardPagination()
        pending_page = paginator.paginate_queryset(pending_qs, request)
        pending_data = ManagerResignationListItemSerializer(pending_page, many=True).data
        pending_payload = paginator.get_paginated_data(pending_data)

        history_paginator = HistoryPagination()
        history_page = history_paginator.paginate_queryset(history_qs, request)
        history_data = ManagerResignationHistoryItemSerializer(history_page, many=True).data
        history_payload = history_paginator.get_paginated_data(history_data)

        return Response({
            'summary': {
                'total_pending': total_pending,
                'total_inactive': total_inactive,
            },
            'pending_requests': pending_payload,
            'history_requests': history_payload,
        })


class ManagerResignationDetailView(APIView):
    """
    GET /api/manager/resignations/{id}/

    Detail untuk halaman review manajer.
    """
    permission_classes = [IsManagerOrAbove]

    def get(self, request, pk):
        try:
            resignation = ResignationRequest.objects.select_related('member', 'member__user').get(pk=pk)
        except ResignationRequest.DoesNotExist:
            return Response(
                {'error': 'Pengajuan penutupan akun tidak ditemukan.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        member = resignation.member

        if resignation.status == ResignationStatus.PENDING:
            savings = get_total_savings(member)
            total_loan = get_total_loan_outstanding(member)
            estimated_payout = savings['total_overall'] - total_loan
            snapshot = {
                'total_pokok': savings['total_pokok'],
                'total_wajib': savings['total_wajib'],
                'total_sukarela': savings['total_sukarela'],
                'total_savings': savings['total_overall'],
                'total_loan_outstanding': total_loan,
                'estimated_payout': estimated_payout,
            }
        else:
            snapshot = {
                'total_pokok': resignation.total_pokok_snapshot,
                'total_wajib': resignation.total_wajib_snapshot,
                'total_sukarela': resignation.total_sukarela_snapshot,
                'total_savings': resignation.total_savings_snapshot,
                'total_loan_outstanding': resignation.total_loan_outstanding_snapshot,
                'estimated_payout': resignation.estimated_payout,
            }

        loan_history = [
            {
                'id': loan.id,
                'loan_id': loan.loan_id,
                'amount': loan.amount,
                'status': loan.status,
                'status_display': loan.get_status_display(),
                'application_date': loan.application_date,
                'outstanding_balance': loan.outstanding_balance,
            }
            for loan in member.loans.all().order_by('-application_date')[:20]
        ]

        return Response({
            'id': resignation.id,
            'member_name': member.full_name,
            'member_id': member.member_id,
            'request_date': resignation.submitted_at,
            'status': resignation.status,
            'status_display': resignation.get_status_display(),
            'rejection_reason': resignation.rejection_reason,
            'reviewed_at': resignation.reviewed_at,
            'snapshot': snapshot,
            'loan_history': loan_history,
        })


class ManagerResignationStatusUpdateView(APIView):
    """
    POST /api/manager/resignations/{id}/status/

    Body:
      {"action": "approve"}
      {"action": "reject", "reason": "..."}
    """
    permission_classes = [IsManagerOrAbove]

    def post(self, request, pk):
        try:
            resignation = ResignationRequest.objects.select_related('member', 'member__user').get(pk=pk)
        except ResignationRequest.DoesNotExist:
            return Response(
                {'error': 'Pengajuan penutupan akun tidak ditemukan.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if resignation.status != ResignationStatus.PENDING:
            return Response(
                {
                    'error': (
                        f'Hanya pengajuan PENDING yang dapat diproses. '
                        f'Status saat ini: {resignation.status}.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        action = str(request.data.get('action', '')).strip().lower()
        reason = str(request.data.get('reason', '')).strip()

        if action not in ['approve', 'reject']:
            return Response(
                {'error': 'Action tidak valid. Gunakan approve atau reject.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action == 'reject' and not reason:
            return Response(
                {'reason': 'Alasan penolakan wajib diisi.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            resignation.reviewed_by = request.user
            resignation.reviewed_at = timezone.now()

            if action == 'approve':
                settlement = calculate_settlement(resignation.member)
                resignation.total_pokok_snapshot = settlement['total_pokok']
                resignation.total_wajib_snapshot = settlement['total_wajib']
                resignation.total_sukarela_snapshot = settlement['total_sukarela']
                resignation.total_savings_snapshot = settlement['total_savings']
                resignation.total_loan_outstanding_snapshot = settlement['total_loan_outstanding']
                resignation.estimated_payout = settlement['estimated_payout']
                resignation.status = ResignationStatus.APPROVED
                resignation.rejection_reason = ''
            else:
                resignation.status = ResignationStatus.REJECTED
                resignation.rejection_reason = reason

            resignation.save()

        try:
            if action == 'approve':
                from notifications.service import notify_resignation_approved
                notify_resignation_approved(resignation)
            else:
                from notifications.service import notify_resignation_rejected
                notify_resignation_rejected(resignation, reason)
        except Exception:
            pass

        return Response({
            'message': (
                'Pengajuan penutupan akun berhasil disetujui.'
                if action == 'approve' else
                'Pengajuan penutupan akun berhasil ditolak.'
            ),
            'status': resignation.status,
            'estimated_payout': resignation.estimated_payout,
        })


class ManagerResignationExportView(APIView):
    """GET /api/manager/resignations/export/ - export CSV semua data resignation."""
    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        status_filter = request.query_params.get('status', '').strip().upper()
        qs = ResignationRequest.objects.select_related('member').order_by('-submitted_at')
        if status_filter:
            qs = qs.filter(status=status_filter)

        response = HttpResponse(content_type='text/csv')
        filename = f'resignations_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Member ID', 'Member Name', 'Request Date', 'Status',
            'Total Savings', 'Total Loan Outstanding', 'Estimated Payout',
            'Rejection Reason', 'Reviewed At',
        ])
        for r in qs:
            writer.writerow([
                r.id,
                r.member.member_id or '',
                r.member.full_name,
                r.submitted_at.isoformat() if r.submitted_at else '',
                r.status,
                str(r.total_savings_snapshot),
                str(r.total_loan_outstanding_snapshot),
                str(r.estimated_payout),
                r.rejection_reason,
                r.reviewed_at.isoformat() if r.reviewed_at else '',
            ])
        return response
