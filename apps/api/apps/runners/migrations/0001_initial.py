import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("executions", "0009_add_execution_mode_and_snapshot_hash"),
        ("organizations", "0004_membership_operator_role"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RunnerPool",
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
                ("key", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("environment", models.CharField(default="production", max_length=32)),
                ("network_zone", models.CharField(blank=True, max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("draining", "Draining"),
                            ("disabled", "Disabled"),
                        ],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("max_concurrent_executions", models.PositiveIntegerField(default=1)),
                ("max_concurrent_per_target", models.PositiveIntegerField(default=1)),
                ("labels", models.JSONField(default=dict)),
                ("capabilities", models.JSONField(default=list)),
                ("metadata", models.JSONField(default=dict)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="runner_pools",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="Runner",
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
                ("display_name", models.CharField(max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("registered", "Registered"),
                            ("active", "Active"),
                            ("draining", "Draining"),
                            ("offline", "Offline"),
                            ("disabled", "Disabled"),
                            ("revoked", "Revoked"),
                        ],
                        default="registered",
                        max_length=16,
                    ),
                ),
                ("runner_version", models.CharField(blank=True, max_length=64)),
                ("hostname", models.CharField(blank=True, max_length=255)),
                ("fingerprint_sha256", models.CharField(blank=True, max_length=64)),
                ("token_hash", models.CharField(max_length=128)),
                ("registered_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("last_heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("drain_requested_at", models.DateTimeField(blank=True, null=True)),
                ("disabled_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("metadata", models.JSONField(default=dict)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="runners",
                        to="organizations.organization",
                    ),
                ),
                (
                    "pool",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="runners",
                        to="runners.runnerpool",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="RunnerRegistrationToken",
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
                ("token_hash", models.CharField(max_length=128)),
                ("label_policy", models.JSONField(default=list)),
                ("capability_policy", models.JSONField(default=list)),
                ("expires_at", models.DateTimeField()),
                ("max_registrations", models.PositiveIntegerField(default=1)),
                ("used_count", models.PositiveIntegerField(default=0)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="runner_registration_tokens",
                        to="organizations.organization",
                    ),
                ),
                (
                    "pool",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="registration_tokens",
                        to="runners.runnerpool",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_registration_tokens",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="TargetConnectivityRoute",
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
                ("environment", models.CharField(default="production", max_length=32)),
                ("target_type", models.CharField(max_length=64)),
                ("normalized_identifier_pattern", models.CharField(max_length=255)),
                ("required_labels", models.JSONField(default=dict)),
                ("required_capabilities", models.JSONField(default=list)),
                ("priority", models.PositiveIntegerField(default=100)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="target_connectivity_routes",
                        to="organizations.organization",
                    ),
                ),
                (
                    "pool",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="connectivity_routes",
                        to="runners.runnerpool",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="ExecutionLease",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("released", "Released"),
                            ("expired", "Expired"),
                        ],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("claimed_at", models.DateTimeField()),
                ("last_heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("released_at", models.DateTimeField(blank=True, null=True)),
                ("release_reason", models.CharField(blank=True, max_length=64)),
                (
                    "execution",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="lease",
                        to="executions.execution",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_leases",
                        to="organizations.organization",
                    ),
                ),
                (
                    "runner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_leases",
                        to="runners.runner",
                    ),
                ),
                (
                    "pool",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="execution_leases",
                        to="runners.runnerpool",
                    ),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        # RunnerPool constraints and indexes
        migrations.AddConstraint(
            model_name="runnerpool",
            constraint=models.UniqueConstraint(
                fields=["organization", "key"],
                name="runner_pool_org_key_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="runnerpool",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=["active", "draining", "disabled"]),
                name="runner_pool_status_valid_chk",
            ),
        ),
        migrations.AddIndex(
            model_name="runnerpool",
            index=models.Index(
                fields=["organization", "status"],
                name="runner_pool_org_status_idx",
            ),
        ),
        # Runner constraints and indexes
        migrations.AddConstraint(
            model_name="runner",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    status__in=[
                        "registered",
                        "active",
                        "draining",
                        "offline",
                        "disabled",
                        "revoked",
                    ]
                ),
                name="runner_status_valid_chk",
            ),
        ),
        migrations.AddIndex(
            model_name="runner",
            index=models.Index(
                fields=["organization", "pool", "status", "last_heartbeat_at"],
                name="runner_org_pool_status_hb_idx",
            ),
        ),
        # RunnerRegistrationToken indexes
        migrations.AddIndex(
            model_name="runnerregistrationtoken",
            index=models.Index(
                fields=["organization", "pool", "expires_at"],
                name="reg_token_org_pool_exp_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="runnerregistrationtoken",
            index=models.Index(
                fields=["organization", "revoked_at"],
                name="reg_token_org_revoked_idx",
            ),
        ),
        # TargetConnectivityRoute indexes
        migrations.AddIndex(
            model_name="targetconnectivityroute",
            index=models.Index(
                fields=["organization", "environment", "target_type", "is_active"],
                name="tcr_org_env_type_active_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="targetconnectivityroute",
            index=models.Index(
                fields=["organization", "pool", "is_active"],
                name="tcr_org_pool_active_idx",
            ),
        ),
        # ExecutionLease constraints and indexes
        migrations.AddConstraint(
            model_name="executionlease",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=["active", "released", "expired"]),
                name="exec_lease_status_valid_chk",
            ),
        ),
        migrations.AddIndex(
            model_name="executionlease",
            index=models.Index(
                fields=["organization", "pool", "status"],
                name="exec_lease_org_pool_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="executionlease",
            index=models.Index(
                fields=["runner", "status"],
                name="exec_lease_runner_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="executionlease",
            index=models.Index(
                fields=["status", "last_heartbeat_at"],
                name="exec_lease_status_hb_idx",
            ),
        ),
    ]
