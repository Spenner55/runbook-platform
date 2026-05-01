import django.db.models.deletion
from django.db import migrations, models


def backfill_subject_fields(apps, schema_editor):
    ApprovalRequest = apps.get_model("approvals", "ApprovalRequest")
    ApprovalRequest.objects.filter(subject_type__isnull=True).update(
        subject_type="execution_step",
    )
    for ar in ApprovalRequest.objects.filter(subject_id__isnull=True, step_id__isnull=False):
        ApprovalRequest.objects.filter(pk=ar.pk).update(subject_id=ar.step_id)


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0003_approvalrequest_approval_req_status_req_idx"),
        ("executions", "0007_execution_exec_status_valid_chk_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="approvalrequest",
            name="subject_type",
            field=models.CharField(
                choices=[
                    ("execution_step", "Execution Step"),
                    ("change_record", "Change Record"),
                ],
                default="execution_step",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="approvalrequest",
            name="subject_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="approvalrequest",
            name="execution",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="approval_requests",
                to="executions.execution",
            ),
        ),
        migrations.AlterField(
            model_name="approvalrequest",
            name="step",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="approval_request",
                to="executions.executionstep",
            ),
        ),
        migrations.RunPython(backfill_subject_fields, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="approvalrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    subject_type__in=["execution_step", "change_record"]
                ),
                name="approval_req_subject_type_valid_chk",
            ),
        ),
    ]
