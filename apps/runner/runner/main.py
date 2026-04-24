"""Runner entry point — load config, wire components, start poll loop."""

from __future__ import annotations

import httpx

from runner.client import ApiClient
from runner.executor import Executor
from runner.log_streamer import LogStreamer, configure_logging
from runner.poller import Poller
from runner.schemas import RunnerSettings


def main() -> None:
    settings = RunnerSettings.from_env()

    base_logger = configure_logging(
        level=settings.log_level,
        runner_id=settings.runner_id,
        runner_version=settings.runner_version,
    )
    log = LogStreamer(
        base_logger=base_logger,
        runner_id=settings.runner_id,
        runner_version=settings.runner_version,
    )

    log.runner_started()

    timeout = httpx.Timeout(10.0)
    with httpx.Client(timeout=timeout) as http_client:
        api_client = ApiClient(
            base_url=settings.api_base_url,
            runner_id=settings.runner_id,
            runner_version=settings.runner_version,
            http_client=http_client,
        )
        executor = Executor(client=api_client)
        poller = Poller(client=api_client, executor=executor)

        poller.run_forever()


if __name__ == "__main__":
    main()
