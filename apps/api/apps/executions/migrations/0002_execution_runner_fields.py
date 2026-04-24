from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("executions", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="execution",
            name="claimed_by_runner_id",
            field=models.CharField(blank=True, max_length=255, default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="execution",
            name="claim_token",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="execution",
            name="claimed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="execution",
            name="last_heartbeat_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
