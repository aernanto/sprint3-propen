from django.utils import timezone
from datetime import date, timedelta
from django.db.models import Sum, Q
from django.db.models import Count
from django.db.models.functions import TruncMonth

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework import status

from members.permissions import IsManagerOrAbove
from .models import Loan, LoanStatus, Installment, InstallmentStatus
from .serializers import (
    ManagerPendingLoanSerializer,
    ManagerLoanHistorySerializer,
    ManagerAllLoanSerializer,
    ManagerLoanDetailSerializer,
    ManagerMemberLoanHistoryItemSerializer,
)


def _manager_remaining_balance(loan):
    """Sisa pinjaman manager: pokok + bunga yang belum dibayar."""
    total_remaining = (
        loan.installments
        .filter(status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING])
        .aggregate(total=Sum('amount'))['total']
    )
    if total_remaining is not None:
        return total_remaining
    return loan.outstanding_balance


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


class AllLoansPagination(StandardPagination):
    page_query_param = 'all_page'
    page_size_query_param = 'all_page_size'


class ManagerPendingLoansView(APIView):
    """
    GET /api/manager/loans/pending/

    Mengembalikan:
    - ringkasan total pinjaman pending dan total requested amount
    - daftar pinjaman pending (search, sort, pagination)
    - history pinjaman yang pernah APPROVED/REJECTED
    """
    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        search = request.query_params.get('search', '').strip()
        sort = request.query_params.get('sort', '-application_date').strip() or '-application_date'
        history_limit = request.query_params.get('history_limit', '20').strip()
        history_search = request.query_params.get('history_search', '').strip()
        history_status = request.query_params.get('history_status', '').strip().upper()
        all_search = request.query_params.get('all_search', '').strip()
        all_status = request.query_params.get('all_status', '').strip().upper()

        allowed_sorts = {'application_date', '-application_date'}
        if sort not in allowed_sorts:
            sort = '-application_date'

        pending_queryset = (
            Loan.objects
            .filter(status=LoanStatus.PENDING)
            .select_related('member')
            .order_by(sort, '-id')
        )

        if search:
            pending_queryset = pending_queryset.filter(
                Q(member__full_name__icontains=search)
            )

        pending_summary_qs = Loan.objects.filter(status=LoanStatus.PENDING)
        total_pending = pending_summary_qs.count()
        total_requested_amount = pending_summary_qs.aggregate(total=Sum('amount'))['total'] or 0
        total_approved = Loan.objects.filter(status=LoanStatus.APPROVED).count()
        total_overdue = Loan.objects.filter(status=LoanStatus.OVERDUE).count()
        total_unverified_installments = Installment.objects.filter(status=InstallmentStatus.PENDING).count()

        paginator = StandardPagination()
        pending_page = paginator.paginate_queryset(pending_queryset, request)
        pending_serializer = ManagerPendingLoanSerializer(pending_page, many=True)
        pending_payload = paginator.get_paginated_data(pending_serializer.data)

        try:
            parsed_history_limit = max(1, min(int(history_limit), 100))
        except ValueError:
            parsed_history_limit = 20

        history_queryset = (
            Loan.objects
            .filter(status__in=[LoanStatus.APPROVED, LoanStatus.REJECTED])
            .select_related('member', 'reviewed_by')
        )

        if history_status in [LoanStatus.APPROVED, LoanStatus.REJECTED]:
            history_queryset = history_queryset.filter(status=history_status)

        if history_search:
            history_queryset = history_queryset.filter(
                Q(member__full_name__icontains=history_search)
                | Q(loan_id__icontains=history_search)
            )

        history_queryset = history_queryset.order_by('-reviewed_at', '-application_date', '-id')[:parsed_history_limit]
        history_serializer = ManagerLoanHistorySerializer(history_queryset, many=True)

        # Tabel all loans (server-side search/filter/pagination)
        all_loans_queryset = (
            Loan.objects
            .exclude(status=LoanStatus.PENDING)
            .select_related('member')
            .order_by('-application_date', '-id')
        )

        if all_search:
            all_loans_queryset = all_loans_queryset.filter(
                Q(member__full_name__icontains=all_search)
                | Q(loan_id__icontains=all_search)
            )

        valid_statuses = {choice[0] for choice in LoanStatus.choices}
        if all_status in valid_statuses and all_status != LoanStatus.PENDING:
            all_loans_queryset = all_loans_queryset.filter(status=all_status)

        all_paginator = AllLoansPagination()
        all_page = all_paginator.paginate_queryset(all_loans_queryset, request)
        all_serializer = ManagerAllLoanSerializer(all_page, many=True)
        all_payload = all_paginator.get_paginated_data(all_serializer.data)

        # Loan activity barchart (6 bulan terakhir)
        today = timezone.now().date()
        month_starts = []
        for offset in range(5, -1, -1):
            y = today.year
            m = today.month - offset
            while m <= 0:
                m += 12
                y -= 1
            month_starts.append(date(y, m, 1))

        activity_qs = (
            Loan.objects
            .filter(application_date__date__gte=month_starts[0])
            .annotate(month=TruncMonth('application_date'))
            .values('month')
            .annotate(total=Count('id'))
            .order_by('month')
        )
        activity_map = {
            item['month'].date().replace(day=1): item['total']
            for item in activity_qs
            if item.get('month')
        }
        loan_activity_barchart = [
            {
                'month': ms.strftime('%b').upper(),
                'total': activity_map.get(ms, 0),
            }
            for ms in month_starts
        ]

        # Loan mendekati due date (2 minggu ke depan)
        near_due_limit_raw = request.query_params.get('near_due_limit', '20').strip()
        try:
            near_due_limit = max(1, min(int(near_due_limit_raw), 100))
        except ValueError:
            near_due_limit = 20

        due_until = today + timedelta(days=14)
        near_due_installments = (
            Installment.objects
            .filter(
                status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING],
                due_date__gte=today,
                due_date__lte=due_until,
                loan__status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE],
            )
            .select_related('loan', 'loan__member')
            .order_by('due_date', 'loan__id')
        )

        near_due_loans = []
        seen_loan_ids = set()
        for inst in near_due_installments:
            loan = inst.loan
            if loan.id in seen_loan_ids:
                continue
            seen_loan_ids.add(loan.id)

            near_due_loans.append({
                'id': loan.id,
                'member_name': loan.member.full_name,
                'loan_id': loan.loan_id,
                'remaining_balance': _manager_remaining_balance(loan),
                'due_date': inst.due_date,
                'status': loan.status,
                'status_display': loan.get_status_display(),
                'detail_url': f'/dashboard/manager/loans/{loan.id}',
            })

            if len(near_due_loans) >= near_due_limit:
                break

        return Response({
            'summary': {
                'total_pending': total_pending,
                'total_requested_amount': total_requested_amount,
                'total_approved': total_approved,
                'total_unverified_installments': total_unverified_installments,
                'total_overdue': total_overdue,
            },
            'pending_loans': pending_payload,
            'history_loans': history_serializer.data,
            'all_loans': all_payload,
            'loan_activity_barchart': loan_activity_barchart,
            'near_due_loans': near_due_loans,
        })


