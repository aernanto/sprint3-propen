from enum import member
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from .serializers import MemberRegisterSerializer, MemberProfileSerializer, BankAccountSerializer
from .models import Member, BankAccount
from users.models import User
from decimal import Decimal
from django.db.models import Sum

from savings.models import SavingTransaction, SavingsBalance, SavingStatus
from loans.models import Loan, Installment, LoanStatus, InstallmentStatus


class MemberRegisterView(APIView):
    permission_classes = [permissions.AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = MemberRegisterSerializer(data=request.data)
        if serializer.is_valid():
            member = serializer.save()

            # Trigger notifikasi registrasi pending
            try:
                from notifications.service import notify_registration_pending
                notify_registration_pending(member)
            except Exception:
                pass

            return Response(
                {'message': 'Registrasi berhasil. Data sedang menunggu verifikasi.'},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MemberStatusView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        email = request.query_params.get('email', '').strip()
        if not email:
            return Response({'error': 'Email wajib diisi'}, status=400)
        try:
            user = User.objects.select_related('member').get(email__iexact=email)
            if hasattr(user, 'member'):
                return Response({'email': user.email, 'status': user.member.status})
            account_status = 'ACTIVE' if user.is_active else 'INACTIVE'
            return Response({'email': user.email, 'status': account_status, 'role': user.role})
        except User.DoesNotExist:
            return Response({'error': 'Email tidak ditemukan'}, status=404)


class MemberProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        user = request.user
        # Non-MEMBER roles (STAFF, MANAGER, CHAIRMAN) don't have a linked Member object.
        # Return their basic user info so dashboard pages don't 404.
        if not hasattr(user, 'member') or user.role != 'MEMBER':
            return Response({
                'id': user.id,
                'email': user.email,
                'role': user.role,
                'full_name': getattr(user, 'full_name', user.email.split('@')[0]),
                'member_id': None,
                'is_member': False,
            })
        try:
            member = user.member
            serializer = MemberProfileSerializer(member, context={'request': request})
            return Response({**serializer.data, 'is_member': True})
        except Member.DoesNotExist:
            return Response({
                'id': user.id,
                'email': user.email,
                'role': user.role,
                'full_name': getattr(user, 'full_name', user.email.split('@')[0]),
                'member_id': None,
                'is_member': False,
            })

    def patch(self, request):
        """Update informasi profil (telepon, alamat, atau foto)"""
        try:
            member = request.user.member
        except Member.DoesNotExist:
            return Response({'error': 'Profil tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

        mutable_data = request.data.copy()
        mutable_data.pop('profile_picture', None)
        mutable_data.pop('selfie_image', None)

        serializer = MemberProfileSerializer(member, data=mutable_data, partial=True, context={'request': request})

        if serializer.is_valid():
            uploaded_picture = request.FILES.get('profile_picture') or request.FILES.get('selfie_image')
            if uploaded_picture:
                member.selfie_image = uploaded_picture
                member.save(update_fields=['selfie_image'])

            serializer.save()
            member.refresh_from_db()
            response_serializer = MemberProfileSerializer(member, context={'request': request})
            return Response(response_serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MemberBankAccountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            member = request.user.member
        except Member.DoesNotExist:
            return Response({'error': 'Profil tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

        accounts = BankAccount.objects.filter(member=member).order_by('-is_primary', 'created_at')
        return Response(BankAccountSerializer(accounts, many=True).data)

    def post(self, request):
        try:
            member = request.user.member
        except Member.DoesNotExist:
            return Response({'error': 'Profil tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

        serializer = BankAccountSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        is_primary = serializer.validated_data.get('is_primary', False)
        if is_primary:
            BankAccount.objects.filter(member=member, is_primary=True).update(is_primary=False)
        elif not BankAccount.objects.filter(member=member).exists():
            is_primary = True

        bank_account = serializer.save(member=member, is_primary=is_primary)
        return Response(BankAccountSerializer(bank_account).data, status=status.HTTP_201_CREATED)


class MemberBankAccountDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _get_member(self, request):
        try:
            return request.user.member
        except Member.DoesNotExist:
            return None

    def _get_member_account(self, member, pk):
        try:
            return BankAccount.objects.get(pk=pk, member=member)
        except BankAccount.DoesNotExist:
            return None

    def patch(self, request, pk):
        member = self._get_member(request)
        if not member:
            return Response({'error': 'Profil tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

        bank_account = self._get_member_account(member, pk)
        if not bank_account:
            return Response({'error': 'Rekening bank tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

        serializer = BankAccountSerializer(bank_account, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        is_primary = serializer.validated_data.get('is_primary')
        if is_primary is False and bank_account.is_primary:
            return Response(
                {'error': 'Harus ada minimal satu rekening utama.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if is_primary is True:
            BankAccount.objects.filter(member=member, is_primary=True).exclude(pk=bank_account.pk).update(is_primary=False)

        updated_account = serializer.save()
        return Response(BankAccountSerializer(updated_account).data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        member = self._get_member(request)
        if not member:
            return Response({'error': 'Profil tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

        bank_account = self._get_member_account(member, pk)
        if not bank_account:
            return Response({'error': 'Rekening bank tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

        was_primary = bank_account.is_primary
        bank_account.delete()

        if was_primary:
            fallback_account = BankAccount.objects.filter(member=member).order_by('id').first()
            if fallback_account:
                fallback_account.is_primary = True
                fallback_account.save(update_fields=['is_primary'])

        return Response(status=status.HTTP_204_NO_CONTENT)

class MemberDashboardView(APIView):
    """
    PBI-39 - Lihat Dashboard Anggota
    GET /api/dashboards/member/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            member = request.user.member
        except Exception:
            return Response({'error': 'Member profile not found'}, status=404)

        # 1. Total Simpanan 
        balance = getattr(member, 'savings_balance', None)
        if balance:
            total_savings = balance.total_overall
        else:
            total_savings = SavingTransaction.objects.filter(
                member=member, status=SavingStatus.SUCCESS
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        # 2. Total Pinjaman Aktif (outstanding) 
        active_loans = member.loans.filter(
            status__in=[LoanStatus.ACTIVE, LoanStatus.OVERDUE]
        )
        total_loan = sum(loan.outstanding_balance for loan in active_loans)

        # Recent Transactions
        # a) Saving transactions
        saving_txs = SavingTransaction.objects.filter(
            member=member
        ).order_by('-submitted_at')[:20]

        saving_items = []
        for tx in saving_txs:
            type_label = {
                'POKOK': 'Simpanan Pokok',
                'WAJIB': 'Simpanan Wajib',
                'SUKARELA': 'Simpanan Sukarela',
            }.get(tx.saving_type, tx.saving_type)

            saving_items.append({
                'transaction_id': tx.transaction_id,
                'date': tx.submitted_at.isoformat() if tx.submitted_at else None,
                'description': f'Setoran {type_label}',
                'type': 'CREDIT',
                'amount': str(tx.amount),
                'status': tx.status,
                'source': 'SAVING',
            })

        # b) Installment payments (PAID dan PENDING)
        installments = Installment.objects.filter(
            loan__member=member,
            status__in=[InstallmentStatus.PAID, InstallmentStatus.PENDING],
        ).select_related('loan').order_by('-submitted_at')[:20]

        installment_items = []
        for ins in installments:
            installment_items.append({
                'transaction_id': ins.transaction_id or f'TRX-INS-{ins.id:05d}',
                'date': (ins.submitted_at or ins.updated_at).isoformat(),
                'description': f'Angsuran Pinjaman #{ins.loan.loan_id} (Cicilan {ins.installment_number})',
                'type': 'DEBIT',
                'amount': str(ins.amount),
                'status': ins.status,
                'source': 'INSTALLMENT',
            })

        # c) Gabungkan dan sort by date descending, ambil 10 terbaru
        all_transactions = saving_items + installment_items
        all_transactions.sort(
            key=lambda x: x['date'] or '',
            reverse=True
        )
        recent_transactions = all_transactions[:10]

        return Response({
            'total_savings': str(total_savings),
            'total_loan': str(total_loan),
            'recent_transactions': recent_transactions,
        })