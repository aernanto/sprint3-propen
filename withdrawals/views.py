from decimal import Decimal

from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from savings.models import SavingsBalance

from .models import WithdrawalRequest, WithdrawalStatus
from .serializers import WithdrawalRequestSerializer


class WithdrawalCreateView(APIView):
    """
    POST /api/withdrawals/
    Member mengajukan penarikan simpanan sukarela.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.role != 'MEMBER':
            return Response(
                {'error': 'Hanya anggota yang dapat mengajukan penarikan simpanan.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        member = getattr(user, 'member', None)
        if not member:
            return Response({'error': 'Profil anggota tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        if member.status != 'ACTIVE':
            return Response(
                {'error': 'Hanya anggota dengan status ACTIVE yang dapat mengajukan penarikan.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Block if there's already a pending withdrawal
        if WithdrawalRequest.objects.filter(member=member, status=WithdrawalStatus.PENDING).exists():
            return Response(
                {'error': 'Anda masih memiliki pengajuan penarikan yang sedang diproses. Mohon tunggu hingga selesai.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Block if member has active resignation request
        if member.resignation_requests.filter(
            status__in=['PENDING', 'APPROVED']
        ).exists():
            return Response(
                {'error': 'Tidak dapat mengajukan penarikan saat pengajuan penutupan akun sedang aktif.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount_raw = request.data.get('amount')
        try:
            amount = Decimal(str(amount_raw))
        except Exception:
            return Response({'error': 'Nominal penarikan tidak valid.'}, status=status.HTTP_400_BAD_REQUEST)

        if amount <= Decimal('0'):
            return Response(
                {'error': 'Nominal penarikan harus lebih dari 0.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        balance = SavingsBalance.objects.filter(member=member).first()
        current_sukarela = balance.total_sukarela if balance else Decimal('0')

        if amount > current_sukarela:
            return Response(
                {
                    'error': 'Nominal penarikan melebihi saldo simpanan sukarela.',
                    'saldo_sukarela': str(current_sukarela),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        bank_name = str(request.data.get('bank_name', '')).strip()
        account_number = str(request.data.get('account_number', '')).strip()
        account_holder = str(request.data.get('account_holder', '')).strip()

        if not bank_name or not account_number or not account_holder:
            return Response(
                {'error': 'Nama bank, nomor rekening, dan nama pemilik rekening wajib diisi.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        notes = str(request.data.get('notes', '')).strip()

        with transaction.atomic():
            withdrawal = WithdrawalRequest.objects.create(
                member=member,
                amount=amount,
                bank_name=bank_name,
                account_number=account_number,
                account_holder=account_holder,
                balance_sukarela_snapshot=current_sukarela,
                notes=notes,
                status=WithdrawalStatus.PENDING,
            )

        try:
            from notifications.service import notify_withdrawal_received
            notify_withdrawal_received(withdrawal)
        except Exception:
            pass

        return Response(
            WithdrawalRequestSerializer(withdrawal).data,
            status=status.HTTP_201_CREATED,
        )


class WithdrawalMeView(APIView):
    """
    GET /api/withdrawals/me/
    Member melihat riwayat pengajuan penarikan miliknya.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.role != 'MEMBER':
            return Response(
                {'error': 'Hanya anggota yang dapat mengakses endpoint ini.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        member = getattr(user, 'member', None)
        if not member:
            return Response({'error': 'Profil anggota tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        qs = WithdrawalRequest.objects.filter(member=member).order_by('-requested_at')
        return Response(WithdrawalRequestSerializer(qs, many=True).data)
