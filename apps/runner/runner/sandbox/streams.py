"""Bounded stream capture helpers for subprocess stdout/stderr."""

from __future__ import annotations

from runner.sandbox.base import CapturedStream


def capture_bounded(data: bytes, max_bytes: int) -> CapturedStream:
    """Cap `data` to `max_bytes`, recording original size and truncation state."""
    original = len(data)
    if original <= max_bytes:
        return CapturedStream(
            content=data,
            truncated=False,
            original_size_bytes=original,
            captured_size_bytes=original,
        )
    return CapturedStream(
        content=data[:max_bytes],
        truncated=True,
        original_size_bytes=original,
        captured_size_bytes=max_bytes,
    )


class StreamCapture:
    """Accumulates bytes from a stream up to a configured cap.

    Tracks total bytes seen separately from bytes retained so truncation
    metadata is accurate even when the cap is hit mid-stream.
    """

    def __init__(self, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be > 0")
        self._max = max_bytes
        self._buf = bytearray()
        self._total = 0

    def write(self, chunk: bytes) -> None:
        self._total += len(chunk)
        remaining = self._max - len(self._buf)
        if remaining > 0:
            self._buf.extend(chunk[:remaining])

    def to_captured_stream(self) -> CapturedStream:
        data = bytes(self._buf)
        return CapturedStream(
            content=data,
            truncated=self._total > self._max,
            original_size_bytes=self._total,
            captured_size_bytes=len(data),
        )
