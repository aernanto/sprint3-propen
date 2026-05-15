from rest_framework import serializers

from .models import ResignationRequest


class ResignationRequestSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    member_id = serializers.CharField(source='member.member_id', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ResignationRequest
        fields = [
            'id',
            'member_name',
            'member_id',
            'status',
            'status_display',
            'total_pokok_snapshot',
            'total_wajib_snapshot',
            'total_sukarela_snapshot',
            'total_savings_snapshot',
            'total_loan_outstanding_snapshot',
            'estimated_payout',
            'rejection_reason',
            'submitted_at',
            'reviewed_at',
            'resolved_at',
        ]
        read_only_fields = fields


class ManagerResignationListItemSerializer(serializers.ModelSerializer):
    """Untuk list pending request di halaman manager."""
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    member_id = serializers.CharField(source='member.member_id', read_only=True)
    request_date = serializers.DateTimeField(source='submitted_at', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = ResignationRequest
        fields = [
            'id',
            'member_name',
            'member_id',
            'request_date',
            'status',
            'status_display',
            'estimated_payout',
        ]


class ManagerResignationHistoryItemSerializer(serializers.ModelSerializer):
    """Untuk list yang sudah RESIGNED (akun INACTIVE)."""
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    member_id = serializers.CharField(source='member.member_id', read_only=True)
    approval_date = serializers.DateTimeField(source='reviewed_at', read_only=True)

    class Meta:
        model = ResignationRequest
        fields = [
            'id',
            'member_name',
            'member_id',
            'approval_date',
            'estimated_payout',
        ]
