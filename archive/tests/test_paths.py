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
from archivelib.localstore import (
    ALLOW_LOCAL_ENV,
    STORAGE_MODE_LOCAL,
    default_local_root,
)
from archivelib.paths import (
    ARCHIVE_ROOT_ENV,
    TEST_ONLY_ENV,
    create_capture_dir,
    local_storage_authorized,
    project_repo_roots,
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


def test_local_path_refused_without_authorization(monkeypatch, tmp_path):
    """A scratch dir is not an external volume, and local storage is off by default."""
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(tmp_path / "corpus"))
    monkeypatch.delenv(TEST_ONLY_ENV, raising=False)
    monkeypatch.delenv(ALLOW_LOCAL_ENV, raising=False)
    with pytest.raises(ArchiveRootError, match="allow-local-storage"):
        resolve_archive_root()


def test_home_directory_refused_without_authorization(monkeypatch):
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(Path.home() / "corpus"))
    monkeypatch.delenv(TEST_ONLY_ENV, raising=False)
    monkeypatch.delenv(ALLOW_LOCAL_ENV, raising=False)
    with pytest.raises(ArchiveRootError, match="allow-local-storage"):
        resolve_archive_root()


def test_tmp_refused_even_when_local_storage_is_authorized(monkeypatch):
    """Authorization is not a bypass: /tmp is still not under the home directory."""
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, "/tmp/corpus")
    monkeypatch.delenv(TEST_ONLY_ENV, raising=False)
    with pytest.raises(ArchiveRootError, match="under_home_directory"):
        resolve_archive_root(allow_local_storage=True)


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
    assert root.mode == "test_only"
    assert not root.is_real
    assert not root.is_external and not root.is_local


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


# ---------------------------------------------------------------------------
# Explicitly authorized local storage
# ---------------------------------------------------------------------------


@pytest.fixture
def local_root(tmp_path, monkeypatch):
    """A local-looking archive root that passes every guard.

    Rooted under a fake HOME so the checks that key off the home directory
    (managed subdirs, iCloud, "under home") exercise real logic without
    depending on the developer's actual home layout.
    """
    home = tmp_path / "home"
    (home / "LLM-APIgateways-corpus").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home / "LLM-APIgateways-corpus"


# --- authorization gate -----------------------------------------------------


def test_local_storage_is_off_by_default(monkeypatch):
    monkeypatch.delenv(ALLOW_LOCAL_ENV, raising=False)
    assert local_storage_authorized() is False
    assert local_storage_authorized(cfg={}) is False
    assert local_storage_authorized(cfg={"storage": {}}) is False


def test_cli_flag_authorizes(monkeypatch):
    monkeypatch.delenv(ALLOW_LOCAL_ENV, raising=False)
    assert local_storage_authorized(cli_flag=True) is True


def test_config_option_authorizes(monkeypatch):
    monkeypatch.delenv(ALLOW_LOCAL_ENV, raising=False)
    assert local_storage_authorized(cfg={"storage": {"allow_local_storage": True}}) is True


def test_env_var_authorizes(monkeypatch):
    monkeypatch.setenv(ALLOW_LOCAL_ENV, "1")
    assert local_storage_authorized() is True
    monkeypatch.setenv(ALLOW_LOCAL_ENV, "0")
    assert local_storage_authorized() is False


def test_authorized_local_root_resolves(monkeypatch, local_root):
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(local_root))
    monkeypatch.delenv(TEST_ONLY_ENV, raising=False)
    root = resolve_archive_root(allow_local_storage=True)
    assert root.mode == STORAGE_MODE_LOCAL
    assert root.storage_mode == "explicitly_authorized_local"
    assert root.is_real and root.is_local and not root.is_external


def test_default_local_root_is_home_relative():
    assert default_local_root() == Path.home() / "LLM-APIgateways-corpus"


def test_no_shipped_source_hardcodes_a_home_path():
    """This repository is public: a literal /Users/<name> would publish it.

    Enforced with the project's own ``absolute_user_path`` rule so the test and
    the pre-commit scan cannot drift apart. Scoped to that rule specifically:
    ``/Volumes/<external-volume>`` placeholders are intentional documentation and
    disclose nothing, whereas a home path carries the operator's account name.
    Test files are excluded — they carry synthetic paths deliberately, as
    detector *input*.
    """
    from archivelib.sanitize import scan_text_for_secrets

    offenders = []
    for base in (repo_root() / "archive", repo_root() / "docs" / "LOCAL_WACZ_ARCHIVE.md"):
        paths = sorted(base.rglob("*")) if base.is_dir() else [base]
        for path in paths:
            if not path.is_file() or path.suffix not in (".py", ".toml", ".yaml", ".json", ".md", ".template"):
                continue
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for finding in scan_text_for_secrets(text, str(path.relative_to(repo_root()))):
                if finding.rule == "absolute_user_path":
                    offenders.append(f"{finding.path}:{finding.line} {finding.excerpt}")
    assert not offenders, f"hardcoded home paths in shipped source: {offenders}"


# --- the rule-5 guards ------------------------------------------------------


