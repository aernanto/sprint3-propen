import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('members', '0005_alter_bankaccount_id_alter_member_id'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ResignationRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(
                    choices=[
                        ('PENDING', 'Pending'),
                        ('REJECTED', 'Rejected'),
                        ('APPROVED', 'Approved'),
                        ('RESIGNED', 'Resigned'),
                    ],
                    default='PENDING',
                    max_length=20,
                )),
                ('total_savings_snapshot', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('total_pokok_snapshot', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('total_wajib_snapshot', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('total_sukarela_snapshot', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('total_loan_outstanding_snapshot', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('estimated_payout', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('rejection_reason', models.TextField(blank=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('member', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='resignation_requests',
                    to='members.member',
                )),
                ('reviewed_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='reviewed_resignations',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['-submitted_at']},
        ),
    ]
