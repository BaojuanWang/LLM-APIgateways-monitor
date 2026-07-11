#!/usr/bin/env python3
"""Capstone per-site classification — joins every analysis output into one
labelled row per site. Run last; rerun on new data and it just works.

Dimensions (each documented inline):
  * stack_family       — software family (site_characterization)
  * site_role          — relay / conversion_layer / aggregator / unidentified
  * hosting_type       — cdn_fronted / direct_origin / unknown
  * maturity_tier      — established (≤2024) / growing_2025 / new_2026 / unknown
  * health             — liveness bucket
  * operator_id/size   — operator grouping (operator_matching)
  * multi_brand        — operator runs >1 distinct brand name
  * template_family    — similarity cluster (site_similarity)
  * birth_year, dedicated_cert, and business signals when available.

    python3 scripts/classify_sites.py   # -> results/master/site_classification.csv
"""
from __future__ import annotations
import csv, os, sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")

CLOUD = ["cloudflare", "amazon", "google", "akamai", "fastly", "alibaba",
         "tencent", "ovh", "microsoft", "linode", "digitalocean", "netlab"]


def g(r, c):
    return (r.get(c) or "").strip()


def load(name):
    p = os.path.join(M, name)
    return list(csv.DictReader(open(p, encoding="utf-8-sig"))) if os.path.exists(p) else []


def site_role(stack, framework):
    f = (framework or "").lower()
    if stack in ("sub2api", "auth2api") or "2api" in f and "sub2api" in f:
        return "conversion_layer"
    if "all-api-hub" in f or "metapi" in f or stack == "aggregator":
        return "aggregator"
    if stack == "one-api-family":
        return "relay"
    if stack in ("openai-compatible-unknown", "confirmed-unknown", "unlabeled"):
        return "unidentified"
    return stack or "unidentified"


def hosting_type(asn, ip):
    if asn and any(h in asn.lower() for h in CLOUD):
        return "cdn_fronted"
    if ip:
        return "direct_origin"
    return "unknown"


def maturity(birth, has_cert):
    if not birth.isdigit():
        return "unknown"
    y = int(birth)
    if y <= 2024:
        return "established"
    if y == 2025:
        return "growing_2025"
    if y >= 2026:
        return "new_2026"
    return "unknown"


def main():
    master = {r["site_key"]: r for r in load("master_table.csv")}
    labels = {r["site_key"]: r for r in load("site_stack_labels.csv")}

    # operator -> (size, multi_brand)
    op_multi = {}
    for r in load("operator_profiles.csv"):
        names = [n for n in g(r, "platform_names").split(";") if n]
        op_multi[r["operator_id"]] = (r.get("domain_count", ""), "Y" if len(set(names)) > 1 else "")

    # site -> template family id
    tfam = {}
    for r in load("site_similarity_clusters.csv"):
        for m in g(r, "members").split(";"):
            tfam[m] = r["family_id"]

    rows = []
    for key, r in master.items():
        lb = labels.get(key, {})
        stack = lb.get("stack_family", "")
        birth = (g(r, "enrich__whois_reg_date") or g(r, "enrich__ssl_not_before"))[:4]
        has_cert = bool(g(r, "enrich__ssl_fingerprint"))
        op = lb.get("operator_id", "")
        size, multi = op_multi.get(op, (lb.get("cluster_size", ""), ""))
        rows.append({
            "domain": key,
            "stack_family": stack,
            "site_role": site_role(stack, g(r, "disc__framework")),
            "hosting_type": hosting_type(g(r, "enrich__ip_asn"), g(r, "enrich__ip")),
            "maturity_tier": maturity(birth, has_cert),
            "health": lb.get("", "") or g(r, "monitor__online_status") or ("https_alive" if has_cert else "unknown"),
            "birth_year": birth if birth.isdigit() else "",
            "dedicated_cert": "Y" if has_cert else "",
            "operator_id": op,
            "operator_domains": size,
            "multi_brand_operator": multi,
            "template_family": tfam.get(key, ""),
            "payment_methods": g(r, "ops__payment_methods"),
            "has_faka": g(r, "ops__has_faka"),
            "trust_claims": g(r, "ops__trust_claims"),
        })

    cols = ["domain", "stack_family", "site_role", "hosting_type", "maturity_tier",
            "health", "birth_year", "dedicated_cert", "operator_id", "operator_domains",
            "multi_brand_operator", "template_family", "payment_methods", "has_faka", "trust_claims"]
    out = os.path.join(M, "site_classification.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

    print(f"Wrote {out}  ({len(rows)} sites)")
    for dim in ("site_role", "hosting_type", "maturity_tier"):
        c = Counter(x[dim] for x in rows)
        print(f"  {dim}: " + " · ".join(f"{k} {v}" for k, v in c.most_common()))


if __name__ == "__main__":
    main()
