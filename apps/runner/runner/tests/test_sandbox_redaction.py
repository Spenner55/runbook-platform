"""Unit tests for SecretRedactor."""

from runner.sandbox.redaction import SecretRedactor


def test_no_secrets_passthrough():
    r = SecretRedactor([])
    assert r.redact(b"hello world") == b"hello world"


def test_single_secret_redacted():
    r = SecretRedactor(["mysecret"])
    assert r.redact(b"prefix mysecret suffix") == b"prefix [REDACTED] suffix"


def test_multiple_occurrences():
    r = SecretRedactor(["tok"])
    assert r.redact(b"tok tok tok") == b"[REDACTED] [REDACTED] [REDACTED]"


def test_multiple_secrets():
    r = SecretRedactor(["alpha", "beta"])
    assert r.redact(b"alpha and beta") == b"[REDACTED] and [REDACTED]"


def test_empty_secret_ignored():
    r = SecretRedactor(["", "real"])
    assert r.redact(b"real data") == b"[REDACTED] data"


def test_no_match_passthrough():
    r = SecretRedactor(["secret"])
    assert r.redact(b"nothing to see here") == b"nothing to see here"


def test_binary_safe():
    r = SecretRedactor(["abc"])
    data = b"\x00abc\xff"
    assert r.redact(data) == b"\x00[REDACTED]\xff"


def test_redact_str():
    r = SecretRedactor(["pw"])
    assert r.redact_str("pw is here") == "[REDACTED] is here"


def test_redact_str_no_match():
    r = SecretRedactor(["pw"])
    assert r.redact_str("no secrets") == "no secrets"
