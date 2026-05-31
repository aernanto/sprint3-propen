import csv
from datetime import datetime
from decimal import Decimal

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from members.permissions import IsStaffOrAbove
from savings.models import SavingsBalance, SavingsWithdrawal, WithdrawalStatus
from savings.serializers import WithdrawalSerializer


class StaffWithdrawalPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 100


class StaffWithdrawalListView(APIView):
    permission_classes = [IsStaffOrAbove]

    def _extract_date(self, raw_value: str):
        if not raw_value:
            return None
        try:
            return datetime.strptime(raw_value, '%Y-%m-%d').date()
        except ValueError:
            return None

    def _filter_queryset(self, queryset, request):
        search = request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(member__full_name__icontains=search)
                | Q(withdrawal_id__icontains=search)
                | Q(member__member_id__icontains=search)
            )

        bank_name = request.query_params.get('bank_name', '').strip()
        if bank_name:
            queryset = queryset.filter(bank_name__icontains=bank_name)

        account_holder = request.query_params.get('account_holder', '').strip()
        if account_holder:
            queryset = queryset.filter(account_holder__icontains=account_holder)

        start_date = self._extract_date(request.query_params.get('start_date', '').strip())
        if request.query_params.get('start_date') and not start_date:
            raise ValueError('Format start_date tidak valid. Gunakan YYYY-MM-DD.')

        end_date = self._extract_date(request.query_params.get('end_date', '').strip())
        if request.query_params.get('end_date') and not end_date:
            raise ValueError('Format end_date tidak valid. Gunakan YYYY-MM-DD.')

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)

        return queryset

    def _paginate(self, queryset, page, page_size, request):
        paginator = Paginator(queryset, page_size)
        current_page = paginator.get_page(page)
        rows = list(current_page.object_list)
        results = WithdrawalSerializer(rows, many=True, context={'request': request}).data

        for index, row in enumerate(results):
            withdrawal = rows[index]
            row['member_name'] = withdrawal.member.full_name
            row['member_id'] = withdrawal.member.member_id

        return {
            'count': paginator.count,
            'total_pages': paginator.num_pages,
            'current_page': current_page.number,
            'page_size': page_size,
            'next': current_page.next_page_number() if current_page.has_next() else None,
            'previous': current_page.previous_page_number() if current_page.has_previous() else None,
            'results': results,
        }

    def get(self, request):
        base_queryset = SavingsWithdrawal.objects.select_related('member').order_by('-created_at')

        pending_summary_qs = base_queryset.filter(status=WithdrawalStatus.PENDING)
        summary = pending_summary_qs.aggregate(
            total_pending_amount=Coalesce(
                Sum('amount'),
                Value(Decimal('0.00')),
            ),
        )

        pending_queryset = base_queryset.filter(status=WithdrawalStatus.PENDING)
        history_queryset = base_queryset.filter(status=WithdrawalStatus.COMPLETED)

        try:
            pending_queryset = self._filter_queryset(pending_queryset, request)
            history_queryset = self._filter_queryset(history_queryset, request)
        except ValueError as error:
            return Response({'error': str(error)}, status=status.HTTP_400_BAD_REQUEST)

        page_size = int(request.query_params.get('page_size', 5))
        pending_page = int(request.query_params.get('pending_page', 1))
        history_page = int(request.query_params.get('history_page', 1))

        pending_data = self._paginate(pending_queryset, pending_page, page_size, request)
        history_data = self._paginate(history_queryset, history_page, page_size, request)

        return Response(
            {
                'summary': {
                    'total_pending_requests': pending_summary_qs.count(),
                    'total_pending_amount': str(summary['total_pending_amount']),
                },
                'pending_requests': pending_data,
                'completed_history': history_data,
            },
            status=status.HTTP_200_OK,
        )


