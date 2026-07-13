#!/usr/bin/env python3
"""Turn reverse-IP co-hosted domains into vigilante evidence.

For each exposed source IP with a small (non-shared-host) co-tenant set, split
the co-hosted domains into (a) the target operator's OWN brand variants
(subdomains / same registrable domain — merely confirms) and (b) DIFFERENT
registrable domains that look like relays (candidate hidden co-brands the
internal signals missed). Filters VPS/cloud-provider noise. Pure local.

    python3 scripts/analyze_reverse_ip.py   # -> results/master/vigilante_candidates.csv + .md
"""
from __future__ import annotations
import csv
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")
sys.path.insert(0, os.path.join(BASE, "scripts"))
from domain_utils import registrable_domain as reg  # noqa: E402

RELAY = re.compile(r"api|ai|gpt|chat|hub|token|claude|relay|codex|llm|proxy|route|one-api", re.I)
# hosting/CDN/VPS providers that co-tenant by coincidence, not by operator
NOISE = re.compile(r"clouds?\.|vps|hostwinds|dmit|cloudcone|16clouds|gigsgigs|amazonaws|"
                   r"digitalocean|rainyun|arpa|akamai|cloudflare|vercel|netlify", re.I)


def load(name):
    return list(csv.DictReader(open(os.path.join(M, name), encoding="utf-8-sig")))


def main():
    rows = load("direct_origin_targets.csv")
    alldoms = {reg(r["site_key"]) for r in load("master_table.csv")}

    out, new_brands, op_expand = [], set(), {}
    for r in rows:
        co = [d for d in (r.get("co_hosted_domains") or "").split(";") if d]
        if not co:
            continue
        tgt, op = reg(r["domain"]), r.get("operator_id", "")
        cand = set()
        for d in co:
            rd = reg(d)
            if rd == tgt or NOISE.search(d) or not RELAY.search(rd):
                continue
            cand.add(rd)
        if not cand:
            continue
        fresh = sorted(c for c in cand if c not in alldoms)
        for c in fresh:
            new_brands.add(c)
            op_expand.setdefault(op, set()).add(c)
        out.append({"domain": r["domain"], "operator_id": op, "source_ip": r["source_ip"],
                    "cross_brand_co_hosted": ";".join(sorted(cand)),
                    "new_not_in_dataset": ";".join(fresh)})

    with open(os.path.join(M, "vigilante_candidates.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["domain", "operator_id", "source_ip",
                                          "cross_brand_co_hosted", "new_not_in_dataset"])
        w.writeheader(); w.writerows(out)

    ips_probed = len({r["source_ip"] for r in rows if r.get("co_hosted_domains") is not None
                      and (r.get("co_hosted_domains") or r.get("ip_is_shared_host"))})
    L = ["# 马甲候选(reverse-IP)\n",
         f"从已反查的 IP 中,按'同 IP + 跨品牌 + 像中转站 + 非主机噪声'挑出的隐藏马甲。\n",
         f"**新发现(不在现有数据集)的跨品牌马甲主域:{len(new_brands)} 个**\n",
         "\n## 按运营者归并的马甲扩张\n",
         "| 运营者 | 新增隐藏品牌 |", "|---|---|"]
    for op, brands in sorted(op_expand.items(), key=lambda x: -len(x[1])):
        L.append(f"| {op} | {', '.join(sorted(brands))} |")
    L.append("\n## 全部新马甲主域\n\n" + ", ".join(sorted(new_brands)))
    L.append("\n\n> 口径:这是 reverse-IP 抽样结果(HackerTarget 免费配额,非全量 287 IP)。"
             "全量跑完预计更多。这些新域名尚未验证为活跃中转站,是**候选**,可回灌发现层复核。")
    open(os.path.join(M, "vigilante_candidates.md"), "w", encoding="utf-8").write("\n".join(L))

    print(f"跨品牌马甲命中站: {len(out)}")
    print(f"新发现马甲主域(不在库): {len(new_brands)}")
    print(f"涉及运营者扩张: {len(op_expand)} 个")
    for op, brands in sorted(op_expand.items(), key=lambda x: -len(x[1]))[:6]:
        print(f"   {op:18s} +{len(brands)}: {', '.join(sorted(brands))}")
    print(f"\nWrote results/master/vigilante_candidates.csv + .md")


if __name__ == "__main__":
    main()
