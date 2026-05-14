from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("executions", "0009_add_execution_mode_and_snapshot_hash"),
    ]

    operations = [
        migrations.AddField(
            model_name="execution",
            name="runner_pool_key",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
