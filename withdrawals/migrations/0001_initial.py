from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('members', '0005_alter_bankaccount_id_alter_member_id'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WithdrawalRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('withdrawal_id', models.CharField(blank=True, max_length=30, unique=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14)),
                ('status', models.CharField(
                    choices=[('PENDING', 'Menunggu Verifikasi'), ('APPROVED', 'Disetujui'), ('REJECTED', 'Ditolak')],
                    default='PENDING',
                    max_length=20,
                )),
                ('bank_name', models.CharField(max_length=100)),
                ('account_number', models.CharField(max_length=50)),
                ('account_holder', models.CharField(max_length=100)),
                ('balance_sukarela_snapshot', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14)),
                ('notes', models.TextField(blank=True)),
                ('rejection_reason', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('member', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='withdrawal_requests',
                    to='members.member',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='reviewed_withdrawals',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-requested_at'],
            },
        ),
    ]
