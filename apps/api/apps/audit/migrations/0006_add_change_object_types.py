from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0005_auditevent_audit_org_occurred_desc_idx"),
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
                    ("operation_profile", "Operation Profile"),
                    ("change_record", "Change Record"),
                    ("change_target", "Change Target"),
                    ("change_execution_binding", "Change Execution Binding"),
                ],
                max_length=64,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="auditevent",
            name="audit_object_type_valid_chk",
        ),
        migrations.AddConstraint(
            model_name="auditevent",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    object_type__in=[
                        "organization",
                        "runbook",
                        "workflow",
                        "execution",
                        "execution_step",
                        "approval_request",
                        "approval_decision",
                        "policy",
                        "policy_rule",
                        "policy_evaluation",
                        "artifact",
                        "integration_connection",
                        "operation_profile",
                        "change_record",
                        "change_target",
                        "change_execution_binding",
                    ]
                ),
                name="audit_object_type_valid_chk",
            ),
        ),
    ]
