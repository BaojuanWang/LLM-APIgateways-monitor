#!/usr/bin/env python3
"""Operator matching: collapse many domains into few operators.

Reads the master table (scripts/build_master.py) and unions sites that share
operator-linking signals into "operator clusters" via a union-find. This is the
engine behind the "apparent diversity vs structural concentration" finding:
report N domains -> M operators, largest cluster, and the HHI concentration
index (cf. Zembruzki et al., Hosting Industry Centralization, 2022; see
docs/METHODS_literature_grounding_2026-07-08.md §4–5).

Signals, by reliability (strongest first):
  1. same TLS certificate fingerprint         — STRONG, unfiltered
  2. shared certificate SAN domain            — STRONG, unfiltered
  3. same favicon hash (non-generic)          — MEDIUM, frequency-filtered
  4. same origin IP                           — MEDIUM, frequency-filtered
  5. shared contact handle (TG/QQ/WeChat/…)   — MEDIUM, frequency-filtered
ASN is recorded as annotation only and is NOT a merge edge: hosting/CDN ASNs are
shared by hundreds of unrelated sites (43.5% of this dataset sits on Cloudflare
AS13335), so unioning on ASN would fuse the whole population into one blob.

Anti-over-merge guardrails:
  * the single most common favicon hash (the one-api default icon, ~35% of
    sites) is auto-detected and excluded from favicon edges;
  * any MEDIUM signal value shared by more than --max-share distinct sites is
    treated as too-generic and dropped;
  * cert edges are trusted unfiltered (a cert covering many domains genuinely is
    one operator), but a cap still guards against pathological shared wildcards.

Cert signals are optional: they activate automatically once enrich.py has
populated ssl_fingerprint / ssl_san. Until then matching falls back to
favicon + IP + contacts.

Run from the repo root (after build_master.py):
    python3 scripts/operator_matching.py
Outputs:
    results/master/operator_clusters.csv   (site -> operator_id + basis)
    results/master/operator_summary.csv    (concentration metrics)
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from domain_utils import registrable_domain  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Frequency cap for MEDIUM signals (favicon / IP / contact). A value shared by
# more sites than this is treated as generic infrastructure, not an operator tie.
DEFAULT_MAX_SHARE = 8
CONTACT_MAX_SHARE = 10          # contacts get a slightly higher cap
CERT_MAX_SHARE = 40             # certs are strong, but cap pathological wildcards
SITENAME_MAX_SHARE = 12         # a distinctive shared operator name is a strong tie
GENERIC_FAVICON_PCT = 15.0      # a favicon covering >this% of sites is "default"

# Non-identifying / software-default display names — a shared value here is NOT
# an operator tie (e.g. "new api" is the default one-api/new-api install name,
# seen on 21 unrelated domains in the 764 set).
GENERIC_SITE_NAMES = {
    "", "-", "n/a", "na", "none", "null", "unknown", "api", "ai", "gpt",
    "new api", "one api", "new-api", "one-api", "newapi", "oneapi",
    "chatgpt", "openai", "chat", "home", "index", "login", "dashboard",
}

# Known cloud / CDN ASNs — annotation only (never a merge edge).
CLOUD_ASN_HINTS = [
    "cloudflare", "amazon", "google", "microsoft", "akamai", "fastly",
    "alibaba", "tencent", "ovh", "digitalocean", "linode", "hetzner",
    "vultr", "netlab",
]

# Column suffixes we look for in the master table (namespaced as source__col).
SIG_SUFFIXES = {
    "cert_fp":  ["ssl_fingerprint", "cert_fingerprint"],
    "cert_san": ["ssl_san", "cert_san"],
    "favicon":  ["favicon_hash", "favicon_group"],
    "ip":       ["__ip"],           # exact match handled below
    "asn":      ["ip_asn"],
    "telegram": ["telegram", "contact_telegram"],
    "qq":       ["qq_group", "contact_qq"],
    "wechat":   ["wechat"],
    "discord":  ["discord"],
    "sitename": ["platform_name", "verified_site_name", "site_name", "sitename"],
}


class DSU:
    def __init__(self):
        self.parent = {}
        self.basis = defaultdict(set)   # frozenset(pair) -> {(sig_type, value)}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b, sig_type, value):
        ra, rb = self.find(a), self.find(b)
        self.basis[frozenset((a, b))].add((sig_type, value))
        if ra != rb:
            self.parent[ra] = rb


def _find_columns(fieldnames, suffixes):
    cols = []
    for f in fieldnames:
        fl = f.lower()
        for suf in suffixes:
            if suf.startswith("__"):
                if fl.endswith(suf.lstrip("_")):
                    cols.append(f)
            elif fl.endswith(suf) or fl == suf:
                cols.append(f)
    return cols


def load_signals(master_path):
    with open(master_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        colmap = {sig: _find_columns(fields, sufs) for sig, sufs in SIG_SUFFIXES.items()}
        # exact ip column: prefer '<src>__ip' not '..._city' etc.
        colmap["ip"] = [f for f in fields if f.lower().endswith("__ip")]
        sites = {}
        for row in reader:
            key = row.get("site_key") or ""
            if not key:
                continue
            sig = {}
            for sigtype, cols in colmap.items():
                vals = [row.get(c, "").strip() for c in cols if row.get(c, "").strip()]
                sig[sigtype] = vals
            sites[key] = sig
    return sites, colmap


def _value_to_sites(sites, sigtype, transform=None, exclude=None):
    """Map signal value -> set of site_keys that carry it.

    ``exclude`` is a set of site_keys whose value for this signal must be
    ignored (used to drop CDN-fronted sites from IP edges).
    """
    exclude = exclude or set()
    idx = defaultdict(set)
    for key, sig in sites.items():
        if key in exclude:
            continue
        for v in sig.get(sigtype, []):
            for token in (transform(v) if transform else [v]):
                if token:
                    idx[token].add(key)
    return idx


def _cloud_fronted_sites(sites):
    """Sites whose ASN is a CDN/cloud edge — their observed IP is NOT an origin,
    so it must not be used as an operator-linking signal."""
    cloud = set()
    for key, sig in sites.items():
        for asn in sig.get("asn", []):
            if any(hint in asn.lower() for hint in CLOUD_ASN_HINTS):
                cloud.add(key)
                break
    return cloud


def _san_tokens(san_value):
    return {registrable_domain(part) for part in san_value.split(";") if part.strip()}


def _sitename_tokens(value):
    """Normalize an operator display name; drop generic / software-default names."""
    v = re.sub(r"\s+", " ", (value or "").strip().lower())
    if not v or len(v) < 3 or v in GENERIC_SITE_NAMES:
        return []
    return [v]


def build_operators(sites, max_share, verbose=True):
    dsu = DSU()
    for key in sites:
        dsu.find(key)   # ensure singletons are tracked

    dropped = defaultdict(list)   # sigtype -> [(value, n_sites)]

    def apply_edges(sigtype, index, cap, label):
        for value, members in index.items():
            n = len(members)
            if n < 2:
                continue
            if n > cap:
                dropped[label].append((value, n))
                continue
            members = sorted(members)
            for other in members[1:]:
                dsu.union(members[0], other, label, value)

    # CDN-fronted sites present the CDN's certificate (e.g. Cloudflare Universal
    # SSL bundles many unrelated customer domains on one shared cert + SAN), so
    # they must be excluded from cert edges — the same failure mode as CDN edge
    # IPs. A dedicated-cert operator behind a CDN loses the cert tie here, which
    # is the conservative side to err on ("prefer dispersion over wrong merges").
    cloud_sites = _cloud_fronted_sites(sites)
    if verbose and cloud_sites:
        print(f"  excluded {len(cloud_sites)} CDN-fronted site(s) from cert + IP edges "
              f"(shared CDN cert/edge IP is not an operator tie)")

    # ── STRONG: certificate fingerprint + SAN (direct-origin sites only) ─────
    apply_edges("cert_fp", _value_to_sites(sites, "cert_fp", exclude=cloud_sites), CERT_MAX_SHARE, "cert_fp")
    apply_edges("cert_san", _value_to_sites(sites, "cert_san", _san_tokens, exclude=cloud_sites), CERT_MAX_SHARE, "cert_san")

    # ── MEDIUM: favicon (drop the auto-detected default), IP, contacts ───────
    favicon_idx = _value_to_sites(sites, "favicon")
    generic_favicons = set()
    if sites:
        counts = Counter()
        for v, m in favicon_idx.items():
            counts[v] = len(m)
        for v, n in counts.items():
            if 100.0 * n / len(sites) >= GENERIC_FAVICON_PCT:
                generic_favicons.add(v)
    favicon_idx = {v: m for v, m in favicon_idx.items() if v not in generic_favicons}
    apply_edges("favicon", favicon_idx, max_share, "favicon")
    # IP edges only for direct-origin sites (cloud_sites excluded above).
    apply_edges("ip", _value_to_sites(sites, "ip", exclude=cloud_sites), max_share, "ip")
    for ctype in ("telegram", "qq", "wechat", "discord"):
        apply_edges(ctype, _value_to_sites(sites, ctype), CONTACT_MAX_SHARE, ctype)

    # A distinctive shared operator display name (e.g. "ePhone AI" across three
    # domains) is one of the strongest identity ties; generic/default names are
    # dropped by _sitename_tokens, and a frequency cap guards the rest.
    apply_edges("sitename", _value_to_sites(sites, "sitename", _sitename_tokens),
                SITENAME_MAX_SHARE, "sitename")

    # ── assemble clusters ────────────────────────────────────────────────
    clusters = defaultdict(list)
    for key in sites:
        clusters[dsu.find(key)].append(key)
    # stable operator id = lexicographically smallest member
    operators = {}
    for members in clusters.values():
        members = sorted(members)
        operators[members[0]] = members

    if verbose and generic_favicons:
        print(f"  auto-excluded generic favicon(s): "
              f"{sorted(generic_favicons)} (>= {GENERIC_FAVICON_PCT}% of sites)")
    if verbose:
        for label, items in dropped.items():
            top = sorted(items, key=lambda x: -x[1])[:3]
            shown = ", ".join(f"{v[:22]}({n})" for v, n in top)
            print(f"  frequency-filtered {label}: {len(items)} value(s) too generic  e.g. {shown}")

    return operators, dsu


def cluster_basis(members, dsu):
    sigs = set()
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            sigs |= dsu.basis.get(frozenset((members[i], members[j])), set())
    # summarize by signal type
    by_type = defaultdict(set)
    for stype, val in sigs:
        by_type[stype].add(val)
    return "; ".join(f"{t}={sorted(v)[:2]}" for t, v in sorted(by_type.items()))


def hhi(sizes, total):
    frac = sum((s / total) ** 2 for s in sizes) if total else 0.0
    return frac, frac * 10000


def self_test() -> None:
    """Verify cert edges + the CDN-cert guardrail on controlled synthetic data.

    Certs cannot be collected in a TLS-intercepting sandbox (the proxy re-signs
    every host), so this fixture stands in for a real enrich pass to prove the
    matching logic before real data lands.
    """
    def site(**kw):
        base = {k: [] for k in SIG_SUFFIXES}
        for k, v in kw.items():
            base[k] = v if isinstance(v, list) else [v]
        return base

    sites = {
        # Operator A — two direct-origin domains on the SAME certificate.
        "a1.com": site(cert_fp="FP_A", cert_san="a1.com;a2.com", asn="AS111 Real Hosting"),
        "a2.com": site(cert_fp="FP_A", cert_san="a1.com;a2.com", asn="AS111 Real Hosting"),
        # Operator B — linked only by a shared SAN entry (no fp overlap).
        "b1.net": site(cert_san="b1.net;b2.net", asn="AS222 Real Hosting"),
        "b2.net": site(cert_san="b1.net;b2.net", asn="AS222 Real Hosting"),
        # Two UNRELATED Cloudflare sites on a shared CF Universal-SSL cert
        # (same fp + shared SAN). Must NOT merge — CF is excluded from cert edges.
        "cf1.com": site(cert_fp="FP_CF", cert_san="cf1.com;cf2.com;stranger.org", asn="AS13335 Cloudflare, Inc."),
        "cf2.com": site(cert_fp="FP_CF", cert_san="cf1.com;cf2.com;stranger.org", asn="AS13335 Cloudflare, Inc."),
        # A lone site.
        "solo.io": site(asn="AS333 Real Hosting"),
    }
    operators, dsu = build_operators(sites, DEFAULT_MAX_SHARE, verbose=False)
    op_of = {m: op for op, members in operators.items() for m in members}

    assert op_of["a1.com"] == op_of["a2.com"], "cert fingerprint should merge A"
    assert op_of["b1.net"] == op_of["b2.net"], "shared SAN should merge B"
    assert op_of["cf1.com"] != op_of["cf2.com"], "CF shared cert must NOT merge"
    assert op_of["a1.com"] != op_of["b1.net"], "A and B are distinct operators"
    assert len([m for m in operators if len(operators[m]) == 1]) == 3, "cf1, cf2, solo stay singletons"

    # Site-name scenario: a distinctive shared name merges across registrable
    # domains; a generic software-default name does not.
    named = {
        "ephone.ai":   site(sitename="ePhone AI"),
        "ephone.chat": site(sitename="ePhone AI"),
        "innk.cc":     site(sitename="ePhone AI"),
        "g1.com":      site(sitename="New API"),   # default install name -> generic
        "g2.com":      site(sitename="New API"),
    }
    ops2, _ = build_operators(named, DEFAULT_MAX_SHARE, verbose=False)
    op2 = {m: op for op, members in ops2.items() for m in members}
    assert op2["ephone.ai"] == op2["ephone.chat"] == op2["innk.cc"], "distinctive name must merge"
    assert op2["g1.com"] != op2["g2.com"], "generic default name must NOT merge"

    print("self-test passed: cert edges merge direct-origin operators; "
          "CDN-cert guardrail blocks Cloudflare false merges; "
          "distinctive site-name merges, generic name does not")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true",
                        help="Run the synthetic cert-matching verification and exit.")
    parser.add_argument("--master", default="results/master/master_table.csv")
    parser.add_argument("--out-dir", default="results/master")
    parser.add_argument("--max-share", type=int, default=DEFAULT_MAX_SHARE,
                        help="Drop a MEDIUM signal value shared by more than N sites.")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    master_path = os.path.join(BASE_DIR, args.master)
    if not os.path.exists(master_path):
        print(f"error: {master_path} not found — run build_master.py first", file=sys.stderr)
        return 1

    sites, colmap = load_signals(master_path)
    total = len(sites)
    print(f"Loaded {total} sites from {args.master}")
    active = {k: v for k, v in colmap.items() if v}
    print("Signal columns detected:")
    for sig, cols in active.items():
        print(f"  {sig:9s} <- {cols}")
    missing = [s for s in ("cert_fp", "cert_san") if not colmap.get(s)]
    if missing:
        print(f"  note: {missing} not populated yet — cert edges will activate "
              f"after an enrich.py run. Falling back to favicon/IP/contacts.")

    print("\nMatching...")
    operators, dsu = build_operators(sites, args.max_share)

    sizes = sorted((len(m) for m in operators.values()), reverse=True)
    multi = [s for s in sizes if s > 1]
    frac, idx = hhi(sizes, total)

    # ── write clusters ───────────────────────────────────────────────────
    out_dir = os.path.join(BASE_DIR, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    clusters_path = os.path.join(out_dir, "operator_clusters.csv")
    with open(clusters_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["site_key", "operator_id", "cluster_size", "merge_basis"])
        for op_id, members in sorted(operators.items(), key=lambda kv: -len(kv[1])):
            basis = cluster_basis(members, dsu) if len(members) > 1 else ""
            for m in members:
                w.writerow([m, op_id, len(members), basis])
    print(f"\nWrote {clusters_path}")

    # ── summary metrics ──────────────────────────────────────────────────
    summary_path = os.path.join(out_dir, "operator_summary.csv")
    with open(summary_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "value"])
        w.writerow(["total_domains", total])
        w.writerow(["distinct_operators", len(operators)])
        w.writerow(["multi_site_operators", len(multi)])
        w.writerow(["singletons", len(sizes) - len(multi)])
        w.writerow(["largest_operator_domains", sizes[0] if sizes else 0])
        w.writerow(["compression_ratio", f"{total / len(operators):.2f}" if operators else "0"])
        w.writerow(["hhi_fraction", f"{frac:.4f}"])
        w.writerow(["hhi_index_10000", f"{idx:.0f}"])
    print(f"Wrote {summary_path}")

    print("\n── Concentration summary ─────────────────────────────")
    print(f"  {total} domains -> {len(operators)} operators "
          f"(compression {total / len(operators):.2f}x)" if operators else "  no data")
    print(f"  multi-site operators: {len(multi)}   singletons: {len(sizes) - len(multi)}")
    print(f"  largest operator: {sizes[0] if sizes else 0} domains")
    print(f"  HHI: {frac:.4f} (index {idx:.0f}; >0.25 / 2500 = highly concentrated)")

    print("\n── Multi-site operators (manual spot-check) ──────────")
    shown = 0
    for op_id, members in sorted(operators.items(), key=lambda kv: -len(kv[1])):
        if len(members) < 2:
            continue
        basis = cluster_basis(members, dsu)
        flag = "  ⚠ LARGE — verify not over-merged" if len(members) > 15 else ""
        print(f"  [{len(members):2d}] {op_id}{flag}")
        print(f"       members: {members[:8]}{' …' if len(members) > 8 else ''}")
        print(f"       basis:   {basis}")
        shown += 1
        if shown >= 12:
            print("  … (see operator_clusters.csv for the rest)")
            break
    if not shown:
        print("  (no multi-site operators found with current signals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
