#!/usr/bin/env python3
"""Operator profiles + favicon families — deepen the 'structure' narrative.

Two CSVs from existing data (no network):
  * operator_profiles.csv — one row per multi-site operator, with aggregated
    features (stack, hosting, countries, birth range, which signals tied them).
  * favicon_families.csv  — each non-default favicon hash shared by >1 site, its
    members and stacks (template / operator families; the one-api default icon
    is flagged, not treated as a family).

    python3 scripts/operator_profiles.py
"""
from __future__ import annotations
import csv, os, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")


def g(r, c):
    return (r.get(c) or "").strip()


def yr(r):
    d = g(r, "enrich__whois_reg_date") or g(r, "enrich__ssl_not_before")
    return d[:4] if d[:4].isdigit() else ""


def short_asn(a):
    a = a.strip()
    if not a: return ""
    p = a.split(None, 1)
    return (p[1] if len(p) > 1 and p[0].upper().startswith("AS") else a).split(",")[0].strip()[:24]


def main():
    master = list(csv.DictReader(open(os.path.join(M, "master_table.csv"), encoding="utf-8-sig")))
    labels = {r["site_key"]: r for r in csv.DictReader(open(os.path.join(M, "site_stack_labels.csv"), encoding="utf-8-sig"))}
    mk = {r["site_key"]: r for r in master}
    ops = list(csv.DictReader(open(os.path.join(M, "operator_clusters.csv"), encoding="utf-8-sig")))

    # ---- operator profiles ----
    members = defaultdict(list)
    basis = {}
    for r in ops:
        members[r["operator_id"]].append(r["site_key"])
        basis[r["operator_id"]] = g(r, "merge_basis")
    multi = {o: ms for o, ms in members.items() if len(ms) > 1}

    op_rows = []
    for o, ms in sorted(multi.items(), key=lambda kv: -len(kv[1])):
        rows = [mk[m] for m in ms if m in mk]
        stacks = Counter(labels[m]["stack_family"] for m in ms if m in labels)
        hosts = Counter(filter(None, (short_asn(g(r, "enrich__ip_asn")) for r in rows)))
        countries = Counter(filter(None, (g(r, "enrich__ip_country") for r in rows)))
        years = sorted(filter(None, (yr(r) for r in rows)))
        names = sorted({g(r, "disc__platform_name") or g(r, "hvoy__platform_name") for r in rows if (g(r, "disc__platform_name") or g(r, "hvoy__platform_name"))})
        b = basis.get(o, "")
        op_rows.append({
            "operator_id": o,
            "domain_count": len(ms),
            "member_domains": ";".join(sorted(ms)),
            "platform_names": ";".join(names),
            "stack_families": ";".join(f"{k}:{v}" for k, v in stacks.most_common()),
            "hosting": ";".join(f"{k}:{v}" for k, v in hosts.most_common(3)),
            "countries": ";".join(f"{k}:{v}" for k, v in countries.most_common(3)),
            "birth_range": (years[0] + "…" + years[-1]) if years else "",
            "tie_cert": "Y" if "cert" in b else "",
            "tie_favicon": "Y" if "favicon" in b else "",
            "tie_ip": "Y" if "ip=" in b else "",
            "tie_sitename": "Y" if "sitename" in b else "",
            "tie_contact": "Y" if any(x in b for x in ("telegram", "qq", "wechat")) else "",
            "merge_basis": b,
        })
    op_cols = ["operator_id", "domain_count", "platform_names", "stack_families", "hosting",
               "countries", "birth_range", "tie_cert", "tie_favicon", "tie_ip",
               "tie_sitename", "tie_contact", "member_domains", "merge_basis"]
    with open(os.path.join(M, "operator_profiles.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=op_cols); w.writeheader(); w.writerows(op_rows)

    # ---- favicon families ----
    fav = defaultdict(list)
    for r in master:
        h = g(r, "enrich__favicon_hash")
        if h:
            fav[h].append(r["site_key"])
    total_fav = sum(len(v) for v in fav.values())
    default_hash = max(fav, key=lambda h: len(fav[h])) if fav else ""
    fam_rows = []
    for h, sites in sorted(fav.items(), key=lambda kv: -len(kv[1])):
        if len(sites) < 2:
            continue
        stacks = Counter(labels[s]["stack_family"] for s in sites if s in labels)
        fam_rows.append({
            "favicon_hash": h,
            "site_count": len(sites),
            "is_default_icon": "Y (one-api 默认图标,非同源)" if h == default_hash else "",
            "stack_families": ";".join(f"{k}:{v}" for k, v in stacks.most_common()),
            "member_domains": ";".join(sorted(sites)) if len(sites) <= 40 else ";".join(sorted(sites)[:40]) + " …",
        })
    fam_cols = ["favicon_hash", "site_count", "is_default_icon", "stack_families", "member_domains"]
    with open(os.path.join(M, "favicon_families.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fam_cols); w.writeheader(); w.writerows(fam_rows)

    print(f"Wrote operator_profiles.csv  ({len(op_rows)} multi-site operators)")
    print(f"Wrote favicon_families.csv   ({len(fam_rows)} shared-favicon groups; "
          f"default icon {default_hash} on {len(fav.get(default_hash, []))} sites, flagged)")


if __name__ == "__main__":
    main()
