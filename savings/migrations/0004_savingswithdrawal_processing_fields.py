from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
        ('savings', '0003_savingswithdrawal'),
    ]

    operations = [
        migrations.AddField(
            model_name='savingswithdrawal',
            name='processed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='savingswithdrawal',
            name='processed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name='processed_withdrawals', to='users.user'),
        ),
        migrations.AddField(
            model_name='savingswithdrawal',
            name='transfer_proof',
            field=models.FileField(blank=True, null=True, upload_to='loans/disbursement/'),
        ),
    ]
