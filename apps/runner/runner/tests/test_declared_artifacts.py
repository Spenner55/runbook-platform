"""Tests for declared artifact upload support in ArtifactUploader."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from runner.artifact_uploader import ArtifactUploader
from runner.schemas import ArtifactDeclaration, ArtifactUploadResponse

EXECUTION_ID = uuid4()
STEP_ID = uuid4()
CLAIM_TOKEN = uuid4()


def _make_response(kind="file", name="out.txt"):
    return ArtifactUploadResponse(
        id=uuid4(),
        execution_id=EXECUTION_ID,
        step_id=STEP_ID,
        kind=kind,
        name=name,
        mime_type="text/plain",
        size_bytes=5,
        checksum_sha256="a" * 64,
        uploaded_by_runner_id="runner-test",
    )


def _make_client(return_value=None):
    client = MagicMock()
    client.upload_artifact.return_value = return_value or _make_response()
    return client


def _make_declaration(
    key: str = "my_artifact",
    path: str = "artifacts/out.txt",
    required: bool = False,
    name: str = "",
    kind: str = "file",
) -> ArtifactDeclaration:
    return ArtifactDeclaration(
        key=key,
        name=name,
        path=path,
        kind=kind,
        required=required,
    )


# ---------------------------------------------------------------------------
# Declared stdout/stderr metadata
# ---------------------------------------------------------------------------


def test_upload_stdout_includes_declaration_metadata():
    client = _make_client(_make_response(kind="stdout", name="stdout.txt"))
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)

    uploader.upload_stdout(
        STEP_ID,
        b"hello",
        declaration_key="stdout_capture",
        action_type="shell_command",
        action_version="pilot.v1",
        step_key="step-1",
    )

    metadata = client.upload_artifact.call_args.kwargs["metadata"]
    assert metadata["declaration_key"] == "stdout_capture"
    assert metadata["action_type"] == "shell_command"
    assert metadata["action_version"] == "pilot.v1"
    assert metadata["step_key"] == "step-1"


def test_upload_stderr_includes_declaration_metadata():
    client = _make_client(_make_response(kind="stderr", name="stderr.txt"))
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)

    uploader.upload_stderr(
        STEP_ID,
        b"error",
        declaration_key="stderr_capture",
        action_type="shell_command",
        action_version="pilot.v1",
        step_key="step-2",
    )

    metadata = client.upload_artifact.call_args.kwargs["metadata"]
    assert metadata["declaration_key"] == "stderr_capture"
    assert metadata["action_type"] == "shell_command"
    assert metadata["action_version"] == "pilot.v1"
    assert metadata["step_key"] == "step-2"


def test_upload_stdout_omits_empty_declaration_fields():
    client = _make_client(_make_response(kind="stdout", name="stdout.txt"))
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)

    uploader.upload_stdout(STEP_ID, b"data")

    metadata = client.upload_artifact.call_args.kwargs["metadata"]
    assert "declaration_key" not in metadata
    assert "action_type" not in metadata
    assert "action_version" not in metadata
    assert "step_key" not in metadata
    assert "dry_run" not in metadata


def test_upload_stdout_dry_run_flag_included():
    client = _make_client(_make_response(kind="stdout", name="stdout.txt"))
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)

    uploader.upload_stdout(STEP_ID, b"data", dry_run=True)

    metadata = client.upload_artifact.call_args.kwargs["metadata"]
    assert metadata["dry_run"] is True


# ---------------------------------------------------------------------------
# upload_declared_file: path safety
# ---------------------------------------------------------------------------


def test_path_traversal_double_dot_rejected(tmp_path):
    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    decl = _make_declaration(path="../etc/passwd", required=True)

    result, failure_kind = uploader.upload_declared_file(STEP_ID, tmp_path, decl)

    assert result is None
    assert failure_kind == "action_input_invalid"
    client.upload_artifact.assert_not_called()


def test_absolute_path_rejected(tmp_path):
    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    decl = _make_declaration(path="/etc/passwd", required=True)

    result, failure_kind = uploader.upload_declared_file(STEP_ID, tmp_path, decl)

    assert result is None
    assert failure_kind == "action_input_invalid"
    client.upload_artifact.assert_not_called()


def test_path_traversal_via_nested_double_dot_rejected(tmp_path):
    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    decl = _make_declaration(path="subdir/../../etc/shadow", required=True)

    result, failure_kind = uploader.upload_declared_file(STEP_ID, tmp_path, decl)

    assert result is None
    assert failure_kind == "action_input_invalid"
    client.upload_artifact.assert_not_called()


# ---------------------------------------------------------------------------
# upload_declared_file: required vs optional missing
# ---------------------------------------------------------------------------


def test_required_file_missing_fails(tmp_path):
    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    decl = _make_declaration(path="artifacts/missing.txt", required=True)

    result, failure_kind = uploader.upload_declared_file(STEP_ID, tmp_path, decl)

    assert result is None
    assert failure_kind == "required_artifact_missing"
    client.upload_artifact.assert_not_called()


def test_optional_file_missing_does_not_fail(tmp_path):
    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    decl = _make_declaration(path="artifacts/optional.txt", required=False)

    result, failure_kind = uploader.upload_declared_file(STEP_ID, tmp_path, decl)

    assert result is None
    assert failure_kind == ""
    client.upload_artifact.assert_not_called()


def test_required_file_present_succeeds(tmp_path):
    artifact_file = tmp_path / "artifacts" / "out.txt"
    artifact_file.parent.mkdir(parents=True)
    artifact_file.write_bytes(b"result data")

    client = _make_client(_make_response(kind="file", name="out.txt"))
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    decl = _make_declaration(
        key="my_report", path="artifacts/out.txt", required=True, name="out.txt"
    )

    result, failure_kind = uploader.upload_declared_file(STEP_ID, tmp_path, decl)

    assert result is not None
    assert failure_kind == ""
    client.upload_artifact.assert_called_once()


# ---------------------------------------------------------------------------
# upload_declared_file: declaration metadata in upload
# ---------------------------------------------------------------------------


def test_declared_file_metadata_includes_declaration_key(tmp_path):
    artifact_file = tmp_path / "out.csv"
    artifact_file.write_bytes(b"col1,col2\n1,2\n")

    client = _make_client(_make_response(kind="report", name="report"))
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    decl = _make_declaration(key="csv_report", path="out.csv", kind="report")

    uploader.upload_declared_file(
        STEP_ID,
        tmp_path,
        decl,
        action_type="shell_command",
        action_version="pilot.v1",
        step_key="generate-report",
    )

    metadata = client.upload_artifact.call_args.kwargs["metadata"]
    assert metadata["declaration_key"] == "csv_report"
    assert metadata["action_type"] == "shell_command"
    assert metadata["action_version"] == "pilot.v1"
    assert metadata["step_key"] == "generate-report"
    assert metadata["artifact_source_path"] == "out.csv"


def test_declared_file_dry_run_metadata(tmp_path):
    artifact_file = tmp_path / "result.txt"
    artifact_file.write_bytes(b"ok")

    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    decl = _make_declaration(path="result.txt")

    uploader.upload_declared_file(STEP_ID, tmp_path, decl, dry_run=True)

    metadata = client.upload_artifact.call_args.kwargs["metadata"]
    assert metadata["dry_run"] is True


def test_declared_file_no_path_required_fails(tmp_path):
    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    decl = _make_declaration(path="", required=True)

    result, failure_kind = uploader.upload_declared_file(STEP_ID, tmp_path, decl)

    assert result is None
    assert failure_kind == "required_artifact_missing"


def test_declared_file_no_path_optional_skips(tmp_path):
    client = _make_client()
    uploader = ArtifactUploader(client, EXECUTION_ID, CLAIM_TOKEN)
    decl = _make_declaration(path="", required=False)

    result, failure_kind = uploader.upload_declared_file(STEP_ID, tmp_path, decl)

    assert result is None
    assert failure_kind == ""
