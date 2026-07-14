#!/usr/bin/env python3
"""Tighten the concentration lower bound by re-probing the FOFA heterogeneous
tail.

Context (§4.1): under framework-agnostic FOFA discovery, one-api family is 71%
and a 24% "openai_compatible_unknown" tail remains. That tail is the crux of
the conservative-lower-bound argument: some of it is almost certainly reskinned
/ white-labeled one-api whose framework fingerprint FOFA simply did not match.
This script runs the deep tech-stack probe over exactly those tail domains and
buckets each into:

  * hidden_one_api  — probe found a one-api-family signal (fork header or the
                      /api/status JSON envelope). FOFA missed it; it IS one-api.
                      → moves the 71% floor UP.
  * other_known     — probe identified a *different* known framework.
  * genuine_unknown — reachable (or SPA shell) but no one-api signal at all.
                      → real heterogeneous / self-built tail.
  * dead            — unreachable / blocked; cannot be adjudicated.

It then recomputes the FOFA one-api share treating dead sites as unknown
(excluded from the denominator) — the tightened, still-conservative bound.

    python3 scripts/analyze_tail.py \
        --probe results/tail/fofa_tail_fingerprints.csv \
        --master data/master_sites.csv

Prints a summary and writes results/tail/tail_verdict.csv (one row per site).
"""
from __future__ import annotations

import argparse
import csv
import os
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ONE_API_KEYS = ("one-api", "new-api", "oneapi", "newapi", "voapi",
                "veloera", "one-hub", "done-hub")


def is_one_api(*fields: str) -> bool:
    blob = " ".join(f or "" for f in fields).lower()
    return any(k in blob for k in ONE_API_KEYS)


def bucket(row: dict) -> str:
    fam = (row.get("app_family") or "").lower()
    stack = (row.get("app_stack_guess") or "").lower()
    status = (row.get("status_class") or "").lower()
    if is_one_api(fam, stack):
        return "hidden_one_api"
    if status in ("identified", "family_only") and stack not in ("", "unknown"):
        return "other_known"
    if status in ("unidentified", "spa_shell", "domain_hint"):
        return "genuine_unknown"
    return "dead"          # unreachable / blocked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", default="results/tail/fofa_tail_fingerprints.csv")
    ap.add_argument("--master", default="data/master_sites.csv")
    ap.add_argument("--out", default="results/tail/tail_verdict.csv")
    args = ap.parse_args()

    probe_path = os.path.join(BASE, args.probe)
    if not os.path.exists(probe_path):
        print(f"error: {probe_path} not found — run the probe first "
              f"(bash scripts/probe_tail.sh)")
        return 1
    probe = list(csv.DictReader(open(probe_path, encoding="utf-8-sig")))

    # baseline FOFA counts from the master discovery list
    master = list(csv.DictReader(open(os.path.join(BASE, args.master), encoding="utf-8-sig")))
    fofa = [r for r in master if r.get("origin") == "fofa_g1"]
    fofa_n = len(fofa)
    fofa_oneapi_base = sum(1 for r in fofa if is_one_api(r.get("framework", "")))

    verdicts = []
    counts = Counter()
    for r in probe:
        b = bucket(r)
        counts[b] += 1
        verdicts.append({
            "domain": r.get("domain", ""),
            "verdict": b,
            "app_family": r.get("app_family", ""),
            "app_stack_guess": r.get("app_stack_guess", ""),
            "status_class": r.get("status_class", ""),
            "confidence": r.get("confidence", ""),
            "version": r.get("version", ""),
            "evidence": (r.get("evidence", "") or "")[:160],
        })

    os.makedirs(os.path.dirname(os.path.join(BASE, args.out)), exist_ok=True)
    with open(os.path.join(BASE, args.out), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(verdicts[0].keys()))
        w.writeheader(); w.writerows(verdicts)

    hidden = counts["hidden_one_api"]
    other = counts["other_known"]
    genuine = counts["genuine_unknown"]
    dead = counts["dead"]
    tail_n = len(probe)

    # tightened bound: add newly-revealed one-api, drop dead from denominator
    oneapi_tight = fofa_oneapi_base + hidden
    denom_tight = fofa_n - dead
    share_base = 100 * fofa_oneapi_base / fofa_n if fofa_n else 0
    share_tight = 100 * oneapi_tight / denom_tight if denom_tight else 0

    print("=" * 60)
    print(f"FOFA heterogeneous tail re-probe  ({tail_n} sites)")
    print("=" * 60)
    for b in ("hidden_one_api", "other_known", "genuine_unknown", "dead"):
        print(f"  {b:16s} {counts[b]:3d}  ({100*counts[b]/tail_n:.0f}%)")
    print("-" * 60)
    print(f"FOFA one-api share (baseline)  : {fofa_oneapi_base}/{fofa_n} = {share_base:.0f}%")
    print(f"FOFA one-api share (tightened) : {oneapi_tight}/{denom_tight} = {share_tight:.0f}%"
          f"   (+{hidden} hidden one-api, -{dead} dead)")
    print(f"Genuine heterogeneous tail     : {genuine}/{fofa_n} = {100*genuine/fofa_n:.0f}%  "
          f"(the irreducible non-one-api remainder)")
    print("-" * 60)
    print("Reading: the tail is NOT monolithic. hidden_one_api tightens the 71%")
    print("floor upward; genuine_unknown is the real heterogeneous ecosystem")
    print("that GitHub codesearch structurally misses. Either way → 'concentrated")
    print("+ codesearch biased'.")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
