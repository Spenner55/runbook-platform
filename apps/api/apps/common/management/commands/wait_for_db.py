import time

from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Block until the database is available."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Maximum seconds to wait (default: 30).",
        )

    def handle(self, *args, **options):
        timeout = options["timeout"]
        self.stdout.write("Waiting for database...")
        elapsed = 0
        while elapsed < timeout:
            try:
                connections["default"].ensure_connection()
                self.stdout.write(self.style.SUCCESS("Database ready."))
                return
            except OperationalError:
                time.sleep(1)
                elapsed += 1
        raise SystemExit(f"Database not ready after {timeout}s.")
