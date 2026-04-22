"""Runner entry point — load config, wire components, start poll loop."""

from __future__ import annotations

import logging
import os
import sys

from runner.client import ApiClient
from runner.executor import Executor
from runner.poller import Poller


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


def main() -> None:
    _configure_logging()
    logger = logging.getLogger(__name__)

    api_base_url = os.environ.get("API_BASE_URL", "http://api:8000")
    runner_id = os.environ.get("RUNNER_REGISTRATION_TOKEN", "default-runner")

    logger.info("Runner starting — api=%s runner_id=%s", api_base_url, runner_id)

    client = ApiClient(base_url=api_base_url, runner_id=runner_id)
    executor = Executor(client=client)
    poller = Poller(client=client, executor=executor)

    try:
        poller.run_forever()
    finally:
        client.close()
        logger.info("Runner stopped")


if __name__ == "__main__":
    main()
