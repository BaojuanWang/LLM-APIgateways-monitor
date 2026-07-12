#!/usr/bin/env python3
"""Drill-down: expand every dashboard category into its concrete member sites.

The dashboard shows aggregate bars ("relay 838", "62 multi-site operators",
"26 template families"). This prints and writes what is actually *inside* each
bar — which domains, grouped, so the distributions can be inspected site by
site. Pure local computation; rerun after new data.

    python3 scripts/category_detail.py            # print highlights
    python3 scripts/category_detail.py --full      # also list long tails

Writes results/master/CATEGORY_DETAIL.md (full breakdown).
"""
from __future__ import annotations
import argparse
import csv
import os
import re
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")


def load(name):
    p = os.path.join(M, name)
    return list(csv.DictReader(open(p, encoding="utf-8-sig"))) if os.path.exists(p) else []


def g(r, c):
    return (r.get(c) or "").strip()


VENDORS = ["openai", "gpt", "claude", "anthropic", "gemini", "grok", "deepseek",
           "qwen", "grok", "llama", "midjourney", "sora", "kimi", "glm", "chatgpt"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="list long tails too")
    args = ap.parse_args()

    master = load("master_table.csv")
    cls = {r["domain"]: r for r in load("site_classification.csv")}
    profs = load("operator_profiles.csv")
    fams = load("site_similarity_clusters.csv")

    L = ["# 分类下钻 · 面板每根柱子的具体成员\n",
         "把仪表盘的聚合分布展开成站点级明细。快照随数据刷新。\n"]

    def section(title):
        L.append(f"\n## {title}\n")

    def sample(items, k=12):
        items = list(items)
        head = ", ".join(items[:k])
        return head + (f" … (+{len(items)-k})" if len(items) > k else "")

    # ── 1. 多站运营者 ──────────────────────────────────────────────
    section("1. 多站运营者(谁控制多个站)")
    multi = [p for p in profs if str(g(p, "domain_count")).isdigit() and int(g(p, "domain_count")) > 1]
    multi.sort(key=lambda p: -int(g(p, "domain_count")))
    L.append(f"共 {len(multi)} 个多站运营者(单站运营者省略)。`merge_basis` = 归并依据(证书/favicon/IP/站名/联系方式)。\n")
    L.append("| 运营者 | 站数 | 成员域名 | 归并依据 | 技术栈 | 出生区间 |")
    L.append("|---|---:|---|---|---|---|")
    for p in multi:
        L.append(f"| {g(p,'operator_id')} | {g(p,'domain_count')} | {g(p,'member_domains')} "
                 f"| {g(p,'merge_basis')} | {g(p,'stack_families')} | {g(p,'birth_range')} |")
    print(f"── 多站运营者 {len(multi)} 个 ──")
    for p in multi[:8]:
        print(f"  {g(p,'operator_id'):22s} {g(p,'domain_count')}站  基于[{g(p,'merge_basis')}]  {g(p,'member_domains')[:60]}")

    # ── 2. 模板家族(搭建商层)────────────────────────────────────
    section("2. 相似模板家族(共享搭建模板 / 搭建商)")
    L.append(f"共 {len(fams)} 个模板家族,{sum(int(g(f,'size') or 0) for f in fams)} 站。"
             f"`shared_features` = 让它们成簇的共享稀有特征。\n")
    L.append("| 家族 | 站数 | 共享特征 | 成员 |")
    L.append("|---|---:|---|---|")
    for f in sorted(fams, key=lambda x: -int(g(x, "size") or 0)):
        L.append(f"| {g(f,'family_id')} | {g(f,'size')} | {g(f,'shared_features')} | {g(f,'members')} |")
    print(f"\n── 模板家族 {len(fams)} 个 ──")
    for f in sorted(fams, key=lambda x: -int(g(x, "size") or 0))[:6]:
        print(f"  {g(f,'family_id'):10s} {g(f,'size')}站  [{g(f,'shared_features')[:40]}]  {g(f,'members')[:55]}")

    # ── 3. 站点角色 ────────────────────────────────────────────────
    section("3. 站点角色分类(site_role)")
    by_role = defaultdict(list)
    for d, r in cls.items():
        by_role[g(r, "site_role") or "?"].append(d)
    for role, ds in sorted(by_role.items(), key=lambda x: -len(x[1])):
        L.append(f"\n**{role}** — {len(ds)} 站\n\n{sample(sorted(ds), 40 if args.full else 20)}")
    print("\n── 站点角色 ──")
    for role, ds in sorted(by_role.items(), key=lambda x: -len(x[1])):
        print(f"  {role:16s} {len(ds):4d}  e.g. {sample(sorted(ds),6)}")

    # ── 4. 技术栈少数派(非 one-api 的都是啥)──────────────────────
    section("4. 技术栈少数派(非 one-api 家族的站)")
    by_stack = defaultdict(list)
    for d, r in cls.items():
        by_stack[g(r, "stack_family") or "?"].append(d)
    for st, ds in sorted(by_stack.items(), key=lambda x: -len(x[1])):
        if st == "one-api-family":
            L.append(f"\n**{st}** — {len(ds)} 站(主体,略)")
            continue
        L.append(f"\n**{st}** — {len(ds)} 站\n\n{sample(sorted(ds), 40 if args.full else 25)}")
    print("\n── 技术栈少数派 ──")
    for st, ds in sorted(by_stack.items(), key=lambda x: -len(x[1])):
        if st == "one-api-family":
            print(f"  {st:26s} {len(ds):4d}  (主体)")
        else:
            print(f"  {st:26s} {len(ds):4d}  e.g. {sample(sorted(ds),5)}")

    # ── 5. 傍上游品牌名的域名 ──────────────────────────────────────
    section("5. 域名含上游厂商名(傍品牌 / 商标风险)")
    hits = defaultdict(list)
    for d in cls:
        low = d.lower()
        for v in VENDORS:
            if v in low:
                hits[v].append(d)
    total_brand = len({d for ds in hits.values() for d in ds})
    L.append(f"共 {total_brand} 个域名含上游品牌名。\n")
    for v, ds in sorted(hits.items(), key=lambda x: -len(x[1])):
        L.append(f"\n**{v}** — {len(ds)} 站\n\n{sample(sorted(ds), 40 if args.full else 20)}")
    print("\n── 傍品牌域名 ──")
    for v, ds in sorted(hits.items(), key=lambda x: -len(x[1]))[:10]:
        print(f"  {v:12s} {len(ds):3d}  {sample(sorted(ds),5)}")

    # ── 6. 托管 / TLD / 注册商 / CA Top(带例子)───────────────────
    section("6. 基础设施 Top(带样例站)")
    dims = [("托管 ASN", "enrich__ip_asn"), ("顶级域", None),
            ("注册商", "enrich__whois_registrar"), ("证书 CA", "enrich__ssl_issuer")]
    key_of = {r.get("site_key"): r for r in master}
    for label, col in dims:
        buckets = defaultdict(list)
        for r in master:
            k = r.get("site_key", "")
            if col is None:
                val = k.rsplit(".", 1)[-1] if "." in k else k
            else:
                val = g(r, col) or "(空)"
            buckets[val].append(k)
        L.append(f"\n### {label}\n")
        L.append("| 值 | 站数 | 样例 |")
        L.append("|---|---:|---|")
        for val, ks in sorted(buckets.items(), key=lambda x: -len(x[1]))[:15]:
            L.append(f"| {val[:40]} | {len(ks)} | {sample(sorted(ks),4)} |")

    # ── 7. 2026 按月出生 ───────────────────────────────────────────
    section("7. 2026 按月出生(井喷明细)")
    by_month = defaultdict(list)
    for r in master:
        d = (g(r, "enrich__whois_reg_date") or g(r, "enrich__ssl_not_before"))[:7]
        if d.startswith("2026"):
            by_month[d].append(r.get("site_key", ""))
    L.append("| 月份 | 新站 | 样例 |")
    L.append("|---|---:|---|")
    for mo in sorted(by_month):
        L.append(f"| {mo} | {len(by_month[mo])} | {sample(sorted(by_month[mo]),5)} |")
    print("\n── 2026 按月出生 ──")
    for mo in sorted(by_month):
        print(f"  {mo}  {len(by_month[mo]):3d} 站")

    out = os.path.join(M, "CATEGORY_DETAIL.md")
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
