from rest_framework import serializers
from django.contrib.auth import get_user_model
from members.models import Member

User = get_user_model()

class LoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        # Cari user berdasarkan email (termasuk yang is_active=False)
        try:
            user = User.objects.get(email__iexact=data['email'])
        except User.DoesNotExist:
            raise serializers.ValidationError('Email atau password salah')

        # Verifikasi password
        if not user.check_password(data['password']):
            raise serializers.ValidationError('Email atau password salah')

        # Cek status member untuk pesan error yang spesifik
        try:
            member = user.member
            if member.status == 'PENDING':
                raise serializers.ValidationError(
                    'Akun kamu belum diverifikasi. Silakan cek status pendaftaran kamu.'
                )
            if member.status == 'REJECTED':
                raise serializers.ValidationError(
                    'Akun kamu ditolak. Silakan hubungi petugas untuk informasi lebih lanjut.'
                )
            if member.status == 'INACTIVE':
                raise serializers.ValidationError(
                    'Akun kamu sudah tidak aktif. Silakan hubungi petugas untuk aktivasi kembali.'
                )
        except Member.DoesNotExist:
            pass

        # Cek is_active untuk non-member (staff/manager/chairman yang di-deactivate manual)
        if not user.is_active:
            raise serializers.ValidationError(
                'Akun kamu sudah tidak aktif. Silakan hubungi petugas untuk aktivasi kembali.'
            )

        data['user'] = user
        return data

class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)
    confirm_password = serializers.CharField(required=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError("Konfirmasi password tidak cocok.")
        return data
