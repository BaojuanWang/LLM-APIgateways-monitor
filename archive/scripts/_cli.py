"""Shared CLI plumbing for the archive scripts.

Kept deliberately small: argument parsing, ``sys.path`` bootstrapping, and the
one place that turns ``--test-only-allow-nonexternal`` into a resolved archive
root. Every script routes storage resolution through here so the boundary rules
cannot drift between commands.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ARCHIVE_PKG_DIR = Path(__file__).resolve().parent.parent
if str(ARCHIVE_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(ARCHIVE_PKG_DIR))

from archivelib.config import load_config  # noqa: E402
from archivelib.errors import ArchiveError  # noqa: E402
from archivelib.paths import repo_root, resolve_archive_root  # noqa: E402


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--config", type=Path, default=None, help="path to an archive TOML config")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON on stdout")
    parser.add_argument(
        "--allow-local-storage",
        action="store_true",
        help=(
            "Authorize keeping the corpus on this Mac's own disk instead of an "
            "external volume. External storage remains the default and the "
            "recommendation. The path must still be outside every Git repository, "
            "outside Desktop/Downloads/Documents and iCloud, not a symlink, "
            "writable, and have enough free space."
        ),
    )
    parser.add_argument(
        "--test-only-allow-nonexternal",
        action="store_true",
        help=(
            "TESTS ONLY: permit a scratch ARCHIVE_ROOT. Also requires the "
            "environment opt-in ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL=1. Never use "
            "this for a capture of a real third-party site."
        ),
    )
    return parser


def get_repo() -> Path:
    return repo_root()


def get_config(args) -> dict:
    return load_config(get_repo(), getattr(args, "config", None))


def get_archive_root(args, *, require_writable: bool = True, cfg: dict | None = None):
    """Resolve $ARCHIVE_ROOT under the mode implied by CLI flags and config."""
    if cfg is None:
        try:
            cfg = get_config(args)
        except Exception:
            cfg = None
    return resolve_archive_root(
        allow_nonexternal=bool(getattr(args, "test_only_allow_nonexternal", False)),
        allow_local_storage=bool(getattr(args, "allow_local_storage", False)),
        cfg=cfg,
        require_writable=require_writable,
    )


def emit(payload: dict, *, as_json: bool, human: str | None = None) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    elif human is not None:
        print(human)


def fail(message: str, *, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def run_guarded(main_fn) -> None:
    """Turn archive errors into clean non-zero exits instead of tracebacks."""
    try:
        raise SystemExit(main_fn())
    except ArchiveError as exc:
        fail(f"{type(exc).__name__}: {exc}")
    except KeyboardInterrupt:
        fail("interrupted", code=130)