def test_local_root_inside_a_git_repository_is_refused(monkeypatch, tmp_path):
    home = tmp_path / "home"
    project = home / "some-project"
    (project / ".git").mkdir(parents=True)
    corpus = project / "corpus"
    corpus.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(corpus))
    with pytest.raises(ArchiveRootError, match="outside_every_git_repository"):
        resolve_archive_root(allow_local_storage=True)


def test_local_root_inside_a_git_worktree_is_refused(monkeypatch, tmp_path):
    """A linked worktree has a .git FILE, not a directory."""
    home = tmp_path / "home"
    worktree = home / "linked-worktree"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n", encoding="utf-8")
    corpus = worktree / "corpus"
    corpus.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(corpus))
    with pytest.raises(ArchiveRootError, match="outside_every_git_repository"):
        resolve_archive_root(allow_local_storage=True)


@pytest.mark.parametrize("subdir", ["Desktop", "Downloads", "Documents", "Library"])
def test_local_root_in_managed_home_subdirs_is_refused(monkeypatch, tmp_path, subdir):
    home = tmp_path / "home"
    corpus = home / subdir / "corpus"
    corpus.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(corpus))
    with pytest.raises(ArchiveRootError, match="outside_managed_home_subdirectories"):
        resolve_archive_root(allow_local_storage=True)


def test_local_root_in_icloud_drive_is_refused(monkeypatch, tmp_path):
    home = tmp_path / "home"
    corpus = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "corpus"
    corpus.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(corpus))
    with pytest.raises(ArchiveRootError, match="not_icloud_synchronized|outside_managed"):
        resolve_archive_root(allow_local_storage=True)


def test_icloud_desktop_documents_sync_is_detected(monkeypatch, tmp_path):
    """With Desktop & Documents sync on, the paths look normal but replicate."""
    from archivelib.localstore import is_icloud_synced

    home = tmp_path / "home"
    (home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Documents").mkdir(parents=True)
    target = home / "Documents" / "corpus"
    target.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    synced, why = is_icloud_synced(target)
    assert synced and "iCloud" in why


def test_symlinked_local_root_is_refused(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir(parents=True)
    real = tmp_path / "elsewhere"
    real.mkdir()
    link = home / "LLM-APIgateways-corpus"
    link.symlink_to(real)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(link))
    with pytest.raises(ArchiveRootError, match="not_a_symlink"):
        resolve_archive_root(allow_local_storage=True)


def test_symlinked_ancestor_is_refused(monkeypatch, tmp_path):
    """An ancestor link can be repointed after authorization."""
    home = tmp_path / "home"
    home.mkdir(parents=True)
    real = tmp_path / "real-parent"
    (real / "corpus").mkdir(parents=True)
    (home / "parent").symlink_to(real)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(home / "parent" / "corpus"))
    with pytest.raises(ArchiveRootError, match="not_a_symlink"):
        resolve_archive_root(allow_local_storage=True)


def test_insufficient_free_space_is_refused(monkeypatch, local_root):
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(local_root))
    huge = {"safety": {"min_free_bytes": 1 << 62}}
    with pytest.raises(ArchiveRootError, match="sufficient_free_space"):
        resolve_archive_root(allow_local_storage=True, cfg=huge)


def test_local_validation_reports_every_failure_at_once(tmp_path, monkeypatch):
    from archivelib.localstore import validate_local_root

    home = tmp_path / "home"
    corpus = home / "Desktop" / "repo" / "corpus"
    corpus.mkdir(parents=True)
    (home / "Desktop" / "repo" / ".git").mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    report = validate_local_root(corpus, min_free_bytes=0)
    assert not report.ok
    names = {f.split(":")[0] for f in report.failures}
    assert {"outside_every_git_repository", "outside_managed_home_subdirectories"} <= names


# --- repository refusal still applies to local mode -------------------------


def test_project_repositories_are_refused_in_local_mode(monkeypatch):
    """Requirement: the monitor and archive worktrees stay off limits."""
    for project in project_repo_roots():
        monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(project / "corpus"))
        with pytest.raises(ArchiveRootError, match="repositor"):
            resolve_archive_root(allow_local_storage=True)


def test_repo_root_itself_is_refused_in_local_mode(monkeypatch):
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(repo_root() / "corpus"))
    with pytest.raises(ArchiveRootError, match="Git repository"):
        resolve_archive_root(allow_local_storage=True)


# --- external volume behaviour is unchanged ---------------------------------


def test_authorizing_local_does_not_weaken_external_checks(monkeypatch):
    """A /Volumes path is always evaluated as an external volume."""
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, "/Volumes/Macintosh HD/corpus")
    with pytest.raises(ArchiveRootError, match="internal disk|not under /Volumes|root filesystem"):
        resolve_archive_root(allow_local_storage=True)


def test_nonexistent_volume_still_refused_with_local_authorized(monkeypatch):
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, "/Volumes/NoSuchDisk/corpus")
    with pytest.raises(ArchiveRootError):
        resolve_archive_root(allow_local_storage=True)


# --- storage mode is never a path -------------------------------------------


def test_public_summary_omits_the_path(monkeypatch, local_root):
    monkeypatch.setenv(ARCHIVE_ROOT_ENV, str(local_root))
    root = resolve_archive_root(allow_local_storage=True)
    public = root.public_summary()
    assert public == {"storage_mode": "explicitly_authorized_local", "external_volume": False}
    assert str(local_root) not in repr(public)
