from datetime import datetime
from decimal import Decimal

from django.db.models import Sum
from django.utils.timezone import make_aware
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from loans.models import Installment, InstallmentStatus, Loan, LoanStatus
from members.models import Member
from refunds.models import Refund, RefundStatus
from resignations.models import ResignationRequest, ResignationStatus
from savings.models import SavingStatus, SavingTransaction, SavingsBalance, SavingsWithdrawal, WithdrawalStatus


class StaffDashboardView(APIView):
    """
    GET /api/dashboards/staff/

    Mengembalikan ringkasan metrik untuk dashboard petugas (staff).
    Hanya dapat diakses oleh user dengan role STAFF.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # ── 1. Anggota menunggu verifikasi ────────────────────────────────
        total_pending_members = Member.objects.filter(status="PENDING").count()

        # ── 2. Simpanan menunggu verifikasi ───────────────────────────────
        pending_savings_qs = SavingTransaction.objects.filter(
            status=SavingStatus.PENDING
        )
        total_pending_savings_count = pending_savings_qs.count()
        total_pending_savings_amount = (
            pending_savings_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        )

        # ── 3. Pinjaman disetujui (menunggu pencairan) ────────────────────
        approved_loans_qs = Loan.objects.filter(status=LoanStatus.APPROVED)
        total_approved_loans_count = approved_loans_qs.count()
        total_approved_loans_amount = (
            approved_loans_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        )

        # ── 4. Angsuran menunggu verifikasi pembayaran ────────────────────
        pending_installments_qs = Installment.objects.filter(
            status=InstallmentStatus.PENDING
        )
        total_pending_installments_count = pending_installments_qs.count()
        total_pending_installments_amount = (
            pending_installments_qs.aggregate(total=Sum("amount"))["total"]
            or Decimal("0")
        )

        # ── 5. Penarikan simpanan sukarela selesai ────────────────────────
        total_completed_withdrawals = SavingsWithdrawal.objects.filter(
            status=WithdrawalStatus.COMPLETED
        ).count()

        # ── 5b. Penarikan simpanan sukarela menunggu proses ───────────────
        total_pending_withdrawals = SavingsWithdrawal.objects.filter(
            status=WithdrawalStatus.PENDING
        ).count()

        # ── 6. Pengembalian dana menunggu pencairan ───────────────────────
        total_approved_refunds = Refund.objects.filter(
            status=RefundStatus.PENDING
        ).count()

        # ── 7. Pengajuan resign disetujui manajer ─────────────────────────
        total_approved_resignations = ResignationRequest.objects.filter(
            status=ResignationStatus.APPROVED
        ).count()

        # ── Tugas terbaru (maks 2 per kategori) ──────────────────────────
        recent_tasks = []

        for m in Member.objects.filter(status="PENDING").order_by('-pk'):
            recent_tasks.append({
                'task_id': f'MBR-{m.pk:04d}',
                'category': 'ANGGOTA',
                'subject': f'Pendaftaran: {m.full_name}',
                'status': 'Menunggu',
                'action': 'Verifikasi',
                'link': f'/dashboard/staff/verification/{m.pk}/verify',
            })

        for s in SavingTransaction.objects.filter(
            status=SavingStatus.PENDING
        ).select_related('member').order_by('-submitted_at'):
            recent_tasks.append({
                'task_id': s.saving_id,
                'category': 'SIMPANAN',
                'subject': f'Setoran {s.get_saving_type_display()}: {s.member.full_name}',
                'status': 'Menunggu',
                'action': 'Periksa',
                'link': f'/dashboard/staff/verifications/savings/{s.pk}',
            })

        for ln in Loan.objects.filter(
            status=LoanStatus.APPROVED
        ).select_related('member').order_by('-pk'):
            recent_tasks.append({
                'task_id': ln.loan_id,
                'category': 'PINJAMAN',
                'subject': f'Pencairan: {ln.member.full_name}',
                'status': 'Disetujui',
                'action': 'Cairkan',
                'link': f'/dashboard/staff/disbursement/{ln.loan_id}',
            })

        for ins in Installment.objects.filter(
            status=InstallmentStatus.PENDING
        ).select_related('loan__member').order_by('-updated_at'):
            recent_tasks.append({
                'task_id': ins.transaction_id or f'INS-{ins.pk:05d}',
                'category': 'ANGSURAN',
                'subject': f'Cicilan #{ins.installment_number}: {ins.loan.member.full_name}',
                'status': 'Menunggu',
                'action': 'Verifikasi',
                'link': f'/dashboard/staff/installments/{ins.pk}',
            })

        for wd in SavingsWithdrawal.objects.filter(
            status=WithdrawalStatus.PENDING
        ).select_related('member').order_by('-created_at'):
            recent_tasks.append({
                'task_id': wd.withdrawal_id,
                'category': 'PENARIKAN',
                'subject': f'Penarikan Sukarela: {wd.member.full_name}',
                'status': 'Menunggu',
                'action': 'Proses',
                'link': '/dashboard/staff/withdrawals',
            })

        for ref in Refund.objects.filter(
            status=RefundStatus.PENDING
        ).select_related('member').order_by('-created_at'):
            recent_tasks.append({
                'task_id': f'REF-{ref.pk:04d}',
                'category': 'PENGEMBALIAN',
                'subject': f'Pengembalian Dana: {ref.member.full_name}',
                'status': 'Menunggu Pencairan',
                'action': 'Cairkan',
                'link': '/dashboard/staff/refunds',
            })

        for res in ResignationRequest.objects.filter(
            status=ResignationStatus.APPROVED
        ).select_related('member').order_by('-pk'):
            recent_tasks.append({
                'task_id': f'RES-{res.pk:04d}',
                'category': 'PENUTUPAN',
                'subject': f'Penutupan Akun: {res.member.full_name}',
                'status': 'Disetujui',
                'action': 'Proses',
                'link': '/dashboard/staff/refunds',
            })

        return Response(
            {
                "total_pending_members": total_pending_members,
                "total_pending_savings_count": total_pending_savings_count,
                "total_pending_savings_amount": str(total_pending_savings_amount),
                "total_approved_loans_count": total_approved_loans_count,
                "total_approved_loans_amount": str(total_approved_loans_amount),
                "total_pending_installments_count": total_pending_installments_count,
                "total_pending_installments_amount": str(
                    total_pending_installments_amount
                ),
                "total_completed_withdrawals": total_completed_withdrawals,
                "total_pending_withdrawals": total_pending_withdrawals,
                "total_approved_refunds": total_approved_refunds,
                "total_approved_resignations": total_approved_resignations,
                "recent_tasks": recent_tasks,
            }
        )


class ChairmanDashboardView(APIView):
    """GET /api/dashboards/chairman/"""

    permission_classes = [IsAuthenticated]

    BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun',
             'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']

    def get(self, request):
        from django.utils import timezone

        # ── 1. Total kas (semua saldo simpanan anggota) ───────────────────
        cash_agg = SavingsBalance.objects.aggregate(
            pokok=Sum('total_pokok'),
            wajib=Sum('total_wajib'),
            sukarela=Sum('total_sukarela'),
        )
        total_cash = (
            (cash_agg['pokok']    or Decimal('0')) +
            (cash_agg['wajib']    or Decimal('0')) +
            (cash_agg['sukarela'] or Decimal('0'))
        )

        # ── 2. Total pinjaman aktif (outstanding) ─────────────────────────
        total_loans = (
            Loan.objects.filter(status=LoanStatus.ACTIVE)
            .aggregate(total=Sum('amount'))['total'] or Decimal('0')
        )

        # ── 3. Anggota aktif ──────────────────────────────────────────────
        total_active_members = Member.objects.filter(status='ACTIVE').count()

        # ── 4. Rasio likuiditas: kas / pinjaman × 100 ─────────────────────
        if total_loans > 0:
            liquidity_ratio = round(float(total_cash / total_loans * 100), 1)
        else:
            liquidity_ratio = 0.0

        # ── 5. Tren keanggotaan 12 bulan terakhir ─────────────────────────
        now = timezone.now()
        trends = []
        for i in range(11, -1, -1):
            year, month = now.year, now.month - i
            while month <= 0:
                month += 12
                year -= 1
            month_start = make_aware(datetime(year, month, 1))
            if month == 12:
                month_end = make_aware(datetime(year + 1, 1, 1))
            else:
                month_end = make_aware(datetime(year, month + 1, 1))

            new_count = Member.objects.filter(
                registration_date__gte=month_start,
                registration_date__lt=month_end,
            ).count()
            resigned_count = ResignationRequest.objects.filter(
                status=ResignationStatus.RESIGNED,
                resolved_at__gte=month_start,
                resolved_at__lt=month_end,
            ).count()
            trends.append({
                'month': self.BULAN[month - 1],
                'new_members': new_count,
                'resigned_members': resigned_count,
            })

        return Response({
            'total_cash': str(total_cash),
            'total_loans': str(total_loans),
            'total_active_members': total_active_members,
            'liquidity_ratio': liquidity_ratio,
            'liquidity_components': {
                'cash_in_bank': str(total_cash),
                'loans_disbursed': str(total_loans),
            },
            'membership_trends': trends,
        })
