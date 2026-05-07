"""Management command for explicit evidence storage retention cleanup.

No background worker: this command must be run explicitly by an operator.
It deletes stored ZIP bytes only when the retention deadline has passed and
no active legal hold covers the bundle or export.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.audit.services import system_actor
from apps.common.exceptions import DomainValidationError
from apps.evidence import services
from apps.evidence.models import EvidenceBundle, EvidenceExport


class Command(BaseCommand):
    help = (
        "Delete stored ZIP bytes for evidence bundles and exports whose retention "
        "period has expired. Legal holds are always respected. Metadata rows are kept."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--bundles",
            action="store_true",
            default=False,
            dest="do_bundles",
            help="Clean up expired sealed/invalidated bundle storage.",
        )
        parser.add_argument(
            "--exports",
            action="store_true",
            default=False,
            dest="do_exports",
            help="Clean up expired export storage.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            dest="dry_run",
            help="Report what would be cleaned up without deleting anything.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            dest="batch_size",
            help="Maximum rows to process per run (default: 100).",
        )

    def handle(self, *args, **options):
        do_bundles = options["do_bundles"]
        do_exports = options["do_exports"]
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        if not do_bundles and not do_exports:
            self.stderr.write(
                "Specify --bundles and/or --exports to select what to clean up."
            )
            return

        now = timezone.now()
        actor = system_actor("cleanup_evidence_storage management command")
        deleted_bundles = 0
        skipped_bundles = 0
        deleted_exports = 0
        skipped_exports = 0

        if do_bundles:
            candidates = (
                EvidenceBundle.objects.filter(
                    storage_deleted_at__isnull=True,
                    storage_key__gt="",
                    retention_expires_at__lte=now,
                    status__in=[
                        EvidenceBundle.Status.SEALED,
                        EvidenceBundle.Status.INVALIDATED,
                    ],
                )
                .order_by("retention_expires_at", "id")[:batch_size]
            )
            for bundle in candidates:
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would clean bundle {bundle.id} "
                        f"(expired {bundle.retention_expires_at})"
                    )
                    deleted_bundles += 1
                    continue
                try:
                    services.cleanup_expired_bundle_storage(bundle, actor=actor, now=now)
                    deleted_bundles += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"Cleaned bundle {bundle.id}")
                    )
                except DomainValidationError as exc:
                    skipped_bundles += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipped bundle {bundle.id}: {exc.code} — {exc.detail}"
                        )
                    )

        if do_exports:
            candidates = (
                EvidenceExport.objects.filter(
                    storage_deleted_at__isnull=True,
                    storage_key__gt="",
                    expires_at__lte=now,
                    status=EvidenceExport.Status.READY,
                )
                .order_by("expires_at", "id")[:batch_size]
            )
            for export in candidates:
                if dry_run:
                    self.stdout.write(
                        f"[DRY RUN] Would clean export {export.id} "
                        f"(expired {export.expires_at})"
                    )
                    deleted_exports += 1
                    continue
                try:
                    services.cleanup_expired_export_storage(export, actor=actor, now=now)
                    deleted_exports += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"Cleaned export {export.id}")
                    )
                except DomainValidationError as exc:
                    skipped_exports += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipped export {export.id}: {exc.code} — {exc.detail}"
                        )
                    )

        summary_parts = []
        if do_bundles:
            summary_parts.append(
                f"bundles: {deleted_bundles} cleaned, {skipped_bundles} skipped"
            )
        if do_exports:
            summary_parts.append(
                f"exports: {deleted_exports} cleaned, {skipped_exports} skipped"
            )
        self.stdout.write("; ".join(summary_parts) or "Nothing to report.")
