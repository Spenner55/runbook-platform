"""Tests for EvidenceRedactionPolicy service behavior.

Hard rules enforced here:
- Redaction never mutates canonical bundle bytes or DB rows.
- Redacted export omits configured sensitive fields.
- NDJSON redaction preserves event order.
"""
import json

from apps.evidence.services import (
    _apply_json_pointer_redaction,
    _apply_ndjson_field_redaction,
    _apply_redaction_policy,
    canonical_json_bytes,
    compute_redaction_policy_sha256,
    sha256_hexdigest,
)

# ---------------------------------------------------------------------------
# compute_redaction_policy_sha256
# ---------------------------------------------------------------------------


def test_redaction_policy_sha256_is_canonical():
    rules_a = [{"action": "omit_path", "id": "r1", "path": "audit/audit_trail.ndjson"}]
    rules_b = [{"id": "r1", "action": "omit_path", "path": "audit/audit_trail.ndjson"}]
    assert compute_redaction_policy_sha256(rules_a) == compute_redaction_policy_sha256(rules_b)


def test_redaction_policy_sha256_differs_for_different_rules():
    rules_a = [{"action": "omit_path", "id": "r1", "path": "audit/audit_trail.ndjson"}]
    rules_b = [{"action": "omit_path", "id": "r2", "path": "change/change_record.json"}]
    assert compute_redaction_policy_sha256(rules_a) != compute_redaction_policy_sha256(rules_b)


# ---------------------------------------------------------------------------
# _apply_json_pointer_redaction
# ---------------------------------------------------------------------------


def test_json_pointer_redact_top_level_key():
    data = {"actor_label": "admin@example.com", "event_type": "login"}
    count = _apply_json_pointer_redaction(data, "/actor_label")
    assert count == 1
    assert data["actor_label"] == "[REDACTED]"
    assert data["event_type"] == "login"


def test_json_pointer_redact_nested_key():
    data = {"items": [{"id": "1", "secret": "tok"}]}
    count = _apply_json_pointer_redaction(data, "/items/0/secret")
    assert count == 1
    assert data["items"][0]["secret"] == "[REDACTED]"
    assert data["items"][0]["id"] == "1"


def test_json_pointer_missing_path_returns_zero():
    data = {"a": 1}
    assert _apply_json_pointer_redaction(data, "/b/c") == 0
    assert data == {"a": 1}


def test_json_pointer_empty_pointer_returns_zero():
    data = {"a": 1}
    assert _apply_json_pointer_redaction(data, "") == 0


