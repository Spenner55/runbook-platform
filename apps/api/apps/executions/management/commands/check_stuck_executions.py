from django.core.management.base import BaseCommand

from apps.approvals import services as approval_services
from apps.executions import services
from apps.runners import services as runner_services


class Command(BaseCommand):
    help = "Recover stuck executions, expired approval timeouts, and stale runners."

    def add_arguments(self, parser):
        parser.add_argument(
            "--threshold-seconds",
            type=int,
            default=300,
            dest="threshold_seconds",
            help="Seconds since last heartbeat before an execution is considered stuck (default: 300).",
        )
        parser.add_argument(
            "--approval-batch-size",
            type=int,
            default=100,
            dest="approval_batch_size",
            help="Maximum expired approvals to recover in one run (default: 100).",
        )
        parser.add_argument(
            "--skip-expired-approvals",
            action="store_true",
            dest="skip_expired_approvals",
            help="Only recover stale executions; do not sweep expired approvals.",
        )
        parser.add_argument(
            "--runner-offline-seconds",
            type=int,
            default=None,
            dest="runner_offline_seconds",
            help=(
                "Seconds since last runner heartbeat before marking it offline. "
                "Defaults to RUNNER_OFFLINE_SECONDS setting."
            ),
        )
        parser.add_argument(
            "--skip-runner-watchdog",
            action="store_true",
            dest="skip_runner_watchdog",
            help="Skip the runner liveness sweep.",
        )

    def handle(self, *args, **options):
        # --- runner liveness sweep ---
        if not options["skip_runner_watchdog"]:
            offline_ids = runner_services.mark_stale_runners_offline(
                offline_threshold_seconds=options["runner_offline_seconds"],
            )
            if offline_ids:
                self.stdout.write(
                    self.style.WARNING(
                        f"Marked {len(offline_ids)} runner(s) offline: "
                        + ", ".join(offline_ids)
                    )
                )
            else:
                self.stdout.write("No stale runners found.")
        else:
            self.stdout.write("Runner watchdog skipped.")

        # --- execution liveness sweep ---
        threshold = options["threshold_seconds"]
        recovered_ids = services.recover_stuck_executions(
            stuck_threshold_seconds=threshold
        )
        if recovered_ids:
            self.stdout.write(
                self.style.WARNING(
                    f"Recovered {len(recovered_ids)} stuck execution(s): "
                    + ", ".join(recovered_ids)
                )
            )
        else:
            self.stdout.write("No stuck executions found.")

        if options["skip_expired_approvals"]:
            self.stdout.write("Expired approval recovery skipped.")
            return

        recovered_approval_ids = approval_services.recover_expired_approvals(
            batch_size=options["approval_batch_size"],
        )
        if recovered_approval_ids:
            self.stdout.write(
                self.style.WARNING(
                    f"Recovered {len(recovered_approval_ids)} expired approval(s): "
                    + ", ".join(recovered_approval_ids)
                )
            )
        else:
            self.stdout.write("No expired approvals found.")
