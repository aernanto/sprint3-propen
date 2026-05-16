from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('refunds', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='refund',
            name='transfer_proof',
            field=models.FileField(blank=True, null=True, upload_to='refunds/proofs/'),
        ),
    ]
