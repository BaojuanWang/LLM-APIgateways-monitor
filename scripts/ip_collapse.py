#!/usr/bin/env python3
"""Step ⓪ — internal IP collapse (zero network).

Among the 313 direct_origin sites, how many share a source IP, and does that
sharing reveal operators that operator_matching did NOT already merge? Answers
whether the within-dataset IP signal still holds untapped 'vigilante' merges,
or is already exhausted (in which case only EXTERNAL reverse-IP can add more).

    python3 scripts/ip_collapse.py     # -> results/master/ip_collapse.csv
"""
from __future__ import annotations
import csv
import os
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")
SHARED_HOST_MIN = 8       # >= this many of OUR sites on one IP → likely shared host


def main():
    rows = list(csv.DictReader(open(os.path.join(M, "direct_origin_targets.csv"),
                                     encoding="utf-8-sig")))
    by_ip = defaultdict(list)
    for r in rows:
        if r.get("source_ip"):
            by_ip[r["source_ip"]].append(r)

    shared = {ip: g for ip, g in by_ip.items() if len(g) > 1}
    host = {ip: g for ip, g in shared.items() if len(g) >= SHARED_HOST_MIN}
    real = {ip: g for ip, g in shared.items() if 2 <= len(g) < SHARED_HOST_MIN}

    out_rows, new_merges = [], 0
    for ip, g in sorted(real.items(), key=lambda x: -len(x[1])):
        ops = {r["operator_id"] for r in g if r["operator_id"]}
        already = len(ops) <= 1
        if not already:
            new_merges += 1
        for r in g:
            out_rows.append({"source_ip": ip, "n_on_ip": len(g), "domain": r["domain"],
                             "operator_id": r["operator_id"],
                             "already_same_operator": "Y" if already else "",
                             "new_collapse": "" if already else "Y"})

    out = os.path.join(M, "ip_collapse.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["source_ip", "n_on_ip", "domain",
                                          "operator_id", "already_same_operator", "new_collapse"])
        w.writeheader(); w.writerows(out_rows)

    print(f"裸露站 {len(rows)} → {len(by_ip)} 个源站 IP")
    print(f"共用 IP 簇(>=2 站)      : {len(shared)}  (覆盖 {sum(len(g) for g in shared.values())} 站)")
    print(f"  疑似共享主机(>={SHARED_HOST_MIN} 站,排除): {len(host)}")
    print(f"  高价值同 IP 簇(2-{SHARED_HOST_MIN-1} 站)  : {len(real)}  (覆盖 {sum(len(g) for g in real.values())} 站)")
    print(f"新坍缩(同 IP 但当前算不同运营者): {new_merges}")
    if new_merges == 0:
        print("→ 内部 IP 信号已被 operator_matching 榨干;新马甲只能靠外部反查(reverse_ip.py)。")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
