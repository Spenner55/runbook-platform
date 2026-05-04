from django.db import migrations, models


def backfill_execution_step_subject_id(apps, schema_editor):
    """Ensure all execution_step approvals have subject_id set (= step_id)."""
    ApprovalRequest = apps.get_model("approvals", "ApprovalRequest")
    for ar in ApprovalRequest.objects.filter(
        subject_type="execution_step",
        subject_id__isnull=True,
        step_id__isnull=False,
    ):
        ApprovalRequest.objects.filter(pk=ar.pk).update(subject_id=ar.step_id)


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0004_approval_subject_fields"),
    ]

    operations = [
        migrations.RunPython(
            backfill_execution_step_subject_id, migrations.RunPython.noop
        ),
        migrations.AddConstraint(
            model_name="approvalrequest",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        subject_type="execution_step",
                        execution_id__isnull=False,
                        step_id__isnull=False,
                    )
                    | models.Q(
                        subject_type="change_record",
                        subject_id__isnull=False,
                        execution_id__isnull=True,
                        step_id__isnull=True,
                    )
                ),
                name="approval_req_subject_integrity_chk",
            ),
        ),
    ]
