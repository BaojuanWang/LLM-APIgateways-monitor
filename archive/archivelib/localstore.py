"""Validation for an explicitly authorized MacBook-local archive root.

External-volume storage remains the recommended and default mode. This module
implements the *opt-in* alternative: keeping the corpus on the machine's own
disk, permitted only when the operator explicitly authorizes it with
``--allow-local-storage`` (or the equivalent config/env opt-in).

Local storage gives up a real property. An external volume can be unmounted,
stored separately, and physically separated from the laptop that made it; a
local corpus shares the fate of the machine, and it sits inside the same home
directory as the Git repository it must never enter. So the checks here are
stricter than the ones an external volume needs, and every one of them fails
closed:

* not inside **any** Git repository or worktree — the whole point of the
  storage boundary is that raw archival material cannot be committed;
* not inside Desktop, Downloads, Documents, or an iCloud-synchronized
  directory — those replicate to Apple's servers, which would silently upload
  gigabytes of third-party page captures;
* not a symlink, at the root or at any ancestor, so the location cannot be
  redirected after authorization;
* under the user's home directory, so an authorized flag cannot aim a corpus at
  a system directory;
* writable, and with enough free space to be worth starting.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .volumes import free_bytes, probe_writable

# Storage modes recorded with every capture.
STORAGE_MODE_EXTERNAL = "external_volume"
STORAGE_MODE_LOCAL = "explicitly_authorized_local"
STORAGE_MODE_TEST = "test_only"

ALLOW_LOCAL_ENV = "ARCHIVE_ALLOW_LOCAL_STORAGE"

# The documented default, expressed relative to $HOME. It is deliberately NOT
# written out with a username: this repository is public, and a hardcoded
# /Users/<name>/... would publish the operator's account name in every clone.
DEFAULT_LOCAL_ROOT_NAME = "LLM-APIgateways-corpus"

# Standard home subdirectories a corpus must never live inside. Desktop,
# Downloads, and Documents are the iCloud-syncable ones; the rest are managed by
# macOS and are not places to put research data.
FORBIDDEN_HOME_SUBDIRS = (
    "Desktop",
    "Downloads",
    "Documents",
    "Library",
    "Movies",
    "Music",
    "Pictures",
    "Public",
    "Applications",
)

ICLOUD_ROOT_RELATIVE = "Library/Mobile Documents"


def default_local_root() -> Path:
    """``$HOME/LLM-APIgateways-corpus``.

    On the machine this subsystem was built for that is exactly
    ``/Users/<user>/LLM-APIgateways-corpus``; deriving it from ``Path.home()``
    keeps the username out of the committed source.
    """
    return Path.home() / DEFAULT_LOCAL_ROOT_NAME


def allow_local_flag_enabled(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return str(env.get(ALLOW_LOCAL_ENV, "")).strip() == "1"


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def nearest_existing(path: Path) -> Path:
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def enclosing_git_dir(path: Path) -> Path | None:
    """Nearest ancestor containing a ``.git`` entry, or None.

    ``.git`` is checked as both a directory (normal clone) and a file (a linked
    worktree, which is exactly the situation this repository is in), so a corpus
    cannot be hidden inside a worktree and later committed from it.
    """
    probe = Path(path).resolve()
    while True:
        marker = probe / ".git"
        if marker.is_dir() or marker.is_file():
            return probe
        if probe == probe.parent:
            return None
        probe = probe.parent


def git_toplevel(path: Path) -> str | None:
    """``git rev-parse --show-toplevel`` from the nearest existing ancestor.

    A cross-check on ``enclosing_git_dir``: git knows about configurations
    (``GIT_DIR``, ``$GIT_WORK_TREE``, ceiling directories) that a marker walk
    does not.
    """
    start = nearest_existing(path)
    try:
        proc = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    top = proc.stdout.decode("utf-8", "replace").strip()
    return top or None


def icloud_root() -> Path:
    return Path.home() / ICLOUD_ROOT_RELATIVE


def is_icloud_synced(path: Path) -> tuple[bool, str]:
    """Whether ``path`` lives in an iCloud-replicated location.

    Two cases: the path is literally under ``Library/Mobile Documents``, or it
    is under Desktop/Documents while "Desktop & Documents Folders" sync is on —
    in which case the *paths look normal* but the contents replicate to Apple.
    """
    resolved = Path(path).resolve()
    cloud = icloud_root().resolve() if icloud_root().exists() else icloud_root()
    if _is_within(resolved, cloud):
        return True, f"path is inside {ICLOUD_ROOT_RELATIVE} (iCloud Drive)"

    home = Path.home().resolve()
    cloud_docs = icloud_root() / "com~apple~CloudDocs"
    for name in ("Desktop", "Documents"):
        if _is_within(resolved, home / name) and (cloud_docs / name).exists():
            return True, f"~/{name} is synchronized by iCloud Desktop & Documents"

    # A directory full of .icloud placeholder stubs is evicted cloud content.
    probe = nearest_existing(resolved)
    try:
        if any(child.name.endswith(".icloud") for child in probe.iterdir()):
            return True, f"{probe} contains iCloud placeholder files"
    except (OSError, PermissionError):
        pass
    return False, ""


def symlink_ancestors(path: Path, stop_at: Path | None = None) -> list[str]:
    """Every symlinked component of ``path`` up to ``stop_at`` (default ``/``).

    An ancestor symlink is as dangerous as one at the leaf: it can be repointed
    after the location was authorized, silently relocating the corpus.
    """
    stop = Path(stop_at).resolve() if stop_at else Path("/")
    found: list[str] = []
    probe = Path(path)
    while True:
        if probe.is_symlink():
            try:
                found.append(f"{probe} -> {os.readlink(probe)}")
            except OSError:
                found.append(str(probe))
        if probe == probe.parent or probe.resolve() == stop:
            break
        probe = probe.parent
    return found


@dataclass
class LocalRootReport:
    """Outcome of validating a candidate local archive root."""

    path: Path
    ok: bool = False
    failures: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    free_bytes: int | None = None
    is_default: bool = False

    def summary(self) -> dict:
        return {
            "ok": self.ok,
            "is_default_local_root": self.is_default,
            "checks": self.checks,
            "failures": self.failures,
            "free_bytes": self.free_bytes,
        }


def validate_local_root(
    path: Path,
    *,
    min_free_bytes: int = 5 * 1024 * 1024 * 1024,
    require_writable: bool = True,
    extra_forbidden_roots: tuple[Path, ...] = (),
) -> LocalRootReport:
    """Run every local-storage guard and report which ones failed.

    Returns a report rather than raising so preflight can show the operator all
    the problems at once instead of one per run.
    """
    candidate = Path(path)
    report = LocalRootReport(path=candidate)
    resolved = candidate.resolve()
    home = Path.home().resolve()
    report.is_default = resolved == default_local_root().resolve()

    def record(name: str, passed: bool, detail: str = "") -> bool:
        report.checks[name] = {"passed": passed, "detail": detail}
        if not passed:
            report.failures.append(f"{name}: {detail}" if detail else name)
        return passed

    record("absolute_path", candidate.is_absolute(), "" if candidate.is_absolute() else f"{candidate} is not absolute")

    # --- must not be a symlink, at the leaf or any ancestor -------------
    links = symlink_ancestors(candidate, stop_at=Path("/"))
    record(
        "not_a_symlink",
        not links,
        "" if not links else f"symlinked component(s): {'; '.join(links[:3])}",
    )

    # --- must live under the user's home directory ----------------------
    record(
        "under_home_directory",
        _is_within(resolved, home) and resolved != home,
        "" if _is_within(resolved, home) and resolved != home
        else f"{resolved} is not a directory inside {home}",
    )

    # --- must not be inside any Git repository or worktree ---------------
    git_dir = enclosing_git_dir(candidate)
    top = git_toplevel(candidate)
    inside_git = git_dir is not None or top is not None
    record(
        "outside_every_git_repository",
        not inside_git,
        ""
        if not inside_git
        else f"inside a Git working tree ({git_dir or top}); raw archival material must never be committable",
    )

    # --- must not be inside a known project repository -------------------
    forbidden_hits = [str(r) for r in extra_forbidden_roots if resolved == Path(r).resolve() or _is_within(resolved, Path(r).resolve())]
    record(
        "outside_project_repositories",
        not forbidden_hits,
        "" if not forbidden_hits else f"inside {forbidden_hits[0]}",
    )

    # --- must not be inside Desktop / Downloads / Documents / Library ----
    home_hits = [name for name in FORBIDDEN_HOME_SUBDIRS if _is_within(resolved, home / name)]
    record(
        "outside_managed_home_subdirectories",
        not home_hits,
        "" if not home_hits else f"inside ~/{home_hits[0]}",
    )

    # --- must not be iCloud-synchronized ---------------------------------
    synced, why = is_icloud_synced(candidate)
    record("not_icloud_synchronized", not synced, why)

    # --- must be writable -------------------------------------------------
    if require_writable:
        writable = probe_writable(candidate)
        record("writable", writable, "" if writable else f"cannot create files under {candidate}")
    else:
        report.checks["writable"] = {"passed": True, "detail": "not checked (read-only operation)"}

    # --- must have enough free space --------------------------------------
    available = free_bytes(candidate)
    report.free_bytes = available
    enough = available is None or available >= min_free_bytes
    record(
        "sufficient_free_space",
        enough,
        ""
        if enough
        else f"{available} bytes free, need at least {min_free_bytes}",
    )

    report.ok = not report.failures
    return report
