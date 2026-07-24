"""Single-capture orchestration.

Order of operations matters and is fixed:

1. Build a deterministic ``capture_id`` and create its directory **fail-closed**
   (``exist_ok=False``). A capture never lands on top of an earlier one.
2. Write the effective config, seeds, Browsertrix config, and environment.
3. Run Browsertrix -> WACZ (the canonical artifact).
4. Run Playwright and SingleFile -> secondary representations.
5. Write ``capture.json``.
6. Hash everything into the manifest.
7. Validate.

A failure at step 3 or 4 does not abort the capture: a failed, blocked, or dead
site still produces a complete, manifested, validated capture directory, because
"we tried on this date and this is what we saw" is exactly the evidence a
longitudinal study needs. Only a failure to *create* the directory aborts.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .canonical import sha256_file, short_hash, write_json
from .config import config_hash
from .docker_tools import ImagePin, build_browsertrix_config, run_browsertrix
from .envmeta import base_environment, free_bytes, utc_now_compact, utc_now_iso
from .errors import CaptureError
from .manifest import generate_manifest
from .paths import ArchiveRootInfo, create_capture_dir, ensure_metadata_never_index, relative_corpus_path
from .render import render_pages, run_singlefile, singlefile_available
from .sanitize import normalize_local_path
from .seeds import SeedPlan, discovery_evidence_record
from .validate import validate_capture

_COLLECTION_SAFE = re.compile(r"[^a-z0-9-]+")


def make_capture_id(*, service_id: str, seeds: list[str], effective_config_hash: str, started_utc: str | None = None) -> str:
    """``<UTC compact>_<service_id>_<short hash>``.

    Deterministic in its inputs and collision-resistant: two captures in the
    same second for the same service still differ if their seeds or config
    differ, and the timestamp separates them otherwise.
    """
    stamp = started_utc or utc_now_compact()
    tag = short_hash(
        {"service_id": service_id, "seeds": sorted(seeds), "config": effective_config_hash, "stamp": stamp},
        length=12,
    )
    return f"{stamp}_{service_id}_{tag}"


def collection_name_for(capture_id: str) -> str:
    """Browsertrix-safe collection name derived from the capture id."""
    name = _COLLECTION_SAFE.sub("-", capture_id.lower()).strip("-")
    return name or "capture"


# Browsertrix leaves its throwaway Chrome user-data directory inside the
# collection. It is ~50 MB per crawl of bundled component-extension assets plus
# a Cookies/History/Local Storage database — none of which is evidence about the
# archived site (every byte the site served is in the WARC), and all of which is
# precisely the "Browsertrix profile" that must never leave this machine.
#
# Pruning happens BEFORE the manifest is generated, so the append-only guarantee
# is untouched: immutability begins when the capture is sealed by its manifest.
# What was pruned is recorded in capture.json rather than silently dropped.
PRUNABLE_CRAWLER_SCRATCH = ("profile",)


def prune_crawler_scratch(collection_dir: Path, capture_dir: Path) -> list[dict]:
    """Remove crawler scratch dirs from a collection; report what was removed."""
    import shutil

    removed: list[dict] = []
    if collection_dir is None or not Path(collection_dir).is_dir():
        return removed
    capture_resolved = Path(capture_dir).resolve()
    for name in PRUNABLE_CRAWLER_SCRATCH:
        target = Path(collection_dir) / name
        if not target.is_dir() or target.is_symlink():
            continue
        # Never follow a link out of the capture, and never delete outside it.
        resolved = target.resolve()
        if resolved != capture_resolved and capture_resolved not in resolved.parents:
            continue
        files = [p for p in resolved.rglob("*") if p.is_file()]
        removed.append(
            {
                "path": str(target.relative_to(capture_dir)),
                "file_count": len(files),
                "bytes": sum(p.stat().st_size for p in files if p.exists()),
                "reason": (
                    "throwaway browser user-data directory: contains no archived site "
                    "content and does contain browser state databases"
                ),
            }
        )
        shutil.rmtree(resolved, ignore_errors=True)
    return removed


@dataclass
class CaptureOutcome:
    capture_id: str
    service_id: str
    capture_dir: Path
    status: str = "unknown"
    wacz_path: Path | None = None
    wacz_sha256: str = ""
    wacz_bytes: int = 0
    manifest: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)
    capture_json: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "completed" and self.validation.get("status", "").startswith("valid")


def run_capture(
    *,
    root: ArchiveRootInfo,
    repo: Path,
    identity,
    plan: SeedPlan,
    cfg: dict,
    reason: str,
    browsertrix_pin: ImagePin,
    prior_monitor_state: dict | None = None,
    monitor_source: dict | None = None,
    dry_run: bool = False,
) -> CaptureOutcome:
    """Execute one capture end to end."""
    eff_hash = config_hash(cfg)
    started_utc = utc_now_iso()
    stamp = utc_now_compact()
    seeds = plan.seed_urls
    if not seeds:
        raise CaptureError(f"no seeds for {identity.host}; refusing to create an empty capture")

    capture_id = make_capture_id(
        service_id=identity.service_id, seeds=seeds, effective_config_hash=eff_hash, started_utc=stamp
    )
    collection = collection_name_for(capture_id)

    if dry_run:
        return CaptureOutcome(
            capture_id=capture_id,
            service_id=identity.service_id,
            capture_dir=Path("<dry-run>"),
            status="dry_run",
            capture_json={
                "capture_id": capture_id,
                "service_id": identity.service_id,
                "host": identity.host,
                "seeds": seeds,
                "collection": collection,
                "capture_reason": reason,
                "effective_config_hash": eff_hash,
            },
        )

    # --- 1. fail-closed directory creation -----------------------------
    # Best-effort Spotlight-exclusion marker at the archive root (never fatal).
    ensure_metadata_never_index(root.path)
    capture_dir = create_capture_dir(root, identity.service_id, capture_id)
    outcome = CaptureOutcome(capture_id=capture_id, service_id=identity.service_id, capture_dir=capture_dir)

    def scrub(text: str) -> str:
        return normalize_local_path(text, root=root.path)

    free_before = free_bytes(root.path)
    monotonic_start = time.monotonic()

    # --- 2. site.json + discovery evidence (service level) --------------
    service_root = capture_dir.parent.parent
    site_json = service_root / "site.json"
    if not site_json.exists():
        write_json(site_json, identity.to_site_json())

    evidence_dir = service_root / "discovery"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / "discovery_evidence.jsonl"
    record = discovery_evidence_record(
        service_id=identity.service_id,
        identity=identity,
        plan=plan,
        reason=reason,
        prior_monitor_state=prior_monitor_state,
        source_fingerprint=monitor_source or {},
    )
    record["capture_id"] = capture_id
    import json as _json

    # Append-only: discovery evidence accumulates, never rewrites.
    with open(evidence_path, "a", encoding="utf-8") as handle:
        handle.write(_json.dumps(record, ensure_ascii=False) + "\n")

    # --- 3. config artifacts -------------------------------------------
    config_dir = capture_dir / "config"
    (config_dir / "seeds.txt").write_text("\n".join(seeds) + "\n", encoding="utf-8")
    write_json(config_dir / "effective_archive_config.json", {"effective_config_hash": eff_hash, "config": cfg})

    bt_config = build_browsertrix_config(collection=collection, seeds=seeds, cfg=cfg)
    # Never let Browsertrix crawl past the seeds we chose.
    bt_config["pageLimit"] = min(int(bt_config.get("pageLimit", len(seeds))), max(len(seeds), 1))
    (config_dir / "browsertrix_config.yaml").write_text(
        yaml.safe_dump(bt_config, sort_keys=True, allow_unicode=True), encoding="utf-8"
    )

    environment = base_environment(repo, root.path)
    environment.pop("monotonic_start", None)
    environment.update(
        {
            "capture_id": capture_id,
            "service_id": identity.service_id,
            "capture_reason": reason,
            "started_utc": started_utc,
            "effective_config_hash": eff_hash,
            # The MODE is recorded, never the absolute root path: the path would
            # disclose the operator's username, and it is not a property of the
            # capture anyway — the same corpus can be migrated between disks.
            "storage_mode": root.storage_mode,
            "archive_volume": root.volume.summary() if root.volume else None,
            "free_bytes_before": free_before,
            "source_inventory": {
                "file": identity.inventory_file,
                "sha256": identity.inventory_file_sha256,
                "row_sha256": identity.inventory_row_sha256,
            },
            "monitor_source": monitor_source or {},
            "tools": {
                "browsertrix": browsertrix_pin.summary(),
                "singlefile": {
                    "enabled": bool(cfg.get("singlefile", {}).get("enabled", True)),
                    "version": cfg.get("singlefile", {}).get("version"),
                    "docker_digest": cfg.get("singlefile", {}).get("docker_digest") or None,
                },
            },
        }
    )

    # --- 4. Browsertrix ------------------------------------------------
    crawls_dir = capture_dir / "raw" / "browsertrix"
    time_limit = int(cfg.get("capture", {}).get("time_limit_seconds", 600))
    bt_result = run_browsertrix(
        pin=browsertrix_pin,
        crawls_dir=crawls_dir,
        config_path=config_dir / "browsertrix_config.yaml",
        collection=collection,
        timeout_seconds=time_limit + 300,
    )
    write_json(capture_dir / "validation" / "browsertrix_exit.json", bt_result.to_exit_json(redact=scrub))

    wacz = bt_result.wacz_path
    if wacz is None:
        # The collection directory may exist under a name Browsertrix
        # sanitized differently; look for any WACZ before concluding failure.
        found = sorted((crawls_dir / "collections").glob("*/*.wacz")) if (crawls_dir / "collections").is_dir() else []
        wacz = found[0] if found else None
    if wacz is not None and wacz.exists():
        outcome.wacz_path = wacz
        outcome.wacz_bytes = wacz.stat().st_size
        outcome.wacz_sha256 = sha256_file(wacz)
    else:
        outcome.errors.append(f"browsertrix produced no WACZ (exit {bt_result.exit_code})")

    collection_dir_for_prune = wacz.parent if wacz is not None else (crawls_dir / "collections" / collection)
    pruned_scratch = prune_crawler_scratch(collection_dir_for_prune, capture_dir)

    # --- 5. rendered outputs (secondary) --------------------------------
    rendered_dir = capture_dir / "raw" / "rendered"
    bundle = render_pages(rendered_dir=rendered_dir, seeds=plan.seeds, host=identity.host, cfg=cfg)
    if not bundle.available and bundle.error:
        outcome.errors.append(f"rendered outputs unavailable: {bundle.error}")

    sf_ok, sf_reason = singlefile_available(cfg)
    singlefile_results: list[dict] = []
    if sf_ok:
        sf_targets = plan.seeds[: int(cfg.get("rendered", {}).get("max_pages", 4))]
        for index, seed in enumerate(sf_targets, start=1):
            name = "singlefile.html" if index == 1 else f"singlefile_{index:02d}.html"
            ok, err = run_singlefile(url=seed.url, output_path=rendered_dir / name, cfg=cfg)
            singlefile_results.append({"url": seed.url, "output": name, "ok": ok, "error": err})
            if not ok:
                break  # one failure is enough; do not hammer the site
    else:
        singlefile_results.append({"ok": False, "error": sf_reason})

    # --- 6. capture.json -------------------------------------------------
    ended_utc = utc_now_iso()
    free_after = free_bytes(root.path)
    environment["free_bytes_after"] = free_after
    environment["ended_utc"] = ended_utc
    environment["duration_seconds"] = round(time.monotonic() - monotonic_start, 2)
    write_json(config_dir / "environment.json", environment)

    page_results = [p for p in bundle.pages if p.ok]
    site_condition = page_results[0].site_condition if page_results else (
        bundle.pages[0].site_condition if bundle.pages else "unknown"
    )
    status = "completed" if outcome.wacz_path else "failed_no_wacz"

    collection_dir = wacz.parent if wacz is not None else None
    capture_json = {
        "schema": "capture.schema.json",
        "capture_id": capture_id,
        "service_id": identity.service_id,
        "host": identity.host,
        "canonical_url": identity.canonical_url,
        "platform_name": identity.platform_name,
        "source": identity.source,
        "aliases": sorted(set(identity.aliases)),
        "started_utc": started_utc,
        "ended_utc": ended_utc,
        "capture_reason": reason,
        "status": status,
        "site_condition": site_condition,
        "effective_config_hash": eff_hash,
        "storage_mode": root.storage_mode,
        "code_commit_sha": (environment.get("git") or {}).get("commit_sha"),
        "seed_count": len(seeds),
        "seeds": [s.as_dict() for s in plan.seeds],
        "missing_page_types": plan.missing_page_types,
        "seed_discovery": {
            "homepage_reachable": plan.homepage_reachable,
            "probing_skipped": plan.probing_skipped,
            "probing_skipped_reason": plan.probing_skipped_reason,
            "request_timeout_seconds": plan.request_timeout_seconds,
        },
        "page_count": len(page_results),
        "collection": collection,
        "collection_relpath": (
            str(collection_dir.relative_to(capture_dir)) if collection_dir else None
        ),
        "wacz": {
            "relative_path": str(wacz.relative_to(capture_dir)) if wacz is not None else None,
            "size_bytes": outcome.wacz_bytes or None,
            "sha256": outcome.wacz_sha256 or None,
        },
        "browsertrix_exit_code": bt_result.exit_code,
        "browsertrix_timed_out": bt_result.timed_out,
        "pruned_crawler_scratch": pruned_scratch,
        "rendered": bundle.as_dict(),
        "singlefile": singlefile_results,
        "tools": environment["tools"],
        "environment_relpath": "config/environment.json",
        "source_inventory": environment["source_inventory"],
        "prior_monitor_state": prior_monitor_state or {},
        "monitor_source": monitor_source or {},
        "corpus_relpath": relative_corpus_path(root, capture_dir),
        "errors": outcome.errors,
        "immutability": (
            "This directory is append-only. Files are never regenerated in place; "
            "a retry produces a new capture_id."
        ),
    }
    write_json(capture_dir / "capture.json", capture_json)
    outcome.capture_json = capture_json
    outcome.status = status

    # --- 7. manifest + 8. validation -------------------------------------
    # Nothing is written after this point except the validation report, which is
    # excluded from the manifest by design (it is re-derivable and must stay
    # re-runnable years later). The directory digest and validation status are
    # read back from those two files by the public exporter — capture.json is
    # itself hashed and must not be rewritten.
    outcome.manifest = generate_manifest(capture_dir, capture_id=capture_id, service_id=identity.service_id)
    outcome.validation = validate_capture(capture_dir, write_report=True)
    return outcome
