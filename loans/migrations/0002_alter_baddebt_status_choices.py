from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='baddebt',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDING', 'Belum Ditindaklanjuti'),
                    ('WARNING_SENT', 'Peringatan Terkirim'),
                    ('VISIT_SCHEDULED', 'Kunjungan Dijadwalkan'),
                    ('LEGAL_NOTICE', 'Surat Peringatan Hukum'),
                ],
                default='PENDING',
                max_length=20,
            ),
        ),
    ]
