"""Storage-boundary tests.

The single most damaging failure this subsystem could have is writing a
multi-gigabyte raw corpus somewhere it must never go — the internal disk, the
home directory, or the public Git repository. These tests pin that boundary
shut from every direction: unset variable, relative path, symlink escape,
repo-internal root, path traversal in an identifier, and the "external volume is
absent" case that is the actual state of this machine.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from archivelib.errors import ArchiveRootError, OverwriteError, PathEscapeError
from archivelib.paths import (
    ARCHIVE_ROOT_ENV,
    TEST_ONLY_ENV,
    create_capture_dir,
    relative_corpus_path,
    repo_root,
    resolve_archive_root,
    safe_join,
)


# --- absent / malformed ARCHIVE_ROOT ---------------------------------------


def test_missing_archive_root_is_an_error(monkeypatch):
    monkeypatch.delenv(ARCHIVE_ROOT_ENV, raising=False)
    with pytest.raises(ArchiveRootError, match="not set"):
        resolve_archive_root()


def test_empty_archive_root_is_an_error(monkeypatch):
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, "   ")
    with pytest.raises(ArchiveRootError, match="not set"):
        resolve_archive_root()


def test_relative_archive_root_is_rejected(monkeypatch):
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, "relative/corpus")
    with pytest.raises(ArchiveRootError, match="absolute"):
        resolve_archive_root()


# --- the real-mode external volume requirement ------------------------------


def test_real_mode_requires_volumes_prefix(monkeypatch, tmp_path):
    """A scratch dir is not an external volume, even if it is writable."""
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(tmp_path / "corpus"))
    monkeypatch.delenv(TEST_ONLY_ENV, raising=False)
    with pytest.raises(ArchiveRootError, match="must be under /Volumes"):
        resolve_archive_root()


def test_real_mode_rejects_home_directory(monkeypatch):
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(Path.home() / "corpus"))
    monkeypatch.delenv(TEST_ONLY_ENV, raising=False)
    with pytest.raises(ArchiveRootError, match="must be under /Volumes"):
        resolve_archive_root()


def test_real_mode_rejects_tmp(monkeypatch):
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, "/tmp/corpus")
    monkeypatch.delenv(TEST_ONLY_ENV, raising=False)
    with pytest.raises(ArchiveRootError, match="must be under /Volumes"):
        resolve_archive_root()


def test_absent_external_volume_fails_closed(monkeypatch, tmp_path):
    """The case this machine is actually in: /Volumes has no external disk.

    A path that *looks* right must still fail, because the volume behind it
    cannot be confirmed external. There is no fallback.
    """
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, "/Volumes/NoSuchExternalDisk/LLM-APIgateways-corpus")
    monkeypatch.delenv(TEST_ONLY_ENV, raising=False)
    with pytest.raises(ArchiveRootError):
        resolve_archive_root()


def test_symlink_out_of_volumes_is_rejected(monkeypatch, tmp_path):
    """``/Volumes/Macintosh HD`` is a symlink to ``/``.

    Path-prefix checking alone would accept it and aim the corpus at the boot
    disk, so resolution has to happen before the prefix check.
    """
    fake_volumes = tmp_path / "Volumes"
    fake_volumes.mkdir()
    escape_target = tmp_path / "internal"
    escape_target.mkdir()
    link = fake_volumes / "Macintosh HD"
    link.symlink_to(escape_target)

    resolved = link.resolve()
    assert not str(resolved).startswith("/Volumes"), "symlink must resolve outside /Volumes"

    monkeypatch.setenv(ARCHIVE_ROOT_ENV, "/Volumes/Macintosh HD/corpus")
    monkeypatch.delenv(TEST_ONLY_ENV, raising=False)
    with pytest.raises(ArchiveRootError):
        resolve_archive_root()


# --- the test-only escape hatch --------------------------------------------


def test_test_only_flag_requires_env_opt_in(monkeypatch, tmp_path):
    """A CLI flag alone must not be able to redirect storage."""
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(tmp_path / "corpus"))
    monkeypatch.delenv(TEST_ONLY_ENV, raising=False)
    with pytest.raises(ArchiveRootError, match="opt-in"):
        resolve_archive_root(allow_nonexternal=True)


def test_test_only_mode_works_with_both_signals(monkeypatch, tmp_path):
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(tmp_path / "corpus"))
    monkeypatch.setenv(TEST_ONLY_ENV, "1")
    root = resolve_archive_root(allow_nonexternal=True)
    assert root.mode == "test-only"
    assert not root.is_real


def test_repo_internal_root_rejected_even_in_test_mode(monkeypatch):
    """The repo is off limits in BOTH modes — this is the leak that matters."""
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(repo_root() / "archive" / "runtime" / "corpus"))
    monkeypatch.setenv(TEST_ONLY_ENV, "1")
    with pytest.raises(ArchiveRootError, match="inside the Git repository"):
        resolve_archive_root(allow_nonexternal=True)


# --- path traversal ---------------------------------------------------------


@pytest.mark.parametrize("evil", ["..", ".", "../escape", "/absolute", "a/b", "a\\b", "", "nul\x00byte"])
def test_safe_join_rejects_traversal(tmp_path, evil):
    with pytest.raises(PathEscapeError):
        safe_join(tmp_path, evil)


def test_safe_join_accepts_plain_component(tmp_path):
    assert safe_join(tmp_path, "service_1a2b3c4d") == tmp_path / "service_1a2b3c4d"


def test_capture_dir_rejects_traversal_in_ids(archive_root):
    with pytest.raises(PathEscapeError):
        create_capture_dir(archive_root, "..", "capture")
    with pytest.raises(PathEscapeError):
        create_capture_dir(archive_root, "svc_00000000", "../../etc")


# --- corpus layout ----------------------------------------------------------


def test_create_capture_dir_builds_expected_layout(archive_root):
    target = create_capture_dir(archive_root, "svc_00000000", "20260101T000000Z_svc_00000000_abcdef123456")
    assert target.is_dir()
    for sub in ("raw/browsertrix", "raw/rendered/screenshots", "config", "manifests", "validation"):
        assert (target / sub).is_dir(), sub


def test_create_capture_dir_never_overwrites(archive_root):
    args = (archive_root, "svc_00000000", "20260101T000000Z_svc_00000000_abcdef123456")
    create_capture_dir(*args)
    with pytest.raises(OverwriteError):
        create_capture_dir(*args)


def test_relative_corpus_path_is_never_absolute(archive_root):
    target = create_capture_dir(archive_root, "svc_00000000", "20260101T000000Z_svc_00000000_abcdef123456")
    rel = relative_corpus_path(archive_root, target)
    assert not rel.startswith("/")
    assert ".." not in rel
    assert os.sep + "Users" not in rel


def test_relative_corpus_path_rejects_outside_paths(archive_root, tmp_path):
    with pytest.raises(PathEscapeError):
        relative_corpus_path(archive_root, tmp_path / "elsewhere")