def test_json_pointer_tilde_escaping():
    data = {"a/b": {"c~d": "sensitive"}}
    count = _apply_json_pointer_redaction(data, "/a~1b/c~0d")
    assert count == 1
    assert data["a/b"]["c~d"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# _apply_ndjson_field_redaction
# ---------------------------------------------------------------------------


def test_ndjson_field_redaction_preserves_order():
    events = [
        {"id": "1", "actor_label": "alice", "event_type": "login"},
        {"id": "2", "actor_label": "bob", "event_type": "logout"},
        {"id": "3", "actor_label": "carol", "event_type": "update"},
    ]
    raw = "".join(json.dumps(e) + "\n" for e in events)
    count, result_bytes = _apply_ndjson_field_redaction(raw, "actor_label")
    assert count == 3
    lines = result_bytes.decode("utf-8").rstrip("\n").split("\n")
    assert len(lines) == 3
    for i, line in enumerate(lines):
        parsed = json.loads(line)
        assert parsed["actor_label"] == "[REDACTED]"
        assert parsed["id"] == str(i + 1)
        assert parsed["event_type"] == events[i]["event_type"]


def test_ndjson_field_redaction_missing_field_not_counted():
    events = [
        {"id": "1", "actor_label": "alice"},
        {"id": "2"},
    ]
    raw = "".join(json.dumps(e) + "\n" for e in events)
    count, _ = _apply_ndjson_field_redaction(raw, "actor_label")
    assert count == 1


def test_ndjson_field_redaction_preserves_trailing_newline():
    events = [{"id": "1", "actor_label": "x"}]
    raw = "".join(json.dumps(e) + "\n" for e in events)
    count, result_bytes = _apply_ndjson_field_redaction(raw, "actor_label")
    assert count == 1
    assert result_bytes.endswith(b"\n")


def test_ndjson_empty_returns_zero_bytes():
    count, result = _apply_ndjson_field_redaction("", "field")
    assert count == 0
    assert result == b""


# ---------------------------------------------------------------------------
# _apply_redaction_policy — no policy (unredacted)
# ---------------------------------------------------------------------------


def test_no_policy_returns_copy_unchanged():
    source = {
        "manifest.json": b"{}",
        "change/change_record.json": b'{"id": "abc"}',
        "audit/audit_trail.ndjson": b'{"id":"1"}\n',
    }
    entries, summary = _apply_redaction_policy(source, policy=None)
    assert entries == source
    assert entries is not source  # is a copy
    assert summary["redacted"] is False
    assert summary["policy_id"] is None
    assert summary["rules_applied"] == 0


def test_unredacted_copy_does_not_mutate_source():
    source = {
        "change/change_record.json": b'{"id": "abc"}',
    }
    original_bytes = source["change/change_record.json"]
    entries, _ = _apply_redaction_policy(source, policy=None)
    entries["change/change_record.json"] = b"mutated"
    assert source["change/change_record.json"] == original_bytes


# ---------------------------------------------------------------------------
# _apply_redaction_policy — omit_path
# ---------------------------------------------------------------------------


class _FakePolicy:
    def __init__(self, rules, policy_id="policy-1", sha256="a" * 64):
        self.rules = rules
        self.id = policy_id
        self.rules_sha256 = sha256


def test_omit_path_removes_entry():
    source = {
        "change/change_record.json": b'{"id":"a"}',
        "audit/audit_trail.ndjson": b'{"id":"1"}\n',
    }
    policy = _FakePolicy(
        [{"action": "omit_path", "id": "r1", "path": "audit/audit_trail.ndjson"}]
    )
    entries, summary = _apply_redaction_policy(source, policy=policy)
    assert "audit/audit_trail.ndjson" not in entries
    assert "change/change_record.json" in entries
    assert len(summary["omitted_paths"]) == 1
    assert summary["redacted"] is True


def test_omit_path_cannot_remove_manifest():
    source = {
        "manifest.json": b"{}",
        "checksums.sha256": b"...",
    }
    policy = _FakePolicy(
        [{"action": "omit_path", "id": "r1", "path": "manifest.json"}]
    )
    entries, summary = _apply_redaction_policy(source, policy=policy)
    assert "manifest.json" in entries
    assert len(summary["omitted_paths"]) == 0


# ---------------------------------------------------------------------------
# _apply_redaction_policy — redact_json_pointer
# ---------------------------------------------------------------------------


def test_redact_json_pointer_in_json_file():
    payload = {"schema_version": "1", "items": [{"actor_label": "alice", "event_type": "x"}]}
    source = {
        "change/change_record.json": canonical_json_bytes(payload),
    }
    policy = _FakePolicy(
        [
            {
                "action": "redact_json_pointer",
                "id": "r1",
                "path": "change/change_record.json",
                "pointer": "/items/0/actor_label",
            }
        ]
    )
    entries, summary = _apply_redaction_policy(source, policy=policy)
    result = json.loads(entries["change/change_record.json"].decode("utf-8"))
    assert result["items"][0]["actor_label"] == "[REDACTED]"
    assert result["items"][0]["event_type"] == "x"
    assert len(summary["transformed_paths"]) == 1


def test_redact_json_pointer_does_not_mutate_source_bytes():
    payload = {"actor": "alice"}
    source_bytes = canonical_json_bytes(payload)
    source = {"change/change_record.json": source_bytes}
    policy = _FakePolicy(
        [{"action": "redact_json_pointer", "id": "r1", "path": "change/change_record.json", "pointer": "/actor"}]
    )
    _apply_redaction_policy(source, policy=policy)
    assert source["change/change_record.json"] == source_bytes


# ---------------------------------------------------------------------------
# _apply_redaction_policy — redact_ndjson_field
# ---------------------------------------------------------------------------


def test_redact_ndjson_field_omits_sensitive_field():
    events = [
        {"id": "1", "actor_label": "alice", "event_type": "change.closed"},
        {"id": "2", "actor_label": "bob", "event_type": "approval.granted"},
    ]
    raw = "".join(json.dumps(e) + "\n" for e in events)
    source = {"audit/audit_trail.ndjson": raw.encode("utf-8")}
    policy = _FakePolicy(
        [
            {
                "action": "redact_ndjson_field",
                "id": "r1",
                "path": "audit/audit_trail.ndjson",
                "field": "actor_label",
            }
        ]
    )
    entries, summary = _apply_redaction_policy(source, policy=policy)
    result_bytes = entries["audit/audit_trail.ndjson"]
    lines = result_bytes.decode("utf-8").rstrip("\n").split("\n")
    assert len(lines) == 2
    for line in lines:
        parsed = json.loads(line)
        assert parsed["actor_label"] == "[REDACTED]"
    assert summary["redaction_counts"].get("redact_ndjson_field", 0) == 2


def test_redact_ndjson_field_preserves_event_order():
    events = [{"id": str(i), "actor_label": f"user{i}", "seq": i} for i in range(5)]
    raw = "".join(json.dumps(e) + "\n" for e in events)
    source = {"audit/audit_trail.ndjson": raw.encode("utf-8")}
    policy = _FakePolicy(
        [{"action": "redact_ndjson_field", "id": "r1", "path": "audit/audit_trail.ndjson", "field": "actor_label"}]
    )
    entries, _ = _apply_redaction_policy(source, policy=policy)
    lines = entries["audit/audit_trail.ndjson"].decode("utf-8").rstrip("\n").split("\n")
    for i, line in enumerate(lines):
        parsed = json.loads(line)
        assert parsed["seq"] == i


# ---------------------------------------------------------------------------
# _apply_redaction_policy — artifact_metadata_only
# ---------------------------------------------------------------------------


def test_artifact_metadata_only_removes_artifact_file_bytes():
    source = {
        "artifacts/index.json": b'{"items":[]}',
        "artifacts/files/abc123/report.json": b"binary-data",
        "artifacts/files/def456/log.txt": b"log content",
    }
    policy = _FakePolicy([{"action": "artifact_metadata_only", "id": "r1"}])
    entries, summary = _apply_redaction_policy(source, policy=policy)
    assert "artifacts/index.json" in entries
    assert "artifacts/files/abc123/report.json" not in entries
    assert "artifacts/files/def456/log.txt" not in entries
    assert summary["redaction_counts"].get("artifact_metadata_only", 0) == 2


# ---------------------------------------------------------------------------
# _apply_redaction_policy — replace_file_with_notice
# ---------------------------------------------------------------------------


def test_replace_file_with_notice_replaces_bytes():
    original = b"original content"
    original_sha256 = sha256_hexdigest(original)
    source = {"change/change_record.json": original}
    policy = _FakePolicy(
        [{"action": "replace_file_with_notice", "id": "notice-r1", "path": "change/change_record.json"}]
    )
    entries, summary = _apply_redaction_policy(source, policy=policy)
    notice = entries["change/change_record.json"]
    assert b"[REDACTED]" not in notice
    assert original_sha256.encode() in notice
    assert b"notice-r1" in notice
    assert b"change/change_record.json" in notice
    assert len(summary["transformed_paths"]) == 1


# ---------------------------------------------------------------------------
# Canonical bundle is not mutated by redaction
# ---------------------------------------------------------------------------


def test_redaction_does_not_mutate_canonical_bundle_bytes():
    """Source entries dict and its byte values must not change after redaction."""
    events = [{"id": "1", "actor_label": "alice", "event": "x"}]
    ndjson = "".join(json.dumps(e) + "\n" for e in events)
    payload = {"actor": "alice", "secret": "tok"}
    source = {
        "change/change_record.json": canonical_json_bytes(payload),
        "audit/audit_trail.ndjson": ndjson.encode("utf-8"),
        "artifacts/files/abc/report.json": b"binary",
    }
    original_snapshot = {k: v for k, v in source.items()}

    policy = _FakePolicy(
        [
            {"action": "redact_json_pointer", "id": "r1", "path": "change/change_record.json", "pointer": "/actor"},
            {"action": "redact_ndjson_field", "id": "r2", "path": "audit/audit_trail.ndjson", "field": "actor_label"},
            {"action": "artifact_metadata_only", "id": "r3"},
        ]
    )
    _apply_redaction_policy(source, policy=policy)

    for path, original_bytes in original_snapshot.items():
        assert source[path] == original_bytes, f"Canonical bytes mutated at {path}"
