"""Local runner state — persists canonical runner_id and bearer token across restarts."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_VERSION = 1


@dataclass
class RunnerState:
    runner_id: str = ""
    runner_bearer_token: str = ""

    @property
    def is_registered(self) -> bool:
        return bool(self.runner_id and self.runner_bearer_token)

    def save(self, path: Path) -> None:
        """Write state to disk atomically; restrict file to owner-read-only."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "version": _STATE_VERSION,
                    "runner_id": self.runner_id,
                    "runner_bearer_token": self.runner_bearer_token,
                },
                indent=2,
            )
        )
        os.chmod(tmp, 0o600)
        tmp.replace(path)
        logger.debug("runner_state_saved path=%s runner_id=%s", path, self.runner_id)

    @classmethod
    def load(cls, path: Path) -> RunnerState:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
            return cls(
                runner_id=data.get("runner_id", ""),
                runner_bearer_token=data.get("runner_bearer_token", ""),
            )
        except Exception as exc:
            logger.warning(
                "runner_state_load_failed path=%s error=%s — starting unregistered",
                path,
                exc,
            )
            return cls()