class StaffWithdrawalExportView(APIView):
    permission_classes = [IsStaffOrAbove]

    def get(self, request):
        scope = request.query_params.get('scope', 'pending').strip().lower()
        valid_scopes = {'pending', 'history', 'all'}
        if scope not in valid_scopes:
            return Response(
                {'error': f'Scope tidak valid. Gunakan salah satu dari: {", ".join(sorted(valid_scopes))}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        queryset = SavingsWithdrawal.objects.select_related('member').order_by('-created_at')
        if scope == 'pending':
            queryset = queryset.filter(status=WithdrawalStatus.PENDING)
        elif scope == 'history':
            queryset = queryset.filter(status=WithdrawalStatus.COMPLETED)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="withdrawals-{scope}-{timezone.now().date()}.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'withdrawal_id',
            'member_name',
            'member_id',
            'amount',
            'bank_name',
            'account_number',
            'account_holder',
            'status',
            'created_at',
            'processed_at',
        ])

        for withdrawal in queryset:
            writer.writerow([
                withdrawal.withdrawal_id,
                withdrawal.member.full_name,
                withdrawal.member.member_id or '',
                str(withdrawal.amount),
                withdrawal.bank_name,
                withdrawal.account_number,
                withdrawal.account_holder,
                withdrawal.status,
                withdrawal.created_at.isoformat(),
                withdrawal.processed_at.isoformat() if withdrawal.processed_at else '',
            ])

        return response


class StaffWithdrawalStatusUpdateView(APIView):
    permission_classes = [IsStaffOrAbove]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        try:
            withdrawal = SavingsWithdrawal.objects.select_related('member').get(pk=pk)
        except SavingsWithdrawal.DoesNotExist:
            return Response({'error': 'Data penarikan tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        if withdrawal.status != WithdrawalStatus.PENDING:
            return Response(
                {
                    'error': (
                        'Hanya penarikan dengan status PENDING yang dapat dicairkan. '
                        f'Status saat ini: {withdrawal.status}.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        transfer_proof = request.FILES.get('transfer_proof')
        if not transfer_proof:
            return Response({'error': 'Bukti transfer wajib diunggah.'}, status=status.HTTP_400_BAD_REQUEST)

        max_size = 5 * 1024 * 1024
        if transfer_proof.size > max_size:
            return Response({'error': 'Ukuran file maksimal 5MB.'}, status=status.HTTP_400_BAD_REQUEST)

        allowed_types = {'image/jpeg', 'image/png', 'application/pdf'}
        if hasattr(transfer_proof, 'content_type') and transfer_proof.content_type not in allowed_types:
            return Response({'error': 'Format file harus JPG, PNG, atau PDF.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            balance, _ = SavingsBalance.objects.select_for_update().get_or_create(member=withdrawal.member)
            available_balance = balance.total_sukarela or Decimal('0')

            if withdrawal.amount > available_balance:
                return Response(
                    {
                        'error': (
                            'Saldo simpanan sukarela anggota tidak mencukupi untuk pencairan ini. '
                            f'Saldo tersedia: Rp {available_balance:,.0f}'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            balance.total_sukarela = available_balance - withdrawal.amount
            balance.save(update_fields=['total_sukarela', 'last_updated'])

            withdrawal.status = WithdrawalStatus.COMPLETED
            withdrawal.transfer_proof = transfer_proof
            withdrawal.processed_by = request.user
            withdrawal.processed_at = timezone.now()
            withdrawal.save(update_fields=['status', 'transfer_proof', 'processed_by', 'processed_at', 'updated_at'])

        try:
            from notifications.service import notify_withdrawal_processed
            notify_withdrawal_processed(withdrawal)
        except Exception:
            pass

        return Response(
            {
                'message': 'Pencairan penarikan berhasil dikonfirmasi.',
                'withdrawal': WithdrawalSerializer(withdrawal, context={'request': request}).data,
                'updated_sukarela_balance': str(balance.total_sukarela),
                'cash_out_recorded': True,
            },
            status=status.HTTP_200_OK,
        )
