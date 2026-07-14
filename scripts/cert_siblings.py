#!/usr/bin/env python3
"""Extract operator sibling domains from certificate SANs → discovery seeds.

A dedicated TLS certificate whose Subject Alternative Names list more than one
registrable domain reveals that one operator owns all of them. Those extra
domains are high-quality seeds for the discovery layer: they are provably
operator-owned, yet often absent from the current site list (e.g. a cert on
``buzzai.cc`` also covering ``buzzai.top``).

This reads the enrichment table's ``ssl_san`` / ``ssl_fingerprint`` and emits,
for every SAN entry whose registrable domain differs from its source site's, a
seed row with a full evidence chain.

Guardrails (mirror operator_matching so we never emit shared-CDN noise):
  * source sites on a CDN/cloud ASN are skipped — a Cloudflare Universal-SSL
    cert bundles many *unrelated* customer domains in one SAN (the apenft.* /
    b.ai case), which are not operator siblings;
  * as a backstop, a single cert whose SAN spans more than --max-san-domains
    distinct registrable domains is treated as a shared cert and skipped.

Output is seed-ready: the ``domain`` column is normalized (scheme/www/path
stripped, lower-cased, wildcard ``*.`` removed) to match the discovery-layer
seed format, with an ``already_in_seed`` flag so knowns can be filtered out.

Run from the repo root:
    python3 scripts/cert_siblings.py
    python3 scripts/cert_siblings.py --self-test
Output:
    results/master/cert_sibling_seeds.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from domain_utils import normalize_host, registrable_domain  # noqa: E402
from operator_matching import CLOUD_ASN_HINTS                # noqa: E402  (DRY)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MAX_SAN_DOMAINS = 6   # a SAN spanning more distinct regs = shared cert

OUT_FIELDS = [
    "domain",                    # normalized sibling host — seed-ready
    "registrable_domain",
    "already_in_seed",
    "source_site",               # known site whose cert revealed the sibling
    "source_cert_fingerprint",   # evidence: the exact cert
    "san_entry",                 # evidence: the raw SAN name it came from
    "discovery_method",
]


def is_cloud(asn: str) -> bool:
    a = (asn or "").lower()
    return any(hint in a for hint in CLOUD_ASN_HINTS)


def strip_wildcard(name: str) -> str:
    name = (name or "").strip().lower()
    if name.startswith("*."):
        name = name[2:]
    return normalize_host(name)


def seed_domain(name: str) -> str:
    """Seed-ready host: wildcard + scheme/path/port stripped, leading www dropped
    (other meaningful sub-domains like ``api.`` are kept)."""
    host = strip_wildcard(name)
    if host.startswith("www."):
        host = host[4:]
    return host


def extract(rows, max_san_domains):
    """Yield sibling seed rows. ``rows`` are enrichment dict rows."""
    seed_keys = {registrable_domain(r.get("domain", "")) for r in rows}
    seed_keys.discard("")

    stats = {"certs_seen": 0, "certs_cdn_skipped": 0, "certs_shared_skipped": 0,
             "sibling_rows": 0}
    # dedup on (sibling_domain, source_site)
    seen_pairs = set()
    out = []

    for r in rows:
        san_raw = (r.get("ssl_san") or "").strip()
        if not san_raw:
            continue
        stats["certs_seen"] += 1
        src_domain = normalize_host(r.get("domain", ""))
        src_key = registrable_domain(r.get("domain", ""))
        fp = (r.get("ssl_fingerprint") or "").strip()

        # Guardrail 1 — skip CDN-fronted sources (shared CDN cert).
        if is_cloud(r.get("ip_asn", "")):
            stats["certs_cdn_skipped"] += 1
            continue

        entries = [e for e in (p.strip() for p in san_raw.split(";")) if e]
        regs_in_cert = {registrable_domain(strip_wildcard(e)) for e in entries}
        regs_in_cert.discard("")
        # Guardrail 2 — a cert spanning many registrable domains is a shared cert.
        if len(regs_in_cert) > max_san_domains:
            stats["certs_shared_skipped"] += 1
            continue

        for entry in entries:
            host = seed_domain(entry)
            reg = registrable_domain(host)
            if not host or not reg:
                continue
            if reg == src_key:               # the site's own domain — not a sibling
                continue
            pair = (host, src_domain)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            stats["sibling_rows"] += 1
            out.append({
                "domain": host,
                "registrable_domain": reg,
                "already_in_seed": "yes" if reg in seed_keys else "no",
                "source_site": src_domain,
                "source_cert_fingerprint": fp,
                "san_entry": entry,
                "discovery_method": "cert_san",
            })

    # new (not yet tracked) first, then alphabetical — ready to hand off as seeds
    out.sort(key=lambda x: (x["already_in_seed"] == "yes", x["domain"]))
    return out, stats


def self_test() -> None:
    rows = [
        # independent cert covering a sibling -> should surface buzzai.top
        {"domain": "buzzai.cc", "ip_asn": "AS111 Real Hosting",
         "ssl_fingerprint": "FP1", "ssl_san": "*.buzzai.cc;buzzai.cc;buzzai.top;*.buzzai.top"},
        # CDN cert bundling unrelated domains -> must be skipped entirely
        {"domain": "b.ai", "ip_asn": "AS13335 Cloudflare, Inc.",
         "ssl_fingerprint": "FPCF", "ssl_san": "b.ai;apenft.io;apenft.org;ainft.com"},
        # single-domain cert -> no sibling
        {"domain": "solo.io", "ip_asn": "AS222 Real",
         "ssl_fingerprint": "FP2", "ssl_san": "*.solo.io;solo.io"},
    ]
    out, stats = extract(rows, DEFAULT_MAX_SAN_DOMAINS)
    domains = {r["domain"] for r in out}
    assert domains == {"buzzai.top"}, out
    assert out[0]["source_site"] == "buzzai.cc"
    assert out[0]["already_in_seed"] == "no"
    assert stats["certs_cdn_skipped"] == 1, stats
    assert not any("apenft" in r["domain"] for r in out), "CDN SAN must be excluded"
    print("self-test passed: independent-cert siblings extracted; CDN cert excluded")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enrichment", default="data/enrichment.csv")
    parser.add_argument("--out", default="results/master/cert_sibling_seeds.csv")
    parser.add_argument("--max-san-domains", type=int, default=DEFAULT_MAX_SAN_DOMAINS)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    path = os.path.join(BASE_DIR, args.enrichment)
    if not os.path.exists(path):
        print(f"error: {path} not found", file=sys.stderr)
        return 1
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    out, stats = extract(rows, args.max_san_domains)
    out_path = os.path.join(BASE_DIR, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
        w.writeheader()
        w.writerows(out)

    new = [r for r in out if r["already_in_seed"] == "no"]
    print(f"certs examined:            {stats['certs_seen']}")
    print(f"  skipped (CDN source):    {stats['certs_cdn_skipped']}")
    print(f"  skipped (shared cert):   {stats['certs_shared_skipped']}")
    print(f"sibling domains found:     {len(out)}")
    print(f"  NEW (not in seed):       {len(new)}")
    print(f"\nWrote {out_path}")
    if new:
        print("\nNew sibling seeds (hand to discovery layer):")
        for r in new:
            print(f"  {r['domain']:24s} <- {r['source_site']}  (cert {r['source_cert_fingerprint'][:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
