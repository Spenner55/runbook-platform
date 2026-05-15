"""Action handler registry mapping (type, version) tuples to handler instances."""

from __future__ import annotations

from runner.actions.base import ActionHandler


class ActionRegistry:
    def __init__(self) -> None:
        self._registry: dict[tuple[str, str], ActionHandler] = {}

    def register(self, action_type: str, version: str, handler: ActionHandler) -> None:
        self._registry[(action_type, version)] = handler

    _DEFAULT_VERSION = "pilot.v1"

    def lookup(self, action_type: str, version: str) -> ActionHandler | None:
        handler = self._registry.get((action_type, version))
        if handler is None and version != self._DEFAULT_VERSION:
            handler = self._registry.get((action_type, self._DEFAULT_VERSION))
        return handler


def _build_registry() -> ActionRegistry:
    from runner.actions.approval_gate import ApprovalGateHandler
    from runner.actions.artifact_assertion import ArtifactAssertionHandler
    from runner.actions.http_request import HttpRequestHandler
    from runner.actions.manual_task import ManualTaskHandler
    from runner.actions.shell_command import ShellCommandHandler

    registry = ActionRegistry()
    registry.register("manual_task", "pilot.v1", ManualTaskHandler())
    registry.register("approval_gate", "pilot.v1", ApprovalGateHandler())
    registry.register("shell_command", "pilot.v1", ShellCommandHandler())
    registry.register("http_request", "pilot.v1", HttpRequestHandler())
    registry.register("artifact_assertion", "pilot.v1", ArtifactAssertionHandler())
    return registry


ACTION_REGISTRY: ActionRegistry = _build_registry()
