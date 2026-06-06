from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            'id',
            'type',
            'title',
            'message',
            'is_read',
            'redirect_url',
            'created_at',
        ]
        read_only_fields = ['id', 'type', 'title', 'message', 'redirect_url', 'created_at']


class NotificationListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for the list endpoint.
    Include `message` supaya FE bisa search berdasarkan isi notifikasi (PBI-14)."""
    class Meta:
        model = Notification
        fields = [
            'id',
            'type',
            'title',
            'message',
            'is_read',
            'redirect_url',
            'created_at',
        ]
        read_only_fields = fields