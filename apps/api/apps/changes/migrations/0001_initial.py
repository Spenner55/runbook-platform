import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("approvals", "0004_approval_subject_fields"),
        ("audit", "0006_add_change_object_types"),
        ("executions", "0007_execution_exec_status_valid_chk_and_more"),
        ("organizations", "0001_initial"),
        ("policies", "0001_initial"),
        ("workflows", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OperationProfile",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="operation_profiles",
                        to="organizations.organization",
                    ),
                ),
                ("key", models.CharField(max_length=96)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("risk_level", models.CharField(max_length=32)),
                ("requires_approval", models.BooleanField(default=True)),
                ("verification_required", models.BooleanField(default=True)),
                (
                    "approval_ttl_seconds",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                ("dispatch_ttl_seconds", models.PositiveIntegerField(default=900)),
                ("allowed_target_types", models.JSONField(default=list)),
                ("requested_inputs_schema", models.JSONField(default=dict)),
                ("target_schema", models.JSONField(default=dict)),
                (
                    "allowed_workflows",
                    models.ManyToManyField(
                        blank=True,
                        related_name="operation_profiles",
                        to="workflows.workflow",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_operation_profiles",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_operation_profiles",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"abstract": False},
        ),
        migrations.CreateModel(
            name="ChangeRecord",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="change_records",
                        to="organizations.organization",
                    ),
                ),
                (
                    "operation_profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="change_records",
                        to="changes.operationprofile",
                    ),
                ),
                (
                    "workflow",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="change_records",
                        to="workflows.workflow",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="requested_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "submitted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="submitted_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("summary", models.TextField(blank=True)),
                ("justification", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("pending_approval", "Pending Approval"),
                            ("approved", "Approved"),
                            ("scheduled", "Scheduled"),
                            ("dispatchable", "Dispatchable"),
                            ("running", "Running"),
                            ("verification_pending", "Verification Pending"),
                            ("verified", "Verified"),
                            ("closed", "Closed"),
                            ("rejected", "Rejected"),
                            ("canceled", "Canceled"),
                            ("expired", "Expired"),
                        ],
                        default="draft",
                        max_length=32,
                    ),
                ),
                ("requested_inputs", models.JSONField(default=dict)),
                (
                    "requested_inputs_sha256",
                    models.CharField(blank=True, max_length=64),
                ),
                ("request_snapshot", models.JSONField(default=dict)),
                (
                    "request_snapshot_sha256",
                    models.CharField(blank=True, max_length=64),
                ),
                (
                    "operation_profile_key_snapshot",
                    models.CharField(blank=True, max_length=96),
                ),
                (
                    "workflow_version_snapshot",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "approval_request",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="change_records",
                        to="approvals.approvalrequest",
                    ),
                ),
                (
                    "policy_evaluation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="change_records",
                        to="policies.policyevaluation",
                    ),
                ),
                ("policy_decision_snapshot", models.JSONField(default=dict)),
                ("scheduled_for", models.DateTimeField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("dispatchable_at", models.DateTimeField(blank=True, null=True)),
                ("running_at", models.DateTimeField(blank=True, null=True)),
                (
                    "verification_pending_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("rejected_at", models.DateTimeField(blank=True, null=True)),
                ("canceled_at", models.DateTimeField(blank=True, null=True)),
                ("expired_at", models.DateTimeField(blank=True, null=True)),
                ("terminal_reason", models.CharField(blank=True, max_length=64)),
            ],
            options={"ordering": ["-created_at"], "abstract": False},
        ),
        migrations.CreateModel(
            name="ChangeTarget",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "change_record",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="targets",
                        to="changes.changerecord",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="change_targets",
                        to="organizations.organization",
                    ),
                ),
                ("position", models.PositiveIntegerField()),
                ("target_type", models.CharField(max_length=64)),
                ("target_identifier", models.CharField(max_length=255)),
                ("normalized_identifier", models.CharField(max_length=255)),
                ("display_name", models.CharField(blank=True, max_length=255)),
                ("environment", models.CharField(max_length=32)),
                ("metadata", models.JSONField(default=dict)),
            ],
            options={"ordering": ["position"], "abstract": False},
        ),
        migrations.CreateModel(
            name="ChangeExecutionBinding",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "change_record",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_binding",
                        to="changes.changerecord",
                    ),
                ),
                (
                    "execution",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="change_binding",
                        to="executions.execution",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="change_execution_bindings",
                        to="organizations.organization",
                    ),
                ),
                ("operation_profile_key", models.CharField(max_length=96)),
                ("requested_inputs_sha256", models.CharField(max_length=64)),
                ("dispatch_token_nonce", models.CharField(max_length=128)),
                ("dispatch_token_hash", models.CharField(max_length=128)),
                ("dispatch_token_expires_at", models.DateTimeField()),
                ("reserved_at", models.DateTimeField()),
                ("bound_at", models.DateTimeField(blank=True, null=True)),
                ("bound_by_runner_id", models.CharField(blank=True, max_length=255)),
                ("runner_payload_snapshot", models.JSONField(default=dict)),
            ],
            options={"abstract": False},
        ),
        migrations.AddIndex(
            model_name="operationprofile",
            index=models.Index(
                fields=["organization", "is_active", "key"],
                name="op_profile_org_active_key_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="operationprofile",
            constraint=models.UniqueConstraint(
                fields=["organization", "key"],
                name="op_profile_org_key_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="operationprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(risk_level__in=["high", "critical"]),
                name="op_profile_risk_level_valid_chk",
            ),
        ),
        migrations.AddIndex(
            model_name="changerecord",
            index=models.Index(
                fields=["organization", "status", "created_at"],
                name="chgrec_org_status_created_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="changerecord",
            index=models.Index(
                fields=["organization", "operation_profile", "status"],
                name="chgrec_org_profile_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="changerecord",
            index=models.Index(
                fields=["approval_request"],
                name="change_rec_approval_req_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="changerecord",
            index=models.Index(
                fields=["workflow", "status"],
                name="change_rec_workflow_status_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="changerecord",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "draft",
                        "pending_approval",
                        "approved",
                        "scheduled",
                        "dispatchable",
                        "running",
                        "verification_pending",
                        "verified",
                        "closed",
                        "rejected",
                        "canceled",
                        "expired",
                    ]
                ),
                name="change_rec_status_valid_chk",
            ),
        ),
        migrations.AddIndex(
            model_name="changetarget",
            index=models.Index(
                fields=["organization", "target_type", "normalized_identifier"],
                name="change_target_org_type_id_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="changetarget",
            constraint=models.UniqueConstraint(
                fields=["change_record", "target_type", "normalized_identifier"],
                name="change_target_unique_type_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="changetarget",
            constraint=models.UniqueConstraint(
                fields=["change_record", "position"],
                name="change_target_unique_position",
            ),
        ),
        migrations.AddConstraint(
            model_name="changetarget",
            constraint=models.CheckConstraint(
                condition=models.Q(environment="production"),
                name="change_target_env_production_chk",
            ),
        ),
        migrations.AddIndex(
            model_name="changeexecutionbinding",
            index=models.Index(
                fields=["organization", "reserved_at"],
                name="chgexecbind_org_reserved_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="changeexecutionbinding",
            index=models.Index(
                fields=["dispatch_token_expires_at"],
                name="change_exec_binding_exp_idx",
            ),
        ),
    ]
