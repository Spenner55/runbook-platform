"""Unit tests for bounded stream capture helpers."""

import pytest

from runner.sandbox.streams import StreamCapture, capture_bounded


class TestCaptureBounded:
    def test_under_limit(self):
        cs = capture_bounded(b"hello", 100)
        assert cs.content == b"hello"
        assert not cs.truncated
        assert cs.original_size_bytes == 5
        assert cs.captured_size_bytes == 5

    def test_at_limit(self):
        data = b"a" * 10
        cs = capture_bounded(data, 10)
        assert not cs.truncated
        assert cs.captured_size_bytes == 10
        assert cs.original_size_bytes == 10

    def test_over_limit(self):
        data = b"abcde"
        cs = capture_bounded(data, 3)
        assert cs.content == b"abc"
        assert cs.truncated
        assert cs.original_size_bytes == 5
        assert cs.captured_size_bytes == 3

    def test_empty_data(self):
        cs = capture_bounded(b"", 10)
        assert cs.content == b""
        assert not cs.truncated
        assert cs.original_size_bytes == 0

    def test_cap_of_one(self):
        cs = capture_bounded(b"hello", 1)
        assert cs.content == b"h"
        assert cs.truncated
        assert cs.original_size_bytes == 5
        assert cs.captured_size_bytes == 1


class TestStreamCapture:
    def test_under_limit_single_write(self):
        sc = StreamCapture(1024)
        sc.write(b"hello world")
        result = sc.to_captured_stream()
        assert result.content == b"hello world"
        assert not result.truncated
        assert result.original_size_bytes == 11
        assert result.captured_size_bytes == 11

    def test_multi_chunk_under_limit(self):
        sc = StreamCapture(1024)
        sc.write(b"hello ")
        sc.write(b"world")
        result = sc.to_captured_stream()
        assert result.content == b"hello world"
        assert not result.truncated

    def test_truncates_single_chunk(self):
        sc = StreamCapture(5)
        sc.write(b"hello world")
        result = sc.to_captured_stream()
        assert result.content == b"hello"
        assert result.truncated
        assert result.original_size_bytes == 11
        assert result.captured_size_bytes == 5

    def test_truncates_across_chunks(self):
        sc = StreamCapture(4)
        sc.write(b"ab")
        sc.write(b"cd")
        sc.write(b"ef")  # fills buffer; ef is dropped
        result = sc.to_captured_stream()
        assert result.content == b"abcd"
        assert result.truncated
        assert result.original_size_bytes == 6

    def test_partial_fill_on_overflow(self):
        sc = StreamCapture(5)
        sc.write(b"abc")   # 3 bytes
        sc.write(b"defg")  # 4 bytes; only 2 fit
        result = sc.to_captured_stream()
        assert result.content == b"abcde"
        assert result.truncated
        assert result.original_size_bytes == 7

    def test_empty_stream(self):
        sc = StreamCapture(100)
        result = sc.to_captured_stream()
        assert result.content == b""
        assert not result.truncated
        assert result.original_size_bytes == 0

    def test_invalid_max_raises(self):
        with pytest.raises(ValueError):
            StreamCapture(0)

    def test_negative_max_raises(self):
        with pytest.raises(ValueError):
            StreamCapture(-1)

    def test_write_empty_chunk(self):
        sc = StreamCapture(10)
        sc.write(b"hi")
        sc.write(b"")
        result = sc.to_captured_stream()
        assert result.content == b"hi"
        assert result.original_size_bytes == 2
