from django.db import migrations, models


class Migration(migrations.Migration):
    """Add ARTIFACT to AuditEvent.ObjectType choices (metadata only, no schema change)."""

    dependencies = [
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditevent",
            name="object_type",
            field=models.CharField(
                choices=[
                    ("organization", "Organization"),
                    ("runbook", "Runbook"),
                    ("workflow", "Workflow"),
                    ("execution", "Execution"),
                    ("execution_step", "Execution Step"),
                    ("approval_request", "Approval Request"),
                    ("approval_decision", "Approval Decision"),
                    ("policy", "Policy"),
                    ("policy_rule", "Policy Rule"),
                    ("policy_evaluation", "Policy Evaluation"),
                    ("artifact", "Artifact"),
                ],
                max_length=64,
            ),
        ),
    ]
