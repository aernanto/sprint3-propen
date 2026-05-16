from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('members', '0005_alter_bankaccount_id_alter_member_id'),
        ('resignations', '0001_initial'),
        ('loans', '0001_initial'),
        ('withdrawals', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Refund',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_type', models.CharField(
                    choices=[
                        ('RESIGNATION', 'Pengembalian Pengunduran Diri'),
                        ('INSTALLMENT', 'Pengembalian Cicilan Ditolak'),
                        ('WITHDRAWAL', 'Pencairan Penarikan Simpanan'),
                    ],
                    max_length=20,
                )),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14)),
                ('status', models.CharField(
                    choices=[('PENDING', 'Menunggu Pencairan'), ('COMPLETED', 'Selesai')],
                    default='PENDING',
                    max_length=20,
                )),
                ('approved_at', models.DateTimeField()),
                ('disbursed_at', models.DateTimeField(blank=True, null=True)),
                ('transfer_proof', models.ImageField(blank=True, null=True, upload_to='refunds/proofs/')),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('member', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='refunds',
                    to='members.member',
                )),
                ('resignation', models.OneToOneField(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='refund',
                    to='resignations.resignationrequest',
                )),
                ('installment', models.OneToOneField(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='refund',
                    to='loans.installment',
                )),
                ('withdrawal', models.OneToOneField(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='refund',
                    to='withdrawals.withdrawalrequest',
                )),
                ('disbursed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='disbursed_refunds',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-approved_at'],
            },
        ),
    ]
