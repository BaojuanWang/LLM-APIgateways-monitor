"""Shared pytest fixtures for the archive subsystem.

Every test that touches storage runs against a synthetic scratch directory under
``tmp_path`` with the explicit ``ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL=1`` opt-in.
No test depends on a live third-party website, and no test can write into a real
corpus: the storage boundary rejects a repo-internal root regardless of mode.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ARCHIVE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = ARCHIVE_DIR.parent
for candidate in (str(ARCHIVE_DIR), str(ARCHIVE_DIR / "scripts")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def repo_root_path() -> Path:
    return REPO_ROOT


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture
def test_env(monkeypatch, tmp_path) -> Path:
    """A synthetic ARCHIVE_ROOT with the test-only opt-in enabled."""
    root = tmp_path / "corpus-root"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ARCHIVE_ROOT", str(root))
    monkeypatch.setenv("ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL", "1")
    return root


@pytest.fixture
def archive_root(test_env):
    from archivelib.paths import resolve_archive_root

    return resolve_archive_root(allow_nonexternal=True)


@pytest.fixture
def cfg() -> dict:
    from archivelib.config import load_config

    return load_config(REPO_ROOT)


@pytest.fixture
def identity():
    from archivelib.identity import ServiceIdentity, service_id_for_host

    host = "fixture.localhost.test"
    return ServiceIdentity(
        service_id=service_id_for_host(host),
        host=host,
        canonical_url="http://127.0.0.1:0/",
        platform_name="Fixture Gateway",
        source="synthetic",
        inventory_file="archive/tests/fixtures/master_sites_sample.csv",
        inventory_file_sha256="0" * 64,
        inventory_row={"domain": host, "platform_name": "Fixture Gateway"},
        inventory_row_sha256="1" * 64,
    )
