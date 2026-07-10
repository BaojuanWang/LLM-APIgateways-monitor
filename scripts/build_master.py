#!/usr/bin/env python3
"""Build the master site table: one row per site, all sources outer-joined.

The analysis layer's foundation. It defensively merges every per-site data
source in the repo (monitor status, tech-stack, enrichment, privacy, contacts,
price, discovery) keyed on the registrable domain (eTLD+1), so ``toknex.ai``,
``www.toknex.ai`` and ``https://Api.Toknex.ai/`` all land on the same row.

Design goals (per analysis-layer work order):
  * auto-detect each source's domain column (domain / siteDomain / url / ...)
  * normalize + collapse host variants to one registrable-domain key
  * outer join — a domain present in ANY source produces a row
  * missing files / missing columns are skipped and reported, never fatal
  * every run writes a timestamped snapshot for reproducibility
  * columns are namespaced per source (``enrich__ip_asn``) to avoid collisions

Run from the repo root:
    python3 scripts/build_master.py
Outputs:
    results/master/master_table.csv                      (canonical latest)
    results/master/snapshots/master_<UTC>.csv            (immutable snapshot)
    results/master/master_coverage.csv                   (per-source coverage)
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from domain_utils import normalize_host, registrable_domain  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Candidate column names that hold a site's domain/URL, in priority order.
DOMAIN_COLUMNS = [
    "domain", "site_key", "siteDomain", "site_domain", "input_url",
    "url", "site_urls", "site", "host", "hostname",
]

# Per-source specs. ``dedup='latest'`` keeps the newest row per site by ``ts``;
# ``dedup='first'`` keeps the first seen (static one-row-per-site tables).
# ``optional`` sources simply log a note when absent.
SOURCES = [
    # Discovery-layer deliverable (may not exist yet — auto-picked up when it does).
    {"name": "disc", "path": "data/master_sites.csv", "dedup": "first", "optional": True},
    {"name": "hvoy", "path": "data/hvoy_latest.csv", "dedup": "first"},
    {"name": "manual", "path": "data/manual_sites.csv", "dedup": "first"},
    {"name": "monitor", "path": "results/monitor_results.csv", "dedup": "latest", "ts": "timestamp"},
    {"name": "enrich", "path": "data/enrichment.csv", "dedup": "first"},
    {"name": "privacy", "path": "data/privacy.csv", "dedup": "first"},
    {"name": "contacts", "path": "data/contacts.csv", "dedup": "first"},
    {"name": "ops", "path": "data/operations.csv", "dedup": "first", "optional": True},
    {"name": "price", "path": "results/model_prices/model_prices_summary.csv", "dedup": "latest", "ts": "checked_at"},
    {"name": "blocked", "path": "data/manual_confirmed_blocked.csv", "dedup": "first"},
]


def detect_domain_column(fieldnames):
    if not fieldnames:
        return None
    lowered = {f.lower().lstrip("﻿"): f for f in fieldnames}
    for cand in DOMAIN_COLUMNS:
        if cand.lower() in lowered:
            return lowered[cand.lower()]
    return None


def read_source(spec, log):
    """Return {site_key: (raw_row_dict, observed_host)} for one source, deduped."""
    path = os.path.join(BASE_DIR, spec["path"])
    if not os.path.exists(path):
        log.append((spec["name"], spec["path"], "MISSING", 0, 0))
        if not spec.get("optional"):
            print(f"  ! {spec['name']}: file missing ({spec['path']}) — skipped", file=sys.stderr)
        return {}, []

    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        dom_col = detect_domain_column(fieldnames)
        if not dom_col:
            log.append((spec["name"], spec["path"], "NO_DOMAIN_COL", 0, 0))
            print(f"  ! {spec['name']}: no domain column in {fieldnames} — skipped", file=sys.stderr)
            return {}, []

        ts_col = spec.get("ts")
        data_cols = [c for c in fieldnames if c != dom_col]
        picked = {}          # site_key -> (row, ts, observed_host)
        raw_rows = 0
        for row in reader:
            raw_rows += 1
            raw_dom = row.get(dom_col, "")
            key = registrable_domain(raw_dom)
            if not key:
                continue
            host = normalize_host(raw_dom)
            ts = (row.get(ts_col, "") or "") if ts_col else ""
            if key not in picked:
                picked[key] = (row, ts, {host})
            else:
                _, prev_ts, hosts = picked[key]
                hosts.add(host)
                if spec["dedup"] == "latest" and ts > prev_ts:
                    picked[key] = (row, ts, hosts)
                else:
                    picked[key] = (picked[key][0], prev_ts, hosts)

    log.append((spec["name"], spec["path"], "OK", raw_rows, len(picked)))
    out = {}
    for key, (row, _ts, hosts) in picked.items():
        prefixed = {f"{spec['name']}__{c}": (row.get(c, "") or "") for c in data_cols}
        prefixed[f"in_{spec['name']}"] = "1"
        out[key] = (prefixed, hosts)
    return out, data_cols


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="results/master")
    parser.add_argument("--no-snapshot", action="store_true")
    args = parser.parse_args()

    out_dir = os.path.join(BASE_DIR, args.out_dir)
    snap_dir = os.path.join(out_dir, "snapshots")
    os.makedirs(snap_dir, exist_ok=True)

    log = []                       # coverage report rows
    per_source = {}                # name -> {site_key: prefixed_cols}
    hosts_by_key = {}              # site_key -> set(observed hosts)
    ordered_columns = ["site_key", "observed_hosts"]

    print("Reading sources...")
    for spec in SOURCES:
        merged, data_cols = read_source(spec, log)
        if not merged:
            continue
        per_source[spec["name"]] = {}
        # register column order
        ordered_columns.append(f"in_{spec['name']}")
        for c in data_cols:
            ordered_columns.append(f"{spec['name']}__{c}")
        for key, (prefixed, hosts) in merged.items():
            per_source[spec["name"]][key] = prefixed
            hosts_by_key.setdefault(key, set()).update(h for h in hosts if h)
        status = [r for r in log if r[0] == spec["name"]][-1]
        print(f"  {spec['name']:9s} {status[2]:14s} raw={status[3]:6d} -> sites={status[4]}")

    all_keys = sorted(hosts_by_key)
    print(f"\nOuter-joined unique sites: {len(all_keys)}")

    # ── assemble rows ────────────────────────────────────────────────────
    rows = []
    for key in all_keys:
        row = {c: "" for c in ordered_columns}
        row["site_key"] = key
        row["observed_hosts"] = ";".join(sorted(hosts_by_key[key]))
        for name, table in per_source.items():
            if key in table:
                row.update(table[key])
        rows.append(row)

    # ── write canonical + snapshot ───────────────────────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    master_path = os.path.join(out_dir, "master_table.csv")
    _write_csv(master_path, ordered_columns, rows)
    print(f"\nWrote {master_path}")
    if not args.no_snapshot:
        snap_path = os.path.join(snap_dir, f"master_{ts}.csv")
        _write_csv(snap_path, ordered_columns, rows)
        print(f"Wrote {snap_path}")

    # ── coverage report ──────────────────────────────────────────────────
    cov_path = os.path.join(out_dir, "master_coverage.csv")
    with open(cov_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "path", "status", "raw_rows", "unique_sites",
                    "coverage_pct_of_master"])
        for name, path, status, raw, uniq in log:
            pct = f"{100 * uniq / len(all_keys):.1f}" if all_keys and uniq else "0.0"
            w.writerow([name, path, status, raw, uniq, pct])
    print(f"Wrote {cov_path}")
    print("\nCoverage (share of the master rows each source fills):")
    for name, path, status, raw, uniq in log:
        pct = f"{100 * uniq / len(all_keys):.1f}%" if all_keys and uniq else "-"
        print(f"  {name:9s} {status:14s} {uniq:5d} sites  {pct}")

    # ── verification: prove host-variant collapse ────────────────────────
    print("\nVerification — sites whose distinct hostnames collapsed to one row:")
    shown = 0
    for key in all_keys:
        hosts = sorted(hosts_by_key[key])
        if len(hosts) > 1:
            print(f"  {key:28s} <- {hosts}")
            shown += 1
            if shown >= 8:
                break
    if not shown:
        print("  (no multi-host sites in current data)")

    return 0


def _write_csv(path, columns, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
