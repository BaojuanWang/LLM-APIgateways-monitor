#!/usr/bin/env python3
"""Characterize the relay ecosystem: tech-stack taxonomy + feature distributions.

Reads the master table (scripts/build_master.py) and produces the descriptive
"what is this ecosystem made of" layer:
  * a unified per-site stack family (consolidating the discovery-layer framework,
    enrichment tech_stack, and manual labels into one taxonomy),
  * distributions over stack family, TLD, hosting ASN, signal tier, ICP filing,
    privacy-policy presence,
  * a cross-tab of stack family x operator cluster (from operator_matching),

and writes both a per-site label table and a summary. Pure local computation —
no network, no new collection.

Run from the repo root (after build_master.py, and optionally operator_matching):
    python3 scripts/site_characterization.py
Outputs:
    results/master/site_stack_labels.csv
    results/master/characterization_summary.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from domain_utils import registrable_domain  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ONE_API_FW = ("one-api", "new-api", "oneapi", "newapi", "veloera", "voapi",
              "one-hub", "done-hub", "shell-api", "super-api", "neo-api")


def stack_family(row):
    """Consolidate every available framework signal into one family label."""
    fw = (row.get("disc__framework") or "").strip().lower()
    tech = " ".join([(row.get("enrich__tech_stack") or ""),
                     (row.get("manual__tech_stack") or "")]).lower()

    if "sub2api" in fw or "sub2api" in tech:
        return "sub2api"
    if any(k in fw for k in ONE_API_FW) or any(k in tech for k in ("newapi", "oneapi", "new-api", "one-api")):
        return "one-api-family"
    if "auth2api" in fw or "auth2api" in tech:
        return "auth2api"
    if "openai_compatible" in fw:
        return "openai-compatible-unknown"
    if fw == "unknown":
        return "confirmed-unknown"
    if fw:
        return fw
    return "unlabeled"          # neither discovery nor enrichment gave a stack


def tld_of(site_key):
    reg = registrable_domain(site_key)
    return reg.rsplit(".", 1)[-1] if "." in reg else reg


def asn_provider(asn):
    """Collapse an 'AS13335 Cloudflare, Inc.' string to a short provider name."""
    a = (asn or "").strip()
    if not a:
        return ""
    # drop the leading ASxxxxx token
    parts = a.split(None, 1)
    name = parts[1] if len(parts) > 1 and parts[0].upper().startswith("AS") else a
    return name.split(",")[0].strip()[:30]


def load_operator_map(path):
    """site_key -> (operator_id, cluster_size) from operator_matching output."""
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            out[r["site_key"]] = (r.get("operator_id", ""), r.get("cluster_size", ""))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", default="results/master/master_table.csv")
    parser.add_argument("--operators", default="results/master/operator_clusters.csv")
    parser.add_argument("--out-dir", default="results/master")
    args = parser.parse_args()

    master_path = os.path.join(BASE_DIR, args.master)
    if not os.path.exists(master_path):
        print(f"error: {master_path} not found — run build_master.py first", file=sys.stderr)
        return 1
    with open(master_path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    op_map = load_operator_map(os.path.join(BASE_DIR, args.operators))

    labels = []
    for r in rows:
        key = r.get("site_key", "")
        fam = stack_family(r)
        op_id, csize = op_map.get(key, ("", ""))
        labels.append({
            "site_key": key,
            "stack_family": fam,
            "framework_raw": r.get("disc__framework", "") or r.get("enrich__tech_stack", ""),
            "tld": tld_of(key),
            "signal_tier": r.get("disc__signal_tier", ""),
            "enriched": "yes" if r.get("in_enrich") == "1" else "no",
            "hosting": asn_provider(r.get("enrich__ip_asn", "")),
            "ip_country": r.get("enrich__ip_country", ""),
            "has_privacy": r.get("privacy__has_privacy", ""),
            "icp_filing": r.get("manual__icp_filing", ""),
            "operator_id": op_id,
            "cluster_size": csize,
        })

    out_dir = os.path.join(BASE_DIR, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    labels_path = os.path.join(out_dir, "site_stack_labels.csv")
    with open(labels_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(labels[0].keys()))
        w.writeheader()
        w.writerows(labels)

    # ── distributions ────────────────────────────────────────────────────
    n = len(labels)
    enriched = [x for x in labels if x["enriched"] == "yes"]
    dists = {
        "stack_family": Counter(x["stack_family"] for x in labels),
        "tld": Counter(x["tld"] for x in labels),
        "signal_tier": Counter(x["signal_tier"] or "(none)" for x in labels),
        "hosting (enriched only)": Counter(x["hosting"] or "(unknown)" for x in enriched),
        "ip_country (enriched only)": Counter(x["ip_country"] or "(unknown)" for x in enriched),
    }

    summary_path = os.path.join(out_dir, "characterization_summary.csv")
    with open(summary_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["dimension", "value", "count", "pct_of_total"])
        for dim, ctr in dists.items():
            base = len(enriched) if "enriched only" in dim else n
            for val, cnt in ctr.most_common():
                w.writerow([dim, val, cnt, f"{100*cnt/base:.1f}"])

    # stack family x concentration (which stacks the multi-site operators use)
    fam_multi = Counter(x["stack_family"] for x in labels
                        if x["cluster_size"] and x["cluster_size"].isdigit() and int(x["cluster_size"]) > 1)

    print(f"Total sites: {n}  (enriched: {len(enriched)})")
    print(f"\nWrote {labels_path}")
    print(f"Wrote {summary_path}")

    print("\n── Stack family ─────────────────────────────")
    for val, cnt in dists["stack_family"].most_common():
        print(f"  {cnt:4d}  ({100*cnt/n:4.1f}%)  {val}")
    oaf = dists["stack_family"].get("one-api-family", 0)
    print(f"  → one-api family = {oaf}/{n} ({100*oaf/n:.0f}%) — the ecosystem's near-monoculture")

    print("\n── Top TLDs ─────────────────────────────────")
    for val, cnt in dists["tld"].most_common(10):
        print(f"  {cnt:4d}  .{val}")

    print("\n── Hosting (enriched only) ──────────────────")
    for val, cnt in dists["hosting (enriched only)"].most_common(8):
        print(f"  {cnt:4d}  {val}")

    print("\n── Sites in multi-site operators, by stack ──")
    for val, cnt in fam_multi.most_common():
        print(f"  {cnt:4d}  {val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
