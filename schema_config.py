"""
Schema tools configuration and path resolution.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_SCHEMA_ARTIFACTS_DIR = Path("./tests/artifacts/mcp/schema_validation")

_workspace: Path | None = None
_state_root_default: Path = Path("./tests/artifacts/mcp/project_state")
_artifacts_dir_default: Path = DEFAULT_SCHEMA_ARTIFACTS_DIR
_schema_tools_bin: Path | None = None


def configure_schema_tools(
    *,
    workspace: Path,
    state_root_default: Path,
    artifacts_dir_default: Path | None = None,
    schema_tools_bin: Path | None = None,
) -> None:
    global _workspace, _state_root_default, _artifacts_dir_default, _schema_tools_bin
    _workspace = workspace
    _state_root_default = state_root_default
    if artifacts_dir_default is not None:
        _artifacts_dir_default = artifacts_dir_default
    _schema_tools_bin = schema_tools_bin


def schema_tools_bin() -> Path | None:
    """Path to schema_tools Rust binary if set and present; else None."""
    p = _schema_tools_bin
    if p is not None and p.exists():
        return p
    return None


def require_workspace() -> Path:
    if _workspace is None:
        raise RuntimeError("schema tools: workspace not configured")
    return _workspace


def state_root(root_dir: str) -> Path:
    if root_dir:
        return Path(root_dir)
    return _state_root_default


def artifacts_dir(artifacts_dir_arg: str) -> Path:
    if artifacts_dir_arg:
        return Path(artifacts_dir_arg)
    return _artifacts_dir_default


def schemas_dir(root: Path) -> Path:
    return root / "schemas"
