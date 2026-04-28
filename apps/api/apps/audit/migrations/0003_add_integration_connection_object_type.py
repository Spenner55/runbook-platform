from django.db import migrations, models


class Migration(migrations.Migration):
    """Add INTEGRATION_CONNECTION to AuditEvent.ObjectType choices."""

    dependencies = [
        ("audit", "0002_add_artifact_object_type"),
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
                    ("integration_connection", "Integration Connection"),
                ],
                max_length=64,
            ),
        ),
    ]
