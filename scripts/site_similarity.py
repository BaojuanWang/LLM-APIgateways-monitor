#!/usr/bin/env python3
"""Site similarity clustering — deployment-template / shared-infrastructure families.

Groups sites by *shared distinctive features* rather than by proven common
ownership. Where operator_matching.py answers "same owner?" (strong identity
signals), this answers "configured/deployed alike?" — a coarser grouping that
surfaces shared deployment templates and reseller infrastructure, which may span
more than one operator.

Method (Jaccard / feature-overlap clustering, a standard technique for grouping
web infrastructure and phishing-kit families — see docs/METHODS_element_citations.md
§D1/§D7, e.g. "Phishing Site Detection Using Similarity of Website Structure" and
Jaccard clustering of web/host features):

  1. Represent each site as a set of typed feature tokens (favicon, non-CDN ASN,
     origin IP, registrar, server header, frontend tech).
  2. Keep only *distinctive* tokens — shared by between 2 and --max-df sites.
     Ubiquitous tokens (Cloudflare, the one-api default favicon, Let's Encrypt)
     are non-discriminative and excluded, which is what prevents one giant blob.
  3. Link two sites that share at least --min-shared distinctive tokens; take
     connected components as template families.

Output: results/master/site_similarity_clusters.csv

    python3 scripts/site_similarity.py
"""
from __future__ import annotations
import argparse, csv, itertools, os, sys
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")

CLOUD = ["cloudflare", "amazon", "google", "akamai", "fastly", "alibaba",
         "tencent", "ovh", "microsoft", "linode", "digitalocean"]
DEFAULT_FAVICON = "0d919cd7c5fa"   # one-api default icon — non-discriminative


def g(r, c):
    return (r.get(c) or "").strip()


def is_cloud(asn):
    return any(h in asn.lower() for h in CLOUD)


def feature_tokens(r):
    T = set()
    fav = g(r, "enrich__favicon_hash")
    if fav and fav != DEFAULT_FAVICON:
        T.add("favicon:" + fav)
    asn = g(r, "enrich__ip_asn")
    ip = g(r, "enrich__ip")
    if asn and not is_cloud(asn):
        T.add("asn:" + asn.split(None, 1)[-1][:18])
        if ip:
            T.add("ip:" + ip)
    reg = g(r, "enrich__whois_registrar")
    if reg:
        T.add("registrar:" + reg[:20])
    srv = g(r, "enrich__server_header")
    if srv:
        T.add("server:" + srv.split("/")[0].split()[0].lower()[:14])
    for t in g(r, "enrich__tech_stack").split(","):
        t = t.strip().lower()
        if t and t != "cloudflare":
            T.add("tech:" + t)
    return T


class DSU:
    def __init__(self): self.p = {}
    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b): self.p[self.find(a)] = self.find(b)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-df", type=int, default=25,
                    help="A feature shared by more than this many sites is too common to link on.")
    ap.add_argument("--min-shared", type=int, default=2,
                    help="Sites must share at least this many distinctive features to link.")
    args = ap.parse_args()

    master = list(csv.DictReader(open(os.path.join(M, "master_table.csv"), encoding="utf-8-sig")))
    labels = {r["site_key"]: r for r in csv.DictReader(open(os.path.join(M, "site_stack_labels.csv"), encoding="utf-8-sig"))}
    toks = {r["site_key"]: feature_tokens(r) for r in master}

    df = Counter(t for T in toks.values() for t in T)
    dist = {t for t, c in df.items() if 2 <= c <= args.max_df}

    tok2sites = defaultdict(list)
    for k, T in toks.items():
        for t in (T & dist):
            tok2sites[t].append(k)

    pair = Counter()
    for sites in tok2sites.values():
        for a, b in itertools.combinations(sorted(sites), 2):
            pair[(a, b)] += 1

    dsu = DSU()
    for k in toks:
        dsu.find(k)
    for (a, b), c in pair.items():
        if c >= args.min_shared:
            dsu.union(a, b)

    comp = defaultdict(list)
    for k in toks:
        comp[dsu.find(k)].append(k)
    fams = sorted((m for m in comp.values() if len(m) > 1), key=len, reverse=True)

    rows = []
    for members in fams:
        members = sorted(members)
        shared = set.intersection(*[toks[m] for m in members]) & dist
        stacks = Counter(labels[m]["stack_family"] for m in members if m in labels)
        rows.append({
            "family_id": members[0],
            "size": len(members),
            "shared_features": ";".join(sorted(shared)) or "(仅两两共享,无全组公共)",
            "stack_families": ";".join(f"{k}:{v}" for k, v in stacks.most_common()),
            "members": ";".join(members),
        })

    out = os.path.join(M, "site_similarity_clusters.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["family_id", "size", "shared_features", "stack_families", "members"])
        w.writeheader(); w.writerows(rows)

    covered = sum(len(m) for m in fams)
    print(f"Wrote {out}")
    print(f"  {len(fams)} template families (>1 site) covering {covered}/{len(toks)} sites")
    print(f"  distinctive features used: {len(dist)}  (max_df={args.max_df}, min_shared={args.min_shared})")
    for r in rows[:10]:
        print(f"  [{r['size']:2d}] {r['shared_features'][:52]:52s} {r['members'][:44]}")


if __name__ == "__main__":
    main()
