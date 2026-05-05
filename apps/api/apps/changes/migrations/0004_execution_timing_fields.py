from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('changes', '0003_windows_freezes_locks'),
    ]

    operations = [
        migrations.AddField(
            model_name='changeexecutionbinding',
            name='execution_accepted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='changeexecutionbinding',
            name='execution_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='changeexecutionbinding',
            name='execution_finished_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
