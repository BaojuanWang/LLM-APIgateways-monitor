"""$ARCHIVE_ROOT resolution, corpus layout, and path-safety enforcement.

Three modes exist, and each one has to be asked for:

``external_volume`` — **recommended, and the default**
    ``ARCHIVE_ROOT`` is under ``/Volumes``, is still under ``/Volumes`` after
    symlink resolution, and ``diskutil`` confirms the backing volume is external
    and writable. An external corpus can be unmounted and stored separately from
    the machine that made it, which is why it stays the recommendation.

``explicitly_authorized_local`` — opt-in
    Keeps the corpus on the MacBook's own disk. Refused unless the operator
    explicitly authorizes it via ``--allow-local-storage`` (or the equivalent
    config/env opt-in), and then only if the path clears every guard in
    ``localstore.validate_local_root``: outside any Git repository or worktree,
    outside Desktop/Downloads/Documents and iCloud, not a symlink, under the
    home directory, writable, and with enough free space.

``test_only``
    Enabled solely by the explicit ``ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL=1``
    opt-in (surfaced as ``--test-only-allow-nonexternal``). Lets the unit tests
    and the synthetic smoke test run against a scratch directory.

There is still no fallback. A missing disk is an error, never a quiet redirect —
and no mode, including the authorized local one, will place a corpus inside a
Git repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ArchiveRootError, OverwriteError, PathEscapeError
from .localstore import (
    STORAGE_MODE_EXTERNAL,
    STORAGE_MODE_LOCAL,
    STORAGE_MODE_TEST,
    allow_local_flag_enabled,
    default_local_root,
    validate_local_root,
)
from .volumes import VolumeInfo, inspect_volume, mount_point_for, probe_writable

ARCHIVE_ROOT_ENV = "ARCHIVE_ROOT"
TEST_ONLY_ENV = "ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL"

# Project working trees that must never contain a corpus, regardless of mode.
# Resolved as siblings of this repository so no username is hardcoded.
def project_repo_roots() -> tuple[Path, ...]:
    here = repo_root()
    parent = here.parent
    names = ("LLM-APIgateways-monitor", "LLM-APIgateways-archive", "LLM-APIgateways-audit-clean")
    roots = {here}
    for name in names:
        roots.add(parent / name)
    return tuple(sorted(roots))

VOLUMES_PREFIX = Path("/Volumes")

# Locations that must never hold a real corpus even if someone points
# ARCHIVE_ROOT at them. Checked against the fully symlink-resolved path.
FORBIDDEN_REAL_PREFIXES = ("/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp")
FORBIDDEN_REAL_HOME_SUBDIRS = ("Desktop", "Documents", "Downloads", "Library", "Movies", "Music", "Pictures")

CORPUS_DIRNAME = "corpus"
OPERATIONAL_DIRNAME = "operational"
PUBLIC_EXPORT_DIRNAME = "public-export"


def repo_root() -> Path:
    """Repository working tree that contains this package."""
    # archive/archivelib/paths.py -> archive/archivelib -> archive -> <repo>
    return Path(__file__).resolve().parents[2]


@dataclass
class ArchiveRootInfo:
    """Everything preflight learned about the storage boundary."""

    raw: str
    path: Path
    mode: str  # external_volume | explicitly_authorized_local | test_only
    volume: VolumeInfo | None = None
    mount_point: Path | None = None
    local_report: object | None = None

    @property
    def storage_mode(self) -> str:
        """The value recorded with every capture."""
        return self.mode

    @property
    def is_real(self) -> bool:
        """True for both production modes; False only for the test scratch mode."""
        return self.mode in (STORAGE_MODE_EXTERNAL, STORAGE_MODE_LOCAL)

    @property
    def is_external(self) -> bool:
        return self.mode == STORAGE_MODE_EXTERNAL

    @property
    def is_local(self) -> bool:
        return self.mode == STORAGE_MODE_LOCAL

    @property
    def corpus_dir(self) -> Path:
        return self.path / CORPUS_DIRNAME

    @property
    def operational_dir(self) -> Path:
        return self.path / OPERATIONAL_DIRNAME

    @property
    def queue_dir(self) -> Path:
        return self.operational_dir / "queue"

    @property
    def logs_dir(self) -> Path:
        return self.operational_dir / "logs"

    @property
    def locks_dir(self) -> Path:
        return self.operational_dir / "locks"

    @property
    def public_export_dir(self) -> Path:
        return self.path / PUBLIC_EXPORT_DIRNAME

    def summary(self) -> dict:
        return {
            "storage_mode": self.mode,
            "raw": self.raw,
            "resolved": str(self.path),
            "mount_point": str(self.mount_point) if self.mount_point else None,
            "volume": self.volume.summary() if self.volume else None,
            "local_checks": self.local_report.summary() if self.local_report is not None else None,
        }

    def public_summary(self) -> dict:
        """Storage facts safe to publish: mode only, never the path.

        An absolute local path would disclose the operator's username, which is
        the whole reason the public export normalizes paths away.
        """
        return {
            "storage_mode": self.mode,
            "external_volume": self.is_external,
        }


def test_only_flag_enabled(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return str(env.get(TEST_ONLY_ENV, "")).strip() == "1"


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def local_storage_authorized(
    *,
    cli_flag: bool = False,
    cfg: dict | None = None,
    env: dict | None = None,
) -> bool:
    """Whether local storage has been explicitly authorized.

    Three equally explicit signals, any one of which suffices: the
    ``--allow-local-storage`` CLI flag, ``[storage] allow_local_storage = true``
    in the config, or ``ARCHIVE_ALLOW_LOCAL_STORAGE=1`` (which exists so a
    launchd job can be authorized without an interactive flag). All three
    default to off — silence is never authorization.
    """
    if cli_flag:
        return True
    if cfg and bool((cfg.get("storage") or {}).get("allow_local_storage", False)):
        return True
    return allow_local_flag_enabled(env)


def resolve_archive_root(
    env: dict | None = None,
    *,
    allow_nonexternal: bool = False,
    allow_local_storage: bool = False,
    cfg: dict | None = None,
    require_writable: bool = True,
) -> ArchiveRootInfo:
    """Resolve and validate ``$ARCHIVE_ROOT``, or raise.

    Mode is decided by the path, not by preference: a ``/Volumes`` path is
    always evaluated as an external volume, and only a non-``/Volumes`` path
    consults the local-storage authorization. So enabling local storage cannot
    weaken the checks applied to an external one.

    ``allow_nonexternal`` (the test scratch mode) still requires the separate
    ``ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL=1`` environment opt-in, so a stray
    command-line flag alone can never redirect captures.
    """
    env = os.environ if env is None else env

    local_ok = local_storage_authorized(cli_flag=allow_local_storage, cfg=cfg, env=env)

    raw = str(env.get(ARCHIVE_ROOT_ENV, "") or "").strip()
    if not raw:
        hint = (
            "export ARCHIVE_ROOT=/Volumes/<external-volume>/LLM-APIgateways-corpus"
            if not local_ok
            else f"export ARCHIVE_ROOT={default_local_root()}   (local storage is authorized)"
        )
        raise ArchiveRootError(f"{ARCHIVE_ROOT_ENV} is not set. Export it, e.g.\n    {hint}")

    candidate = Path(raw)
    if not candidate.is_absolute():
        raise ArchiveRootError(f"{ARCHIVE_ROOT_ENV} must be an absolute path, got {raw!r}")
    if "\x00" in raw:
        raise ArchiveRootError(f"{ARCHIVE_ROOT_ENV} contains a NUL byte")

    resolved = candidate.resolve()

    # Applies to EVERY mode, including authorized local storage: a corpus inside
    # the Git repo would eventually be committed, which is the single failure
    # this subsystem exists to prevent.
    repo = repo_root()
    if resolved == repo or _is_within(resolved, repo):
        raise ArchiveRootError(
            f"{ARCHIVE_ROOT_ENV} resolves inside the Git repository ({repo}). "
            "Raw archival material must never live in the repo."
        )
    for project in project_repo_roots():
        project_resolved = project.resolve() if project.exists() else project
        if resolved == project_resolved or _is_within(resolved, project_resolved):
            raise ArchiveRootError(
                f"{ARCHIVE_ROOT_ENV} resolves inside the project repository {project}. "
                "Raw archival material must never live in a working tree."
            )

    test_mode = allow_nonexternal and test_only_flag_enabled(env)
    if allow_nonexternal and not test_mode:
        raise ArchiveRootError(
            "non-external storage was requested but the explicit opt-in "
            f"{TEST_ONLY_ENV}=1 is not set; refusing"
        )

    if test_mode:
        if require_writable and not probe_writable(resolved):
            raise ArchiveRootError(f"test-only archive root is not writable: {resolved}")
        return ArchiveRootInfo(raw=raw, path=resolved, mode=STORAGE_MODE_TEST)

    # ---- explicitly authorized local storage ---------------------------
    # Only for paths that are not under /Volumes; a /Volumes path always goes
    # through the external-volume checks below.
    if not _is_within(candidate, VOLUMES_PREFIX) or candidate == VOLUMES_PREFIX:
        if not local_ok:
            raise ArchiveRootError(
                f"{ARCHIVE_ROOT_ENV}={raw!r} is not on an external volume.\n"
                "    External storage is the default and the recommendation.\n"
                "    To keep the corpus on this Mac instead, authorize it explicitly:\n"
                "        --allow-local-storage\n"
                "    (or set [storage] allow_local_storage = true, or "
                "ARCHIVE_ALLOW_LOCAL_STORAGE=1)"
            )
        safety = (cfg or {}).get("safety", {}) if cfg else {}
        report = validate_local_root(
            candidate,
            min_free_bytes=int(safety.get("min_free_bytes", 5 * 1024 * 1024 * 1024)),
            require_writable=require_writable,
            extra_forbidden_roots=project_repo_roots(),
        )
        if not report.ok:
            bullets = "\n".join(f"      - {failure}" for failure in report.failures)
            raise ArchiveRootError(
                f"local archive root {candidate} is authorized but failed validation:\n{bullets}"
            )
        return ArchiveRootInfo(
            raw=raw, path=resolved, mode=STORAGE_MODE_LOCAL, local_report=report
        )

    # ---- external volume (recommended default) --------------------------
    if not _is_within(resolved, VOLUMES_PREFIX):
        # e.g. /Volumes/Macintosh HD -> /
        raise ArchiveRootError(
            f"{ARCHIVE_ROOT_ENV}={raw!r} resolves through a symlink to {resolved}, "
            "which is outside /Volumes. Refusing: this is the internal disk."
        )
    for bad in FORBIDDEN_REAL_PREFIXES:
        if _is_within(resolved, Path(bad)):
            raise ArchiveRootError(f"{ARCHIVE_ROOT_ENV} resolves into {bad}; not permitted for real captures")
    home = Path.home().resolve()
    if resolved == home:
        raise ArchiveRootError(f"{ARCHIVE_ROOT_ENV} resolves to the home directory; not permitted")
    for sub in FORBIDDEN_REAL_HOME_SUBDIRS:
        if _is_within(resolved, home / sub):
            raise ArchiveRootError(f"{ARCHIVE_ROOT_ENV} resolves into ~/{sub}; not permitted for real captures")

    mount = mount_point_for(resolved)
    if mount == Path("/"):
        raise ArchiveRootError(
            f"{ARCHIVE_ROOT_ENV}={raw!r} is backed by the root filesystem mount; refusing"
        )
    if not _is_within(mount, VOLUMES_PREFIX):
        raise ArchiveRootError(
            f"{ARCHIVE_ROOT_ENV}={raw!r} is backed by mount {mount}, which is not under /Volumes"
        )

    volume = inspect_volume(mount)
    if not volume.is_external:
        raise ArchiveRootError(
            f"volume at {mount} is not confirmed external by diskutil "
            f"(Internal={volume.internal!r}); refusing to write real captures"
        )
    if not volume.is_writable:
        raise ArchiveRootError(
            f"volume at {mount} is not writable (WritableVolume={volume.writable!r})"
        )
    if require_writable and not probe_writable(resolved):
        raise ArchiveRootError(f"archive root exists on {mount} but is not writable: {resolved}")

    return ArchiveRootInfo(
        raw=raw, path=resolved, mode=STORAGE_MODE_EXTERNAL, volume=volume, mount_point=mount
    )


# ---------------------------------------------------------------------------
# Corpus layout
# ---------------------------------------------------------------------------


def service_dir(root: ArchiveRootInfo, service_id: str) -> Path:
    return safe_join(root.corpus_dir, service_id)


def captures_dir(root: ArchiveRootInfo, service_id: str) -> Path:
    return service_dir(root, service_id) / "captures"


def capture_dir(root: ArchiveRootInfo, service_id: str, capture_id: str) -> Path:
    return safe_join(captures_dir(root, service_id), capture_id)


def discovery_dir(root: ArchiveRootInfo, service_id: str) -> Path:
    return service_dir(root, service_id) / "discovery"


def tombstones_dir(root: ArchiveRootInfo, service_id: str) -> Path:
    return service_dir(root, service_id) / "tombstones"


CAPTURE_SUBDIRS = (
    "raw/browsertrix",
    "raw/rendered/screenshots",
    "config",
    "manifests",
    "validation",
)


def safe_join(base: Path, *parts: str) -> Path:
    """Join under ``base`` and refuse anything that escapes it.

    Guards against ``..`` segments, absolute components, and separators smuggled
    into an identifier.
    """
    for part in parts:
        if not part or part in (".", ".."):
            raise PathEscapeError(f"invalid path component {part!r}")
        if part.startswith("/") or "\\" in part:
            raise PathEscapeError(f"path component must be relative and slash-free: {part!r}")
        if "/" in part:
            raise PathEscapeError(f"path component must not contain a separator: {part!r}")
        if "\x00" in part:
            raise PathEscapeError("path component contains a NUL byte")
    joined = base.joinpath(*parts)
    base_resolved = base.resolve()
    # Resolve without requiring existence, then confirm containment.
    joined_resolved = joined.resolve()
    if joined_resolved != base_resolved and not _is_within(joined_resolved, base_resolved):
        raise PathEscapeError(f"path {joined} escapes {base}")
    return joined


def create_capture_dir(root: ArchiveRootInfo, service_id: str, capture_id: str) -> Path:
    """Create a brand-new capture directory, failing closed if it exists.

    Append-only storage depends on this never being ``exist_ok=True``.
    """
    target = capture_dir(root, service_id, capture_id)
    if target.exists():
        raise OverwriteError(
            f"capture directory already exists and must never be overwritten: {target}"
        )
    try:
        target.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise OverwriteError(f"capture directory appeared concurrently: {target}") from exc
    for sub in CAPTURE_SUBDIRS:
        (target / sub).mkdir(parents=True, exist_ok=True)
    return target


def assert_no_symlink_escape(base: Path) -> list[str]:
    """Return violations for symlinks under ``base`` that point outside it.

    Symlinks are the one way an "append-only directory tree" can silently gain a
    pointer to something mutable elsewhere on the machine, so the validator and
    the manifest builder both call this.
    """
    base_resolved = base.resolve()
    violations: list[str] = []
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        for name in list(dirnames) + list(filenames):
            entry = Path(dirpath) / name
            if not entry.is_symlink():
                continue
            try:
                target = entry.resolve()
            except OSError:
                violations.append(f"{entry.relative_to(base_resolved)} -> <unresolvable>")
                continue
            if not _is_within(target, base_resolved):
                violations.append(f"{entry.relative_to(base_resolved)} -> {target}")
    return violations


def relative_corpus_path(root: ArchiveRootInfo, path: Path) -> str:
    """Corpus-relative identifier suitable for the public export.

    Never emits an absolute path, so nothing about the operator's filesystem
    layout leaks into Git.
    """
    resolved = Path(path).resolve()
    root_resolved = root.path.resolve()
    if not _is_within(resolved, root_resolved):
        raise PathEscapeError(f"{path} is not inside the archive root")
    return str(resolved.relative_to(root_resolved))


def iter_capture_files(capture_root: Path) -> list[Path]:
    """Deterministically ordered list of regular files under a capture dir."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(capture_root, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            entry = Path(dirpath) / name
            if entry.is_symlink() or not entry.is_file():
                continue
            found.append(entry)
    return sorted(found, key=lambda p: str(p.relative_to(capture_root)))
