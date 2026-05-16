from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ResignationRequest, ResignationStatus
from .serializers import ResignationRequestSerializer
from .services import calculate_settlement


class ResignationSettlementView(APIView):
    """
    GET /api/resignations/settlement/

    Mengembalikan ringkasan total simpanan, total pinjaman, dan estimasi payout
    untuk anggota yang akan mengajukan penutupan akun.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            member = request.user.member
        except Exception:
            return Response({'error': 'Profil anggota tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        settlement = calculate_settlement(member)

        existing_pending = (
            member.resignation_requests
            .filter(status=ResignationStatus.PENDING)
            .first()
        )
        existing_approved = (
            member.resignation_requests
            .filter(status__in=[ResignationStatus.APPROVED, ResignationStatus.RESIGNED])
            .first()
        )

        return Response({
            'member_name': member.full_name,
            'member_id': member.member_id,
            'total_pokok': settlement['total_pokok'],
            'total_wajib': settlement['total_wajib'],
            'total_sukarela': settlement['total_sukarela'],
            'total_savings': settlement['total_savings'],
            'total_loan_outstanding': settlement['total_loan_outstanding'],
            'estimated_payout': settlement['estimated_payout'],
            'can_resign': settlement['total_loan_outstanding'] <= settlement['total_savings'],
            'has_pending_request': existing_pending is not None,
            'has_active_resignation': existing_approved is not None,
            'pending_request_id': existing_pending.id if existing_pending else None,
        })


class ResignationCreateView(APIView):
    """
    POST /api/resignations/

    Membuat request penutupan akun untuk anggota. Akan menolak request bila:
    - Sudah ada request PENDING/APPROVED/RESIGNED yang aktif
    - Total pinjaman > total simpanan
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            member = request.user.member
        except Exception:
            return Response({'error': 'Profil anggota tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        # Only ACTIVE members can resign; INACTIVE means already resigned, VERIFIED means not yet activated
        if member.status != 'ACTIVE':
            return Response(
                {'error': f'Hanya anggota berstatus ACTIVE yang dapat mengajukan penutupan akun. Status Anda: {member.status}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if member.resignation_requests.filter(
            status__in=[ResignationStatus.PENDING, ResignationStatus.APPROVED, ResignationStatus.RESIGNED]
        ).exists():
            return Response(
                {'error': 'Anda sudah memiliki pengajuan penutupan akun yang masih aktif.'},
                status=status.HTTP_400_BAD_REQUEST,
            )


        settlement = calculate_settlement(member)

        if settlement['total_loan_outstanding'] > settlement['total_savings']:
            return Response(
                {
                    'error': (
                        'Pengajuan penutupan akun tidak dapat diproses karena total pinjaman '
                        'melebihi total simpanan. Mohon lunasi pinjaman terlebih dahulu.'
                    ),
                    'total_savings': settlement['total_savings'],
                    'total_loan_outstanding': settlement['total_loan_outstanding'],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        resignation = ResignationRequest.objects.create(
            member=member,
            status=ResignationStatus.PENDING,
            total_pokok_snapshot=settlement['total_pokok'],
            total_wajib_snapshot=settlement['total_wajib'],
            total_sukarela_snapshot=settlement['total_sukarela'],
            total_savings_snapshot=settlement['total_savings'],
            total_loan_outstanding_snapshot=settlement['total_loan_outstanding'],
            estimated_payout=settlement['estimated_payout'],
        )

        try:
            from notifications.service import notify_resignation_received
            notify_resignation_received(resignation)
        except Exception:
            pass

        serializer = ResignationRequestSerializer(resignation)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ResignationMeView(APIView):
    """
    GET /api/resignations/me/

    Mengembalikan request penutupan akun terbaru milik anggota.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            member = request.user.member
        except Exception:
            return Response({'error': 'Profil anggota tidak ditemukan.'}, status=status.HTTP_404_NOT_FOUND)

        latest = member.resignation_requests.order_by('-submitted_at').first()
        if latest is None:
            return Response({'request': None})

        serializer = ResignationRequestSerializer(latest)
        return Response({'request': serializer.data})
