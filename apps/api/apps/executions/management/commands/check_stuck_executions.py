from django.core.management.base import BaseCommand

from apps.executions import services


class Command(BaseCommand):
    help = "Recover executions stuck in claimed/running due to stale heartbeats."

    def add_arguments(self, parser):
        parser.add_argument(
            "--threshold-seconds",
            type=int,
            default=300,
            dest="threshold_seconds",
            help="Seconds since last heartbeat before an execution is considered stuck (default: 300).",
        )

    def handle(self, *args, **options):
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
