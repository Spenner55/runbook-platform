"""Tests for deterministic hashing helpers."""

import pytest

from apps.changes.services import sha256_canonical_json, canonical_json_bytes


@pytest.mark.django_db
class TestCanonicalHashing:
    def test_dict_key_order_irrelevant(self):
        a = sha256_canonical_json({"b": 1, "a": 2})
        b = sha256_canonical_json({"a": 2, "b": 1})
        assert a == b

    def test_semantic_value_change_alters_hash(self):
        a = sha256_canonical_json({"key": "value1"})
        b = sha256_canonical_json({"key": "value2"})
        assert a != b

    def test_nested_dict_key_order_irrelevant(self):
        a = sha256_canonical_json({"outer": {"z": 1, "a": 2}})
        b = sha256_canonical_json({"outer": {"a": 2, "z": 1}})
        assert a == b

    def test_empty_dict_stable(self):
        h1 = sha256_canonical_json({})
        h2 = sha256_canonical_json({})
        assert h1 == h2

    def test_returns_hex_string(self):
        h = sha256_canonical_json({"x": 1})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_canonical_json_bytes_utf8(self):
        b = canonical_json_bytes({"key": "val"})
        assert isinstance(b, bytes)
        b.decode("utf-8")

    def test_list_order_matters(self):
        a = sha256_canonical_json([1, 2, 3])
        b = sha256_canonical_json([3, 2, 1])
        assert a != b
