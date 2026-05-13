from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("changes", "0006_changerecord_emergency_declared_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dispatcheligibilitycheck",
            name="verification_plan_ok",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dispatcheligibilitycheck",
            name="runner_pool_ok",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dispatcheligibilitycheck",
            name="runner_pool_key",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="dispatcheligibilitycheck",
            name="runner_pool_id",
            field=models.CharField(blank=True, max_length=36),
        ),
        migrations.AddField(
            model_name="dispatcheligibilitycheck",
            name="runner_pool_reason",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="operationprofile",
            name="allowed_runner_pool_keys",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="operationprofile",
            name="required_runner_labels",
            field=models.JSONField(default=dict),
        ),
        migrations.AddField(
            model_name="operationprofile",
            name="required_runner_capabilities",
            field=models.JSONField(default=list),
        ),
    ]
