#!/usr/bin/env python3
"""Build the operator-attribution target list — the 'direct_origin' (non-CDN)
sites whose real server IP is exposed and can therefore be reverse-traced.

This is the input for the attribution steps (ICP lookup, reverse-IP, port
fingerprint). It is the ONLY reverse-traceable slice of the dataset; the 760
cdn_fronted sites resolve to CDN edge IPs and are out of scope.

Emits results/master/direct_origin_targets.csv with, per site:
    domain, source_ip, ip_country, ip_asn, tld, is_cn (ICP-queryable),
    operator_id, operator_domains, priority (direct_origin & >=2 domains),
    site_name, framework.
Pure local; rerun on new data.

    python3 scripts/build_attribution_targets.py
"""
from __future__ import annotations
import csv
import os
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")
CN_SUFFIXES = (".cn", ".com.cn", ".org.cn", ".net.cn", ".gov.cn")


def load(name):
    return list(csv.DictReader(open(os.path.join(M, name), encoding="utf-8-sig")))


def g(r, c):
    return (r.get(c) or "").strip()


def main():
    cls = {r["domain"]: r for r in load("site_classification.csv")}
    mt = {r["site_key"]: r for r in load("master_table.csv")}

    rows = []
    for d, r in cls.items():
        if g(r, "hosting_type") != "direct_origin":
            continue
        m = mt.get(d, {})
        opn = g(r, "operator_domains")
        rows.append({
            "domain": d,
            "source_ip": g(m, "enrich__ip"),
            "ip_country": g(m, "enrich__ip_country"),
            "ip_asn": g(m, "enrich__ip_asn"),
            "tld": d.rsplit(".", 1)[-1] if "." in d else "",
            "is_cn": "Y" if d.endswith(CN_SUFFIXES) else "",
            "operator_id": g(r, "operator_id"),
            "operator_domains": opn,
            "priority": "Y" if opn.isdigit() and int(opn) >= 2 else "",
            "site_name": g(m, "disc__verified_site_name") or g(m, "hvoy__siteName"),
            "framework": g(m, "disc__framework"),
            # to be filled by downstream local steps:
            "icp_entity_name": "", "icp_number": "",
            "co_hosted_domains": "", "ip_is_shared_host": "",
        })
    # priority first, then by operator so co-conspirators sit together
    rows.sort(key=lambda x: (x["priority"] != "Y", x["operator_id"], x["domain"]))

    cols = ["domain", "source_ip", "ip_country", "ip_asn", "tld", "is_cn",
            "operator_id", "operator_domains", "priority", "site_name", "framework",
            "icp_entity_name", "icp_number", "co_hosted_domains", "ip_is_shared_host"]
    out = os.path.join(M, "direct_origin_targets.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader(); w.writerows(rows)

    prio = [r for r in rows if r["priority"] == "Y"]
    cn = [r for r in rows if r["is_cn"] == "Y"]
    uniq_ips = len({r["source_ip"] for r in rows if r["source_ip"]})
    print(f"Wrote {out}")
    print(f"  裸露站(direct_origin)   : {len(rows)}")
    print(f"  优先追(有同伙 >=2)      : {len(prio)}  归属 {len({r['operator_id'] for r in prio if r['operator_id']})} 运营者")
    print(f"  可查 ICP 的 .cn 站       : {len(cn)}")
    print(f"  去重源站 IP              : {uniq_ips}  (IP 反查目标)")
    print(f"  IP 国家分布 Top5         : " +
          " · ".join(f"{k} {v}" for k, v in Counter(r['ip_country'] or '?' for r in rows).most_common(5)))


if __name__ == "__main__":
    main()
