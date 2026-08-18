"""Project paths and reproducibility helpers.

All source modules resolve repository resources from this file instead of the
current working directory.  A run directory remains explicit and may be
outside the repository.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
RUNS_DIR = WORKSPACE_DIR / "runs"
PESTPP_BIN_DIR = PROJECT_ROOT / "pestpp-5.2.16-win" / "bin"


def project_path(*parts: str | os.PathLike[str]) -> Path:
    """Return an absolute path below the repository root."""
    return PROJECT_ROOT.joinpath(*map(Path, parts))


def resolve_path(
    value: str | os.PathLike[str],
    *,
    bases: Iterable[str | os.PathLike[str]] = (),
    must_exist: bool = True,
) -> Path:
    """Resolve a user path deterministically.

    Relative paths are tried against the supplied bases and then the project
    root.  They are never interpreted relative to an arbitrary source module.
    """
    raw = Path(value).expanduser()
    candidates = [raw] if raw.is_absolute() else [Path(b) / raw for b in bases]
    if not raw.is_absolute():
        candidates.append(PROJECT_ROOT / raw)
    for candidate in candidates:
        candidate = candidate.resolve()
        if not must_exist or candidate.exists():
            return candidate
    rendered = ", ".join(str(p.resolve()) for p in candidates)
    raise FileNotFoundError(f"Cannot resolve path {value!s}; checked: {rendered}")


def sha256_file(path: str | os.PathLike[str]) -> str:
    """Return the SHA-256 digest of a file without loading it into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_metadata() -> dict[str, str | bool]:
    """Return commit and dirty-state metadata; never hide command failure."""
    def run(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    return {
        "git_commit": run("rev-parse", "HEAD"),
        "git_branch": run("branch", "--show-current"),
        "git_dirty": bool(run("status", "--porcelain")),
    }
