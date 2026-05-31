import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('members', '0002_initial'),
        ('savings', '0002_savingtransaction_verified_by_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SavingsWithdrawal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('withdrawal_id', models.CharField(blank=True, max_length=50, unique=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=14)),
                ('bank_name', models.CharField(max_length=100)),
                ('account_number', models.CharField(max_length=50)),
                ('account_holder', models.CharField(max_length=150)),
                ('notes', models.TextField(blank=True)),
                ('status', models.CharField(
                    choices=[('PENDING', 'Pending'), ('COMPLETED', 'Completed')],
                    default='PENDING',
                    max_length=20,
                )),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('member', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='savings_withdrawals',
                    to='members.member',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
