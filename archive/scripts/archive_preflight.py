#!/usr/bin/env python3
"""Preflight: verify the storage boundary and pin every tool before any capture.

Run this first, and run it again whenever the disk, Docker, or the config
changes. It answers three questions:

1. Is there a *verified external writable* place to put raw archival material?
2. Are Browsertrix, SingleFile, and Playwright present and **pinned by digest or
   exact version** (never a floating ``latest``)?
3. Is the repository configured such that raw material cannot leak into Git?

Exit codes: 0 ready for real captures, 1 not ready, 2 hard error.

    python3 archive/scripts/archive_preflight.py
    python3 archive/scripts/archive_preflight.py --json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _cli import add_common_args, emit, get_config, get_repo, run_guarded  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from archivelib.config import config_hash  # noqa: E402
from archivelib.docker_tools import resolve_image_digest  # noqa: E402
from archivelib.envmeta import base_environment, utc_now_iso  # noqa: E402
from archivelib.errors import ArchiveRootError, ExternalVolumeError  # noqa: E402
from archivelib.paths import (  # noqa: E402
    ARCHIVE_ROOT_ENV,
    TEST_ONLY_ENV,
    repo_root,
    resolve_archive_root,
)
from archivelib.render import singlefile_available  # noqa: E402
from archivelib.volumes import (  # noqa: E402
    external_writable_volumes,
    free_bytes,
    list_candidate_volumes,
)


def check_storage(args) -> dict:
    """Resolve the archive root, and describe the disk situation either way."""
    candidates = [v.summary() for v in list_candidate_volumes()]
    externals = [v.summary() for v in external_writable_volumes()]

    result: dict = {
        "volumes_seen": candidates,
        "external_writable_volumes": externals,
        "external_volume_count": len(externals),
        "archive_root_env_set": bool(__import__("os").environ.get(ARCHIVE_ROOT_ENV)),
        "test_only_opt_in": __import__("os").environ.get(TEST_ONLY_ENV) == "1",
    }

    if len(externals) == 0:
        result["volume_selection"] = "none — no writable external volume is mounted"
    elif len(externals) > 1:
        result["volume_selection"] = (
            f"ambiguous — {len(externals)} writable external volumes are mounted; "
            "refusing to guess. Set ARCHIVE_ROOT explicitly."
        )
    else:
        result["volume_selection"] = f"unique external volume at {externals[0]['mount_point']}"

    try:
        root = resolve_archive_root(
            allow_nonexternal=bool(args.test_only_allow_nonexternal),
            require_writable=True,
        )
        result["archive_root"] = root.summary()
        result["archive_root_ok"] = True
        result["archive_root_error"] = None
        result["free_bytes"] = free_bytes(root.path)
        result["real_captures_permitted"] = root.is_real
    except (ArchiveRootError, ExternalVolumeError) as exc:
        result["archive_root"] = None
        result["archive_root_ok"] = False
        result["archive_root_error"] = f"{type(exc).__name__}: {exc}"
        result["free_bytes"] = None
        result["real_captures_permitted"] = False
    return result


def check_tools(cfg: dict) -> dict:
    bt = cfg.get("browsertrix", {})
    pin = resolve_image_digest(bt.get("image", ""), str(bt.get("tag", "")), pull=True)

    sf_ok, sf_reason = singlefile_available(cfg)
    sf = cfg.get("singlefile", {})
    singlefile_pin: dict = {
        "available": sf_ok,
        "reason": sf_reason or None,
        "version": sf.get("version"),
        "package": sf.get("package"),
        "pinning": "exact npm version" if not sf.get("docker_image") else "docker digest",
    }
    if sf.get("docker_image"):
        sf_image = resolve_image_digest(sf["docker_image"], sf.get("docker_tag", "") or "latest", pull=False)
        singlefile_pin["docker"] = sf_image.summary()
        singlefile_pin["digest_matches_config"] = sf_image.digest == sf.get("docker_digest")

    from archivelib.envmeta import playwright_versions

    return {
        "browsertrix": pin.summary(),
        "browsertrix_pinned": pin.resolved and bool(pin.digest),
        "singlefile": singlefile_pin,
        "playwright": playwright_versions(),
    }


def check_git_safety(repo: Path) -> dict:
    gitignore = repo / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    required = [".archive-local/", "archive/runtime/", "*.wacz", "*.warc", "*.warc.gz", "*.cdxj", "*.singlefile.html"]
    missing = [rule for rule in required if rule not in text]
    return {
        "gitignore_present": gitignore.exists(),
        "required_rules_missing": missing,
        "ok": gitignore.exists() and not missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(parser)
    args = parser.parse_args()

    repo = get_repo()
    cfg = get_config(args)

    report = {
        "schema": "archive_preflight",
        "checked_at_utc": utc_now_iso(),
        "repo": repo.name,
        "effective_config_hash": config_hash(cfg),
        "storage": check_storage(args),
        "tools": check_tools(cfg),
        "git_safety": check_git_safety(repo),
        "environment": base_environment(repo, None),
    }
    report["environment"].pop("monotonic_start", None)

    ready_for_real = bool(
        report["storage"]["real_captures_permitted"]
        and report["tools"]["browsertrix_pinned"]
        and report["git_safety"]["ok"]
        and report["environment"]["docker"]["available"]
    )
    report["ready_for_real_captures"] = ready_for_real
    report["ready_for_synthetic_tests"] = bool(
        report["tools"]["browsertrix_pinned"] and report["environment"]["docker"]["available"]
    )

    if args.json:
        emit(report, as_json=True)
    else:
        storage = report["storage"]
        print("archive preflight")
        print(f"  checked_at         : {report['checked_at_utc']}")
        print(f"  config hash        : {report['effective_config_hash'][:16]}…")
        print(f"  docker             : {report['environment']['docker'].get('server_version') or 'UNAVAILABLE'}")
        bt = report["tools"]["browsertrix"]
        print(f"  browsertrix        : {bt['image']}:{bt['tag']}")
        print(f"    digest           : {bt['digest'] or 'UNRESOLVED — ' + (bt['error'] or '')}")
        sf = report["tools"]["singlefile"]
        print(f"  singlefile         : {'available' if sf['available'] else 'unavailable'} "
              f"(v{sf['version']}, {sf['pinning']}){'' if sf['available'] else ' — ' + str(sf['reason'])}")
        pw = report["tools"]["playwright"]
        print(f"  playwright         : {'ok' if pw.get('available') else 'UNAVAILABLE'} "
              f"(python {pw.get('playwright_python')}, browser {pw.get('browser')})")
        print(f"  volumes under /Volumes : {len(storage['volumes_seen'])}")
        print(f"  external writable      : {storage['external_volume_count']} — {storage['volume_selection']}")
        if storage["archive_root_ok"]:
            root = storage["archive_root"]
            print(f"  ARCHIVE_ROOT       : {root['resolved']}  [mode={root['mode']}]")
            print(f"  free space         : {storage['free_bytes']} bytes")
        else:
            print(f"  ARCHIVE_ROOT       : NOT USABLE — {storage['archive_root_error']}")
        gs = report["git_safety"]
        print(f"  gitignore          : {'ok' if gs['ok'] else 'missing rules: ' + ', '.join(gs['required_rules_missing'])}")
        print()
        print(f"  READY FOR REAL CAPTURES : {'YES' if ready_for_real else 'NO'}")
        print(f"  READY FOR SYNTHETIC TESTS: {'YES' if report['ready_for_synthetic_tests'] else 'NO'}")
        if not ready_for_real:
            print()
            print("  To enable real captures, attach a single external writable volume and run:")
            print("    export ARCHIVE_ROOT=/Volumes/<external-volume>/LLM-APIgateways-corpus")

    return 0 if ready_for_real else 1


if __name__ == "__main__":
    run_guarded(main)
