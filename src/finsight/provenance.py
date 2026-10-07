"""Where a result came from: git state of a repository."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_commit(repo: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def git_dirty(repo: Path) -> bool:
    """True if the working tree differs from HEAD, including new untracked files.

    A dirty run is not reproducible from a commit. Ignored paths (data/) don't count.
    """
    try:
        out = subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True)
    except (OSError, subprocess.CalledProcessError):
        return True
    return bool(out.strip())
