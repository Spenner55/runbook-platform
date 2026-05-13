from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("policies", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="policyrule",
            name="condition_type",
            field=models.CharField(
                choices=[
                    ("risk_level", "Risk Level"),
                    ("step_type", "Step Type"),
                    ("time_window", "Time Window"),
                    ("action_type", "Action Type"),
                    ("action_version", "Action Version"),
                    ("execution_mode", "Execution Mode"),
                    ("idempotency_mode", "Idempotency Mode"),
                    ("mutates_target", "Mutates Target"),
                ],
                max_length=32,
            ),
        ),
    ]
