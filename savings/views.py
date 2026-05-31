from django.db.models import DecimalField, Sum, Value
from django.db.models import Q
from django.db.models.functions import Coalesce
from rest_framework import permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from config.models import CooperativeBank
from loans.models import Installment, InstallmentStatus
from savings.models import SavingStatus, SavingTransaction, SavingType, SavingsBalance, SavingsWithdrawal, WithdrawalStatus
from savings.serializers import (
	DepositCreateSerializer,
	InitialDepositCreateSerializer,
	SavingTransactionSerializer,
	WithdrawalCreateSerializer,
	WithdrawalSerializer,
)


class SavingsPagination(PageNumberPagination):
	page_size = 5
	page_size_query_param = 'page_size'
	max_page_size = 50


class BaseMemberSavingsView(APIView):
	permission_classes = [permissions.IsAuthenticated]

	def get_member(self, user):
		return getattr(user, 'member', None)

	def ensure_member_role(self, user):
		return user.role == 'MEMBER'


class InitialDepositCreateView(BaseMemberSavingsView):
	parser_classes = [MultiPartParser, FormParser]

	def post(self, request):
		if not self.ensure_member_role(request.user):
			return Response({'detail': 'Hanya anggota yang dapat melakukan setoran'}, status=status.HTTP_403_FORBIDDEN)

		member = self.get_member(request.user)
		if not member or member.status != 'VERIFIED':
			return Response(
				{'detail': 'Hanya anggota berstatus VERIFIED yang bisa upload simpanan pokok'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		serializer = InitialDepositCreateSerializer(data=request.data, context={'request': request})
		serializer.is_valid(raise_exception=True)

		saving = SavingTransaction.objects.filter(
			member=member,
			saving_type=SavingType.POKOK,
		).order_by('-submitted_at').first()

		if saving and saving.status == SavingStatus.SUCCESS:
			return Response(
				{'detail': 'Simpanan pokok sudah terkonfirmasi sebelumnya'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		validated_data = serializer.validated_data
		if saving:
			saving.transfer_proof = validated_data['transfer_proof']
			saving.member_bank_name = validated_data['member_bank_name']
			saving.member_account_number = validated_data['member_account_number']
			saving.amount = 150000
			saving.status = SavingStatus.PENDING
			saving.rejection_reason = ''
			saving.save()
		else:
			saving = serializer.save()

		# Trigger notifikasi setoran diterima
		try:
			from notifications.service import notify_saving_received
			notify_saving_received(saving)
		except Exception:
			pass

		return Response(
			{
				'message': 'Bukti simpanan pokok berhasil dikirim',
				'data': SavingTransactionSerializer(saving, context={'request': request}).data,
			},
			status=status.HTTP_201_CREATED,
		)


class SavingsDepositCreateView(BaseMemberSavingsView):
	parser_classes = [MultiPartParser, FormParser]

	def post(self, request):
		if not self.ensure_member_role(request.user):
			return Response({'detail': 'Hanya anggota yang dapat melakukan setoran'}, status=status.HTTP_403_FORBIDDEN)

		member = self.get_member(request.user)
		if not member or member.status != 'ACTIVE':
			return Response(
				{'detail': 'Hanya anggota berstatus ACTIVE yang bisa menambah simpanan'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		serializer = DepositCreateSerializer(data=request.data, context={'request': request})
		serializer.is_valid(raise_exception=True)
		saving = serializer.save()

		# Trigger notifikasi setoran diterima
		try:
			from notifications.service import notify_saving_received
			notify_saving_received(saving)
		except Exception:
			pass

		return Response(
			{
				'message': 'Setoran berhasil dikirim dan menunggu verifikasi petugas',
				'data': SavingTransactionSerializer(saving, context={'request': request}).data,
			},
			status=status.HTTP_201_CREATED,
		)


class SavingsOverviewView(BaseMemberSavingsView):
	def get(self, request):
		if not self.ensure_member_role(request.user):
			return Response({'detail': 'Hanya anggota yang dapat mengakses overview'}, status=status.HTTP_403_FORBIDDEN)

		member = self.get_member(request.user)
		if not member:
			return Response({'detail': 'Profil anggota tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

		bank_account = CooperativeBank.objects.filter(is_active=True).first()
		bank_data = None
		if bank_account:
			bank_data = {
				'bank_name': bank_account.bank_name,
				'account_number': bank_account.account_number,
				'account_holder': bank_account.account_holder,
				'qr_code_url': None,
			}

		if member.status not in ['VERIFIED', 'ACTIVE']:
			return Response(
				{'detail': 'Status anggota tidak dapat mengakses overview simpanan'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		transactions = SavingTransaction.objects.filter(member=member)
		if member.status == 'VERIFIED':
			transactions = transactions.filter(saving_type=SavingType.POKOK)

		status_filter = request.query_params.get('status')
		if status_filter:
			transactions = transactions.filter(status=status_filter.upper())

		deposit_items = SavingTransactionSerializer(
			transactions,
			many=True,
			context={'request': request},
		).data

		loan_savings_qs = Installment.objects.filter(
			loan__member=member,
			payment_method='SAVINGS',
		).filter(
			Q(submitted_at__isnull=False)
			| Q(status=InstallmentStatus.UNPAID, rejection_reason__gt='')
		).select_related('loan')

		loan_savings_items = []
		for installment in loan_savings_qs:
			submitted_at_value = installment.submitted_at or installment.updated_at
			submitted_at_iso = submitted_at_value.isoformat() if submitted_at_value else None

			if installment.status == InstallmentStatus.PAID:
				mapped_status = SavingStatus.SUCCESS
			elif installment.status == InstallmentStatus.PENDING:
				mapped_status = SavingStatus.PENDING
			else:
				mapped_status = SavingStatus.REJECTED

			loan_savings_items.append({
				'id': -installment.id,
				'saving_id': f'LOAN-{installment.loan.loan_id}-M{installment.installment_number}',
				'transaction_id': installment.transaction_id or f'TRX-INS-{installment.id:05d}',
				'saving_type': SavingType.SUKARELA,
				'amount': str(installment.amount),
				'status': mapped_status,
				'transfer_proof': None,
				'transfer_proof_url': None,
				'member_bank_name': '',
				'member_account_number': '',
				'rejection_reason': installment.rejection_reason or '',
				'submitted_at': submitted_at_iso,
				'direction': 'OUT',
				'source': 'LOAN_INSTALLMENT',
				'description': f'Pembayaran cicilan {installment.loan.loan_id} - bulan {installment.installment_number} via simpanan sukarela',
				'loan_pk': installment.loan_id,
				'loan_id': installment.loan.loan_id,
				'installment_number': installment.installment_number,
			})

		combined_items = []
		for item in deposit_items:
			combined_items.append({
				**item,
				'direction': 'IN',
				'source': 'SAVINGS_DEPOSIT',
				'description': '',
				'loan_pk': None,
				'loan_id': None,
				'installment_number': None,
			})

		combined_items.extend(loan_savings_items)

		# Add withdrawal items
		if member.status == 'ACTIVE':
			withdrawals_qs = SavingsWithdrawal.objects.filter(member=member)
			
			status_filter = request.query_params.get('status')
			if status_filter:
				# Map frontend status to withdrawal status
				if status_filter.upper() == 'PENDING':
					withdrawals_qs = withdrawals_qs.filter(status=WithdrawalStatus.PENDING)
				elif status_filter.upper() == 'SUCCESS':
					withdrawals_qs = withdrawals_qs.filter(status=WithdrawalStatus.COMPLETED)
				elif status_filter.upper() == 'REJECTED':
					withdrawals_qs = withdrawals_qs.none()  # Withdrawals don't have rejected status

			for withdrawal in withdrawals_qs:
				# Map withdrawal status to saving status for consistency
				mapped_status = SavingStatus.PENDING if withdrawal.status == WithdrawalStatus.PENDING else SavingStatus.SUCCESS
				
				# Build transfer_proof_url
				transfer_proof_url = None
				if withdrawal.transfer_proof:
					transfer_proof_url = request.build_absolute_uri(withdrawal.transfer_proof.url)
				
				combined_items.append({
					'id': -withdrawal.id,
					'saving_id': withdrawal.withdrawal_id,
					'transaction_id': withdrawal.withdrawal_id,
					'saving_type': SavingType.SUKARELA,
					'amount': str(withdrawal.amount),
					'status': mapped_status,
					'transfer_proof': None,
					'transfer_proof_url': transfer_proof_url,
					'member_bank_name': withdrawal.bank_name,
					'member_account_number': withdrawal.account_number,
					'rejection_reason': '',
					'submitted_at': withdrawal.created_at.isoformat(),
					'direction': 'OUT',
					'source': 'SAVINGS_WITHDRAWAL',
					'description': f'Penarikan simpanan sukarela ke {withdrawal.bank_name}',
					'loan_pk': None,
					'loan_id': None,
					'installment_number': None,
				})

		combined_items.sort(key=lambda item: item.get('submitted_at') or '', reverse=True)

		balance = SavingsBalance.objects.filter(member=member).first()
		if balance:
			total_wajib = balance.total_wajib or 0
			total_sukarela = balance.total_sukarela or 0
		else:
			totals_query = SavingTransaction.objects.filter(member=member, status=SavingStatus.SUCCESS)
			totals = totals_query.values('saving_type').annotate(
				total=Coalesce(
					Sum('amount'),
					Value(0, output_field=DecimalField(max_digits=14, decimal_places=2)),
				)
			)

			total_wajib = next((item['total'] for item in totals if item['saving_type'] == SavingType.WAJIB), 0)
			total_sukarela = next((item['total'] for item in totals if item['saving_type'] == SavingType.SUKARELA), 0)

		paginator = SavingsPagination()
		page = paginator.paginate_queryset(combined_items, request, view=self)
		paginated = paginator.get_paginated_response(page).data
		paginated['member_status'] = member.status
		paginated['totals'] = {
			'wajib': f'{total_wajib}',
			'sukarela': f'{total_sukarela}',
		}
		paginated['bank_account'] = bank_data

		return Response(paginated)


# ── Withdrawal views ───────────────────────────────────────────────────────

class WithdrawalBalanceView(BaseMemberSavingsView):
	def get(self, request):
		if not self.ensure_member_role(request.user):
			return Response({'detail': 'Hanya anggota yang dapat mengakses saldo simpanan'}, status=status.HTTP_403_FORBIDDEN)

		member = self.get_member(request.user)
		if not member:
			return Response({'detail': 'Profil anggota tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

		if member.status != 'ACTIVE':
			return Response(
				{'detail': 'Hanya anggota berstatus ACTIVE yang dapat melakukan penarikan'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		try:
			balance = member.savings_balance
			total_sukarela = balance.total_sukarela
		except Exception:
			total_sukarela = 0

		return Response({'total_sukarela': str(total_sukarela)})


class WithdrawalCreateView(BaseMemberSavingsView):
	def post(self, request):
		if not self.ensure_member_role(request.user):
			return Response({'detail': 'Hanya anggota yang dapat melakukan penarikan'}, status=status.HTTP_403_FORBIDDEN)

		member = self.get_member(request.user)
		if not member:
			return Response({'detail': 'Profil anggota tidak ditemukan'}, status=status.HTTP_404_NOT_FOUND)

		if member.status != 'ACTIVE':
			return Response(
				{'detail': 'Hanya anggota berstatus ACTIVE yang dapat melakukan penarikan'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		serializer = WithdrawalCreateSerializer(data=request.data, context={'request': request})
		serializer.is_valid(raise_exception=True)
		withdrawal = serializer.save()

		try:
			from notifications.service import notify_withdrawal_received
			notify_withdrawal_received(withdrawal)
		except Exception:
			pass

		return Response(
			{
				'message': 'Permintaan penarikan simpanan sukarela berhasil diajukan dan sedang diproses',
				'data': WithdrawalSerializer(withdrawal, context={'request': request}).data,
			},
			status=status.HTTP_201_CREATED,
		)
