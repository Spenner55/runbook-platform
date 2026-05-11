"""Secret redaction for captured subprocess output."""

from __future__ import annotations

_REDACTED = b"[REDACTED]"


class SecretRedactor:
    """Replaces known secret byte sequences in captured output."""

    def __init__(self, secrets: list[str]) -> None:
        # Empty strings cannot be meaningfully redacted and would corrupt all output.
        self._patterns: list[bytes] = [s.encode() for s in secrets if s]

    def redact(self, data: bytes) -> bytes:
        for pattern in self._patterns:
            data = data.replace(pattern, _REDACTED)
        return data

    def redact_str(self, text: str) -> str:
        return self.redact(text.encode()).decode(errors="replace")
