import re
from datetime import date
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from users.models import User
from .models import Member, BankAccount
from .utils import add_watermark

class MemberRegisterSerializer(serializers.Serializer):
    # Basic Info
    full_name      = serializers.CharField(max_length=255)
    place_of_birth = serializers.CharField(max_length=100)
    date_of_birth  = serializers.DateField()
    gender         = serializers.ChoiceField(choices=[('M','M'),('F','F')])
    occupation     = serializers.CharField(max_length=100)
    # Contact Info
    phone_number   = serializers.CharField(max_length=20)
    home_address   = serializers.CharField()
    city           = serializers.CharField(max_length=100)
    postal_code    = serializers.CharField(max_length=10)
    # Documents
    nik            = serializers.CharField(max_length=16)
    ktp_image      = serializers.ImageField()
    selfie_image = serializers.ImageField()
    # Account Info
    email          = serializers.EmailField()
    password       = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    def validate_phone_number(self, value):
        if not re.fullmatch(r'08\d{8,11}', value):
            raise serializers.ValidationError(
                'Nomor telepon harus diawali 08 dan terdiri dari 10–13 digit angka'
            )
        return value

    def validate_postal_code(self, value):
        if not re.fullmatch(r'\d{5}', value):
            raise serializers.ValidationError('Kode pos harus berupa 5 digit angka')
        return value

    def validate_nik(self, value):
        if not re.fullmatch(r'\d{16}', value):
            raise serializers.ValidationError('NIK harus berupa 16 digit angka')
        if Member.objects.filter(nik=value).exists():
            raise serializers.ValidationError('NIK sudah terdaftar')
        return value

    def validate_date_of_birth(self, value):
        today = date.today()
        if value >= today:
            raise serializers.ValidationError('Tanggal lahir tidak valid')
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 17:
            raise serializers.ValidationError('Pendaftar harus berusia minimal 17 tahun')
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('Email sudah terdaftar')
        return value

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Password tidak cocok'})
        
        if 'ktp_image' in data and data['ktp_image']:
            data['ktp_image'] = add_watermark(
                data['ktp_image'],
                text="SI-MAPAN"
            )

        if 'selfie_image' in data and data['selfie_image']:
            data['selfie_image'] = add_watermark(
                data['selfie_image'],
                text="SI-MAPAN"
            )

        return data

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        email    = validated_data.pop('email')
        password = validated_data.pop('password')
        user     = User.objects.create_user(email=email, password=password)
        member   = Member.objects.create(user=user, **validated_data)
        return member

class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = ['id', 'bank_name', 'account_number', 'account_holder', 'is_primary']

class MemberProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source='user.email', read_only=True)
    bank_accounts = BankAccountSerializer(many=True, read_only=True)
    profile_picture = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = [
            'member_id', 'full_name', 'gender', 'place_of_birth', 
            'date_of_birth', 'occupation', 'nik', 'email', 'phone_number', 
            'home_address', 'profile_picture', 'bank_accounts',
            'status'
        ]
        # Field yang dilarang diubah sesuai kriteria
        read_only_fields = ['member_id', 'nik', 'email']

    def get_profile_picture(self, obj):
        if obj.selfie_image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.selfie_image.url)
            return obj.selfie_image.url
        return None


# ── Staff Serializers ────────────────────────────────────────────
class PendingMemberListSerializer(serializers.ModelSerializer):
    """Serializer ringkas untuk daftar calon anggota PENDING."""
    email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = Member
        fields = ['id', 'full_name', 'registration_date', 'nik', 'status', 'email']


class MemberDetailSerializer(serializers.ModelSerializer):
    """Serializer lengkap untuk halaman verifikasi petugas."""
    email = serializers.EmailField(source='user.email', read_only=True)
    ktp_image = serializers.SerializerMethodField()
    selfie_image = serializers.SerializerMethodField()
    verified_by_email = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = [
            'id',
            'full_name',
            'place_of_birth',
            'date_of_birth',
            'gender',
            'occupation',
            'phone_number',
            'home_address',
            'city',
            'postal_code',
            'nik',
            'ktp_image',
            'selfie_image',
            'email',
            'status',
            'rejection_reason',
            'registration_date',
            'verified_by_email',
            'verified_at',
        ]

    def get_ktp_image(self, obj):
        request = self.context.get('request')
        if obj.ktp_image:
            return request.build_absolute_uri(obj.ktp_image.url) if request else obj.ktp_image.url
        return None

    def get_selfie_image(self, obj):
        request = self.context.get('request')
        if obj.selfie_image:
            return request.build_absolute_uri(obj.selfie_image.url) if request else obj.selfie_image.url
        return None

    def get_verified_by_email(self, obj):
        if obj.verified_by:
            return obj.verified_by.email
        return None


class MemberVerifySerializer(serializers.Serializer):
    """Payload untuk approve / reject calon anggota."""
    ACTION_CHOICES = [('approve', 'Approve'), ('reject', 'Reject')]

    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    rejection_reason = serializers.CharField(required=False, allow_blank=True, default='')

    def validate(self, data):
        if data['action'] == 'reject' and not data.get('rejection_reason', '').strip():
            raise serializers.ValidationError(
                {'rejection_reason': 'Alasan penolakan wajib diisi ketika menolak anggota.'}
            )
        return data