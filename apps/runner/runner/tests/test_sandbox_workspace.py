"""Unit tests for workspace path construction and artifact validation."""

from pathlib import Path
from uuid import uuid4

import pytest

from runner.sandbox.base import ArtifactSpec, SandboxLimits, SandboxValidationError
from runner.sandbox.workspace import WorkspaceManager, validate_artifact_path


@pytest.fixture
def mgr(tmp_path):
    return WorkspaceManager(tmp_path)


# ---------------------------------------------------------------------------
# WorkspaceManager.build_workspace_path
# ---------------------------------------------------------------------------


def test_build_workspace_path_is_inside_root(mgr, tmp_path):
    eid, sid = uuid4(), uuid4()
    p = mgr.build_workspace_path(eid, 1, "deploy", sid)
    assert str(p).startswith(str(tmp_path))


def test_build_workspace_path_includes_step_key(mgr):
    eid, sid = uuid4(), uuid4()
    p = mgr.build_workspace_path(eid, 3, "migrate-db", sid)
    assert "migrate-db" in str(p)


def test_build_workspace_path_sanitises_traversal_in_key(mgr, tmp_path):
    eid, sid = uuid4(), uuid4()
    # A step_key containing '..' should be sanitised, not escape the root
    p = mgr.build_workspace_path(eid, 1, "../../../etc", sid)
    assert str(p).startswith(str(tmp_path))


# ---------------------------------------------------------------------------
# validate_artifact_path — absolute path rejection
# ---------------------------------------------------------------------------


def test_absolute_path_rejected(tmp_path):
    with pytest.raises(SandboxValidationError, match="absolute"):
        validate_artifact_path(tmp_path, "/etc/passwd")


def test_absolute_path_rejected_root(tmp_path):
    with pytest.raises(SandboxValidationError, match="absolute"):
        validate_artifact_path(tmp_path, "/")


# ---------------------------------------------------------------------------
# validate_artifact_path — dotdot rejection
# ---------------------------------------------------------------------------


def test_dotdot_in_path_rejected(tmp_path):
    with pytest.raises(SandboxValidationError, match=r"\.\."):
        validate_artifact_path(tmp_path, "../sibling/secret")


def test_dotdot_nested_rejected(tmp_path):
    with pytest.raises(SandboxValidationError, match=r"\.\."):
        validate_artifact_path(tmp_path, "a/b/../../c")


def test_dotdot_deep_traversal_rejected(tmp_path):
    with pytest.raises(SandboxValidationError, match=r"\.\."):
        validate_artifact_path(tmp_path, "a/../../../../etc/passwd")


# ---------------------------------------------------------------------------
# validate_artifact_path — valid paths
# ---------------------------------------------------------------------------


def test_valid_relative_path(tmp_path):
    result = validate_artifact_path(tmp_path, "artifacts/out.txt")
    assert result == (tmp_path / "artifacts" / "out.txt").resolve()


def test_valid_nested_path(tmp_path):
    result = validate_artifact_path(tmp_path, "work/sub/report.json")
    assert result == (tmp_path / "work" / "sub" / "report.json").resolve()


def test_valid_flat_filename(tmp_path):
    result = validate_artifact_path(tmp_path, "result.txt")
    assert result == (tmp_path / "result.txt").resolve()


# ---------------------------------------------------------------------------
# validate_artifact_path — symlink escape rejection
# ---------------------------------------------------------------------------


def test_symlink_escaping_workspace_rejected(tmp_path):
    outside = tmp_path.parent / f"secret_{uuid4().hex}.txt"
    outside.write_text("secret")
    link = tmp_path / "bad_link"
    link.symlink_to(outside)
    with pytest.raises(SandboxValidationError):
        validate_artifact_path(tmp_path, "bad_link")
    outside.unlink()


def test_symlink_to_parent_dir_rejected(tmp_path):
    link = tmp_path / "escape"
    link.symlink_to(tmp_path.parent)
    with pytest.raises(SandboxValidationError):
        validate_artifact_path(tmp_path, "escape/passwd")


def test_symlink_within_workspace_allowed(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("data")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    result = validate_artifact_path(tmp_path, "link.txt")
    assert result == link.resolve()


# ---------------------------------------------------------------------------
# WorkspaceManager.collect_artifacts
# ---------------------------------------------------------------------------


def _limits(**kwargs) -> SandboxLimits:
    defaults = dict(
        timeout_seconds=60,
        stdout_max_bytes=1024,
        stderr_max_bytes=1024,
        artifact_max_bytes=1024 * 1024,
        max_artifacts=10,
    )
    defaults.update(kwargs)
    return SandboxLimits(**defaults)


def test_collect_existing_artifact(tmp_path, mgr):
    f = tmp_path / "out.txt"
    f.write_bytes(b"hello")
    spec = ArtifactSpec(name="output", path="out.txt")
    results = mgr.collect_artifacts(
        _make_workspace(tmp_path), [spec], _limits()
    )
    assert len(results) == 1
    assert results[0].size_bytes == 5
    assert results[0].checksum_sha256  # non-empty


def test_collect_missing_optional_skipped(tmp_path, mgr):
    spec = ArtifactSpec(name="optional", path="missing.txt", required=False)
    results = mgr.collect_artifacts(_make_workspace(tmp_path), [spec], _limits())
    assert results == []


def test_collect_missing_required_raises(tmp_path, mgr):
    spec = ArtifactSpec(name="required", path="missing.txt", required=True)
    with pytest.raises(SandboxValidationError, match="Required artifact"):
        mgr.collect_artifacts(_make_workspace(tmp_path), [spec], _limits())


def test_collect_artifact_exceeds_size_limit(tmp_path, mgr):
    f = tmp_path / "big.bin"
    f.write_bytes(b"x" * 100)
    spec = ArtifactSpec(name="big", path="big.bin")
    with pytest.raises(SandboxValidationError, match="exceeds limit"):
        mgr.collect_artifacts(_make_workspace(tmp_path), [spec], _limits(artifact_max_bytes=10))


def test_collect_artifact_count_limit(tmp_path, mgr):
    files = []
    for i in range(3):
        f = tmp_path / f"f{i}.txt"
        f.write_bytes(b"data")
        files.append(ArtifactSpec(name=f"f{i}", path=f"f{i}.txt"))
    with pytest.raises(SandboxValidationError, match="count exceeds"):
        mgr.collect_artifacts(_make_workspace(tmp_path), files, _limits(max_artifacts=2))


def test_collect_invalid_path_optional_skipped(tmp_path, mgr):
    spec = ArtifactSpec(name="bad", path="../escape.txt", required=False)
    results = mgr.collect_artifacts(_make_workspace(tmp_path), [spec], _limits())
    assert results == []


def test_collect_invalid_path_required_raises(tmp_path, mgr):
    spec = ArtifactSpec(name="bad", path="../escape.txt", required=True)
    with pytest.raises(SandboxValidationError):
        mgr.collect_artifacts(_make_workspace(tmp_path), [spec], _limits())


def _make_workspace(root: Path):
    from runner.sandbox.workspace import Workspace

    return Workspace(
        root=root,
        work=root / "work",
        artifacts=root / "artifacts",
        tmp=root / "tmp",
        meta=root / "meta",
    )
