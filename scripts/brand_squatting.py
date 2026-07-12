#!/usr/bin/env python3
"""Trademark-risk profile: sites whose domain embeds an upstream vendor brand.

Relays that put "openai/claude/gpt/gemini/…" directly in the domain are a
distinct trademark-risk sub-population. This isolates them and joins their
stack / role / health / operator / hosting so the risk section is evidence-
backed. Pure local; rerun on new data.

    python3 scripts/brand_squatting.py   # -> results/master/BRAND_SQUATTING.md
"""
from __future__ import annotations
import csv
import os
import re
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")

# upstream brands, longest-first so "chatgpt" wins over "gpt"
VENDORS = ["chatgpt", "openai", "anthropic", "claude", "gemini", "deepseek",
           "midjourney", "qwen", "llama", "grok", "kimi", "sora", "gpt"]


def load(name):
    p = os.path.join(M, name)
    return list(csv.DictReader(open(p, encoding="utf-8-sig"))) if os.path.exists(p) else []


def g(r, c):
    return (r.get(c) or "").strip()


def vendor_of(domain):
    low = domain.lower()
    for v in VENDORS:                     # longest-first
        if v in low:
            return v
    return ""


def main():
    cls = {r["domain"]: r for r in load("site_classification.csv")}
    master = {r.get("site_key"): r for r in load("master_table.csv")}

    hits = []
    for d, r in cls.items():
        v = vendor_of(d)
        if not v:
            continue
        mt = master.get(d, {})
        hits.append({
            "domain": d, "vendor": v,
            "stack": g(r, "stack_family"), "role": g(r, "site_role"),
            "hosting": g(r, "hosting_type"),
            "health": g(r, "health") or g(mt, "monitor__online_status"),
            "operator": g(r, "operator_id"), "op_size": g(r, "operator_domains"),
            "birth": g(r, "birth_year"),
            "icp": g(mt, "manual__icp_filing"),
        })
    hits.sort(key=lambda x: (x["vendor"], x["domain"]))

    n = len(hits)
    L = [f"# 傍品牌 / 商标风险专题  ({n} 站)\n",
         "域名直接嵌入上游厂商品牌名(openai/claude/gpt/…)的中转站。"
         "这是一个独立的商标侵权风险子群:既误导用户、又暴露运营者对合规的漠视。\n"]

    # distributions
    L.append("## 概览\n")
    for dim, lab in [("vendor", "傍的品牌"), ("role", "角色"), ("stack", "技术栈"),
                     ("hosting", "托管"), ("health", "存活")]:
        c = Counter(h[dim] or "?" for h in hits)
        L.append(f"- **{lab}**:" + " · ".join(f"{k} {v}" for k, v in c.most_common()))
    multi = [h for h in hits if h["op_size"].isdigit() and int(h["op_size"]) > 1]
    L.append(f"- **属于多站运营者**:{len(multi)}/{n}(即傍品牌常是成规模网络的一部分)\n")

    L.append("## 逐站明细\n")
    L.append("| 域名 | 傍的品牌 | 角色 | 技术栈 | 托管 | 存活 | 运营者(站数) | 出生 | ICP |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for h in hits:
        op = f"{h['operator']}({h['op_size']})" if h["operator"] else ""
        L.append(f"| {h['domain']} | {h['vendor']} | {h['role']} | {h['stack']} "
                 f"| {h['hosting']} | {h['health']} | {op} | {h['birth']} | {h['icp']} |")

    print(f"── 傍品牌站 {n} 个 ──")
    for dim in ("vendor", "role", "health"):
        c = Counter(h[dim] or "?" for h in hits)
        print(f"  {dim:8s}: " + " · ".join(f"{k} {v}" for k, v in c.most_common()))
    print(f"  多站运营者成员: {len(multi)}/{n}")

    out = os.path.join(M, "BRAND_SQUATTING.md")
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
