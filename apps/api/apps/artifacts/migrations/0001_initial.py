import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("executions", "0006_alter_executionstep_status"),
        ("organizations", "0002_alter_organization_slug"),
    ]

    operations = [
        migrations.CreateModel(
            name="Artifact",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("stdout", "Stdout"),
                            ("stderr", "Stderr"),
                            ("file", "File"),
                            ("report", "Report"),
                            ("diagnostic", "Diagnostic"),
                        ],
                        max_length=32,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("original_name", models.CharField(blank=True, max_length=255)),
                ("mime_type", models.CharField(max_length=128)),
                ("size_bytes", models.PositiveBigIntegerField()),
                ("checksum_sha256", models.CharField(max_length=64)),
                ("storage_key", models.CharField(max_length=1024, unique=True)),
                ("uploaded_by_runner_id", models.CharField(max_length=255)),
                (
                    "upload_status",
                    models.CharField(
                        choices=[("available", "Available"), ("failed", "Failed")],
                        default="available",
                        max_length=16,
                    ),
                ),
                ("uploaded_at", models.DateTimeField()),
                (
                    "content_disposition",
                    models.CharField(
                        choices=[("attachment", "Attachment"), ("inline", "Inline")],
                        default="attachment",
                        max_length=16,
                    ),
                ),
                ("metadata", models.JSONField(default=dict)),
                (
                    "execution",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="artifacts",
                        to="executions.execution",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="artifacts",
                        to="organizations.organization",
                    ),
                ),
                (
                    "step",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="artifacts",
                        to="executions.executionstep",
                    ),
                ),
            ],
            options={
                "ordering": ["-uploaded_at"],
            },
        ),
        migrations.AddIndex(
            model_name="artifact",
            index=models.Index(
                fields=["organization", "uploaded_at"], name="artifact_org_uploaded_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="artifact",
            index=models.Index(
                fields=["execution", "uploaded_at"], name="artifact_exec_uploaded_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="artifact",
            index=models.Index(
                fields=["step", "uploaded_at"], name="artifact_step_uploaded_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="artifact",
            index=models.Index(
                fields=["kind", "uploaded_at"], name="artifact_kind_uploaded_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="artifact",
            index=models.Index(
                fields=["checksum_sha256"], name="artifact_checksum_idx"
            ),
        ),
    ]