class ManagerLoanDetailView(APIView):
    """
    GET /api/manager/loans/{id}/

    Mengembalikan detail pengajuan pinjaman untuk review manager,
    termasuk financial health member, dokumen pendukung, dan riwayat pinjaman.
    """
    permission_classes = [IsManagerOrAbove]

    def get(self, request, pk):
        try:
            loan = Loan.objects.select_related('member', 'member__savings_balance').get(pk=pk)
        except Loan.DoesNotExist:
            return Response({'error': 'Pinjaman tidak ditemukan'}, status=404)

        detail_serializer = ManagerLoanDetailSerializer(loan, context={'request': request})

        previous_loans_qs = (
            loan.member.loans
            .exclude(pk=loan.pk)
            .exclude(status=LoanStatus.PENDING)
            .order_by('-application_date', '-id')[:10]
        )
        previous_loans_serializer = ManagerMemberLoanHistoryItemSerializer(previous_loans_qs, many=True)

        credit_score = detail_serializer.data['credit_score']['score']
        savings_total = detail_serializer.data['total_savings']
        active_loans_count = detail_serializer.data['active_loans_count']
        bad_debt_history_count = detail_serializer.data['bad_debt_history_count']

        # Skor kelayakan sederhana untuk scorecard manager (0-100)
        eligibility_score = 50
        if credit_score >= 750:
            eligibility_score += 25
        elif credit_score >= 650:
            eligibility_score += 15
        elif credit_score >= 500:
            eligibility_score += 5

        try:
            savings_total_num = float(savings_total)
        except (TypeError, ValueError):
            savings_total_num = 0.0

        if savings_total_num >= 5_000_000:
            eligibility_score += 15
        elif savings_total_num >= 1_000_000:
            eligibility_score += 8

        if active_loans_count == 0:
            eligibility_score += 10
        elif active_loans_count >= 3:
            eligibility_score -= 5

        if bad_debt_history_count > 0:
            eligibility_score -= min(20, bad_debt_history_count * 10)

        eligibility_score = max(0, min(100, eligibility_score))

        monthly_income_proxy_ok = savings_total_num >= float(loan.amount) * 0.1
        collateral_ratio = 140 if loan.collateral_image else 0
        has_bad_debt = bad_debt_history_count > 0

        risk_assessment = [
            {
                'label': 'Indikasi kapasitas bayar memadai berdasarkan total simpanan member.',
                'passed': monthly_income_proxy_ok,
            },
            {
                'label': f'Bukti jaminan tersedia dengan estimasi coverage {collateral_ratio}% dari nilai pinjaman.',
                'passed': bool(loan.collateral_image),
            },
            {
                'label': (
                    'Tidak ditemukan riwayat kredit macet aktif.'
                    if not has_bad_debt
                    else f'Ditemukan riwayat kredit macet sebanyak {bad_debt_history_count} kasus.'
                ),
                'passed': not has_bad_debt,
            },
        ]

        monitoring = None
        if loan.status in [LoanStatus.ACTIVE, LoanStatus.OVERDUE, LoanStatus.LUNAS, LoanStatus.LUNAS_AFTER_OVERDUE]:
            installments_qs = loan.installments.all().order_by('installment_number')
            total_installments = installments_qs.count()
            paid_installments = installments_qs.filter(status=InstallmentStatus.PAID).count()

            if total_installments > 0:
                payment_progress_percent = round((paid_installments / total_installments) * 100, 1)
            else:
                payment_progress_percent = 0

            monitoring_installments = []
            for inst in installments_qs:
                transfer_proof_url = None
                if inst.transfer_proof:
                    transfer_url = inst.transfer_proof.url
                    transfer_proof_url = request.build_absolute_uri(transfer_url)

                monitoring_installments.append({
                    'id': inst.id,
                    'installment_number': inst.installment_number,
                    'due_date': inst.due_date,
                    'amount': inst.amount,
                    'status': inst.status,
                    'status_display': inst.get_status_display(),
                    'submitted_at': inst.submitted_at,
                    'paid_at': inst.paid_at,
                    'transaction_id': inst.transaction_id,
                    'transfer_proof_url': transfer_proof_url,
                })

            monitoring = {
                'payment_progress_percent': payment_progress_percent,
                'paid_installments': paid_installments,
                'total_installments': total_installments,
                'outstanding_balance': _manager_remaining_balance(loan),
                'next_due_date': loan.next_due_date,
                'installments': monitoring_installments,
            }

        return Response({
            'loan': detail_serializer.data,
            'member_previous_loans': previous_loans_serializer.data,
            'scorecard': {
                'eligibility_score': eligibility_score,
                'indicators': [
                    {
                        'label': 'Credit score member',
                        'value': detail_serializer.data['credit_score']['score'],
                    },
                    {
                        'label': 'Total simpanan member',
                        'value': detail_serializer.data['total_savings'],
                    },
                    {
                        'label': 'Pinjaman aktif member',
                        'value': detail_serializer.data['active_loans_count'],
                    },
                    {
                        'label': 'Riwayat kredit macet',
                        'value': detail_serializer.data['bad_debt_history_count'],
                    },
                ],
            },
            'risk_assessment': risk_assessment,
            'monitoring': monitoring,
        })

    def post(self, request, pk):
        """
        POST /api/manager/loans/{id}/

        Body:
          {"action": "approve"}
          {"action": "reject", "reason": "..."}
        """
        try:
            loan = Loan.objects.select_related('member', 'member__user').get(pk=pk)
        except Loan.DoesNotExist:
            return Response({'error': 'Pinjaman tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

        if loan.status != LoanStatus.PENDING:
            return Response(
                {'error': f'Hanya pinjaman status PENDING yang dapat direview. Status saat ini: {loan.status}.'},
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

        loan.reviewed_by = request.user
        loan.reviewed_at = timezone.now()

        if action == 'approve':
            loan.status = LoanStatus.APPROVED
            loan.rejection_reason = ''
        else:
            loan.status = LoanStatus.REJECTED
            loan.rejection_reason = reason

        loan.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'rejection_reason', 'updated_at'])

        try:
            from notifications.service import notify_loan_approved, notify_loan_rejected
            if action == 'approve':
                notify_loan_approved(loan)
            else:
                notify_loan_rejected(loan, reason)
        except Exception:
            pass

        return Response({
            'message': 'Pinjaman berhasil di-approve.' if action == 'approve' else 'Pinjaman berhasil di-reject.',
            'loan_id': loan.loan_id,
            'status': loan.status,
        })


class ManagerLoanStatusUpdateView(APIView):
    """
    POST /api/manager/loans/{id}/status/

    Body:
      {"action": "approve"}
      {"action": "reject", "reason": "..."}
    """
    permission_classes = [IsManagerOrAbove]

    def post(self, request, pk):
        try:
            loan = Loan.objects.select_related('member', 'member__user').get(pk=pk)
        except Loan.DoesNotExist:
            return Response({'error': 'Pinjaman tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

        if loan.status != LoanStatus.PENDING:
            return Response(
                {'error': f'Hanya pinjaman status PENDING yang dapat direview. Status saat ini: {loan.status}.'},
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

        loan.reviewed_by = request.user
        loan.reviewed_at = timezone.now()

        if action == 'approve':
            loan.status = LoanStatus.APPROVED
            loan.rejection_reason = ''
        else:
            loan.status = LoanStatus.REJECTED
            loan.rejection_reason = reason

        loan.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'rejection_reason', 'updated_at'])

        try:
            from notifications.service import notify_loan_approved, notify_loan_rejected
            if action == 'approve':
                notify_loan_approved(loan)
            else:
                notify_loan_rejected(loan, reason)
        except Exception:
            pass

        return Response({
            'message': 'Pinjaman berhasil di-approve.' if action == 'approve' else 'Pinjaman berhasil di-reject.',
            'loan_id': loan.loan_id,
            'status': loan.status,
        })

class ManagerDashboardView(APIView):
    """
    GET /api/manager/loans/dashboard/

    Dashboard executive overview untuk manager, mengembalikan:
    - Total liquidity (total simpanan semua member)
    - Total outstanding loans (total pinjaman aktif)
    - Estimated SHU (estimasi hasil usaha)
    - Pending loan approvals count
    - Portfolio performance trend data (6 bulan dan 1 tahun)
    - Recent credit activities
    """
    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        # Use shared finance utilities to compute snapshot metrics
        try:
            from .utils import get_snapshot_financials
            snapshot = get_snapshot_financials()
        except Exception:
            snapshot = {}

        Notification = None
        try:
            from notifications.models import Notification
        except (ImportError, Exception):
            pass

        ResignationRequest = None
        ResignationStatus = None
        try:
            from resignations.models import ResignationRequest, ResignationStatus
        except (ImportError, Exception):
            pass

        response_data = {
            'total_liquidity': snapshot.get('total_liquidity', 0),
            'total_outstanding_loans': snapshot.get('total_outstanding_loans', 0),
            'interest_income_total': snapshot.get('interest_income_total', 0),
            'estimated_shu': snapshot.get('estimated_shu', 0),
            'npl_count': snapshot.get('npl_count', 0),
            'npl_amount': snapshot.get('npl_amount', 0),
            'pending_loans_count': 0,
            'portfolio_trend_6m': [],
            'portfolio_trend_1y': [],
            'recent_activities': [],
        }

        # 4. Pending loan approvals (count + preview list)
        try:
            pending_qs = (
                Loan.objects
                .filter(status=LoanStatus.PENDING)
                .select_related('member')
                .order_by('application_date')[:10]
            )
            pending_loans_count = Loan.objects.filter(status=LoanStatus.PENDING).count()
            total_approved = Loan.objects.filter(status=LoanStatus.APPROVED).count()
            total_overdue = Loan.objects.filter(status=LoanStatus.OVERDUE).count()
            pending_list = []
            for l in pending_qs:
                pending_list.append({
                    'loan_id': l.loan_id,
                    'member_name': getattr(l.member, 'full_name', None),
                    'amount': float(l.amount or 0),
                    'application_date': l.application_date.isoformat() if l.application_date else None,
                    'status': l.status,
                })

            response_data['pending_loans_count'] = pending_loans_count
            response_data['pending_loans'] = pending_list
            response_data['loan_summary'] = {
                'total_pending': pending_loans_count,
                'total_approved': total_approved,
                'total_overdue': total_overdue,
            }
        except Exception:
            pass

        # 4b. Resignation requests (summary + preview list)
        if ResignationRequest and ResignationStatus:
            try:
                resignation_pending = (
                    ResignationRequest.objects
                    .filter(status__in=[ResignationStatus.PENDING, ResignationStatus.APPROVED])
                    .select_related('member')
                    .order_by('-submitted_at')[:8]
                )
                resignation_summary = {
                    'total_pending': ResignationRequest.objects.filter(status=ResignationStatus.PENDING).count(),
                    'total_approved': ResignationRequest.objects.filter(status=ResignationStatus.APPROVED).count(),
                    'total_inactive': ResignationRequest.objects.filter(status=ResignationStatus.RESIGNED).count(),
                }
                resignation_list = []
                for req in resignation_pending:
                    resignation_list.append({
                        'id': req.id,
                        'member_name': req.member.full_name,
                        'member_id': req.member.member_id,
                        'request_date': req.submitted_at.isoformat() if req.submitted_at else None,
                        'status': req.status,
                        'status_display': req.get_status_display(),
                        'estimated_payout': float(req.estimated_payout or 0),
                    })

                response_data['resignation_summary'] = resignation_summary
                response_data['resignation_requests'] = resignation_list
            except Exception:
                pass

        # 5. Portfolio Performance Trend - 6 months
        try:
            today = timezone.now().date()
            six_months_ago = today - timedelta(days=180)
            
            trend_6m_qs = (
                Loan.objects
                .filter(application_date__gte=six_months_ago)
                .filter(status__in=[LoanStatus.APPROVED, LoanStatus.ACTIVE, LoanStatus.LUNAS])
                .annotate(month=TruncMonth('application_date'))
                .values('month')
                .annotate(count=Count('id'), total=Sum('amount'))
                .order_by('month')
            )
            
            trend_6m_data = []
            month_names = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
            for item in trend_6m_qs:
                if item['month']:
                    month_idx = item['month'].month - 1
                    trend_6m_data.append({
                        'month': month_names[month_idx],
                        'date': item['month'].isoformat(),
                        'value': float(item['total'] or 0) / 1_000_000,
                        'count': item['count']
                    })
            response_data['portfolio_trend_6m'] = trend_6m_data
        except Exception:
            pass

        # 6. Portfolio Performance Trend - 1 year
        try:
            today = timezone.now().date()
            one_year_ago = today - timedelta(days=365)
            
            trend_1y_qs = (
                Loan.objects
                .filter(application_date__gte=one_year_ago)
                .filter(status__in=[LoanStatus.APPROVED, LoanStatus.ACTIVE, LoanStatus.LUNAS])
                .annotate(month=TruncMonth('application_date'))
                .values('month')
                .annotate(count=Count('id'), total=Sum('amount'))
                .order_by('month')
            )
            
            trend_1y_data = []
            month_names = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
            for item in trend_1y_qs:
                if item['month']:
                    month_idx = item['month'].month - 1
                    trend_1y_data.append({
                        'month': month_names[month_idx],
                        'date': item['month'].isoformat(),
                        'value': float(item['total'] or 0) / 1_000_000,
                        'count': item['count']
                    })
            response_data['portfolio_trend_1y'] = trend_1y_data
        except Exception:
            pass

        # 6b. Overdue loan summary (for monitoring)
        try:
            today = timezone.now().date()
            overdue_installments = Installment.objects.filter(
                status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING],
                due_date__lt=today,
                loan__status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE],
            )
            total_overdue = overdue_installments.values('loan_id').distinct().count()
            total_amount_overdue = overdue_installments.aggregate(total=Sum('amount'))['total'] or 0
            critical_cutoff = today - timedelta(days=90)
            total_critical = Loan.objects.filter(
                status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE],
                installments__status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING],
                installments__due_date__lt=critical_cutoff,
            ).distinct().count()

            response_data['overdue_summary'] = {
                'total_overdue': total_overdue,
                'total_amount_overdue': float(total_amount_overdue),
                'total_critical': total_critical,
            }
        except Exception:
            pass

        # 7. Recent credit activities
        if Notification:
            try:
                seven_days_ago = timezone.now() - timedelta(days=7)
                
                recent_notifications = Notification.objects.filter(
                    created_at__gte=seven_days_ago,
                    type__in=['LOAN', 'SAVING', 'WITHDRAWAL']
                ).select_related('recipient').order_by('-created_at')[:10]

                recent_activities = []
                for notif in recent_notifications:
                    icon = '+'
                    if 'Disbursed' in notif.title or 'disbursed' in notif.message:
                        icon = '+'
                    elif 'Payment' in notif.title or 'payment' in notif.message or 'Pembayaran' in notif.title:
                        icon = '-'
                    elif 'Resign' in notif.title or 'resign' in notif.message:
                        icon = 'x'
                    
                    recent_activities.append({
                        'icon': icon,
                        'title': notif.title,
                        'detail': notif.message[:100],
                        'time': notif.created_at.isoformat(),
                        'type': notif.type,
                    })
                response_data['recent_activities'] = recent_activities
            except Exception:
                pass

        # 8. Near-due loans preview (next 14 days)
        try:
            today = timezone.now().date()
            due_until = today + timedelta(days=14)
            near_due_installments = (
                Installment.objects
                .filter(
                    status__in=[InstallmentStatus.UNPAID, InstallmentStatus.PENDING],
                    due_date__gte=today,
                    due_date__lte=due_until,
                    loan__status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE],
                )
                .select_related('loan', 'loan__member')
                .order_by('due_date', 'loan__id')
            )
            near_due_loans = []
            seen_loan_ids = set()
            for inst in near_due_installments:
                loan = inst.loan
                if loan.id in seen_loan_ids:
                    continue
                seen_loan_ids.add(loan.id)
                near_due_loans.append({
                    'id': loan.id,
                    'member_name': loan.member.full_name,
                    'loan_id': loan.loan_id,
                    'remaining_balance': float(_manager_remaining_balance(loan) or 0),
                    'due_date': inst.due_date.isoformat() if inst.due_date else None,
                    'status': loan.status,
                    'status_display': loan.get_status_display(),
                    'detail_url': f'/dashboard/manager/loans/{loan.id}',
                })
                if len(near_due_loans) >= 6:
                    break

            response_data['near_due_loans'] = near_due_loans
        except Exception:
            pass

        return Response(response_data)
