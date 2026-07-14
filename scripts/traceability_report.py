#!/usr/bin/env python3
"""Privacy + operator-identity drill-down → the 'structural anti-attribution'
result: how traceable is this ecosystem to a real operating entity?

Combines the identity signals into one traceability rate and reports the
privacy-policy substance. Pure local; rerun as ICP / registrant data grows.

    python3 scripts/traceability_report.py   # -> results/master/TRACEABILITY.md
"""
from __future__ import annotations
import csv
import os
import re
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")

# placeholders that are NOT a real operator identity
REDACT = re.compile(r"redact|privacy|whois|proxy|guard|protect|masked|domains?\s+by|"
                    r"withheld|gdpr|not disclosed|c/o|隐私|保护|withheld for", re.I)


def load(name):
    return list(csv.DictReader(open(os.path.join(M, name), encoding="utf-8-sig")))


def g(r, c):
    return (r.get(c) or "").strip()


def real_entity(v):
    return bool(v) and not REDACT.search(v)


def main():
    rows = load("master_table.csv")
    n = len(rows)
    L = [f"# 可追溯性 / 结构性反追溯  (N={n} 站)\n",
         "一个转售商业 AI API 的灰色生态,在网络层/身份层/注册层能否被追到真实运营者?\n"]

    # ── identity signals ──────────────────────────────────────────
    # CDN count from the classification layer (cdn_fronted), same as dashboard.
    cls = load("site_classification.csv")
    cdn = sum(1 for r in cls if g(r, "hosting_type") == "cdn_fronted")
    cert_org = sum(1 for r in rows if real_entity(g(r, "enrich__ssl_org")))
    whois_real = sum(1 for r in rows if real_entity(g(r, "enrich__whois_registrant_org")))
    icp = sum(1 for r in rows if g(r, "manual__icp_filing")
              or g(r, "icp_entity_name"))          # icp col only in targets file; kept for future
    # a site is "traceable" if ANY hard identity signal names a real entity
    traceable = sum(1 for r in rows if (real_entity(g(r, "enrich__whois_registrant_org"))
                                        or real_entity(g(r, "enrich__ssl_org"))))
    L.append("## 1. 身份信号可得性(可追溯率)\n")
    L.append("| 信号 | 命中真实实体 | 占比 |")
    L.append("|---|---:|---:|")
    L.append(f"| WHOIS 注册人机构(非代理) | {whois_real} | {100*whois_real/n:.1f}% |")
    L.append(f"| 证书 Organization(OV/EV) | {cert_org} | {100*cert_org/n:.1f}% |")
    L.append(f"| **合并可追溯(任一硬信号)** | **{traceable}** | **{100*traceable/n:.1f}%** |")
    L.append(f"\n> **核心数字**:{n} 个站里,只有 **{traceable} 个({100*traceable/n:.1f}%)** 能通过硬信号追到一个疑似真实运营实体。"
             f"其余 **{100*(n-traceable)/n:.0f}%** 结构性地无法归因。\n")

    # ── why untraceable (the mechanism) ───────────────────────────
    L.append("## 2. 追不到的机制(三层反追溯)\n")
    L.append("| 层 | 遮蔽手段 | 覆盖 |")
    L.append("|---|---|---:|")
    L.append(f"| 网络层 | 藏 Cloudflare 等 CDN 后,源站 IP 不可见 | {cdn}/{n} ({100*cdn//n}%) |")
    proxied = sum(1 for r in rows if g(r, "enrich__whois_registrant_org") and not real_entity(g(r, "enrich__whois_registrant_org")))
    L.append(f"| 注册层 | WHOIS 用隐私代理占位(Domains By Proxy 等) | {proxied}/{n} ({100*proxied//n}%) |")
    freecert = sum(1 for r in rows if g(r, "enrich__ssl_issuer") and not real_entity(g(r, "enrich__ssl_org")))
    L.append(f"| 证书层 | 免费 DV 证书,无企业实名字段 | {freecert}/{n} ({100*freecert//n}%) |")

    # ── the few that DID leak an identity ─────────────────────────
    leaked = [(g(r, "site_key"), g(r, "enrich__whois_registrant_org") or g(r, "enrich__ssl_org"))
              for r in rows if real_entity(g(r, "enrich__whois_registrant_org")) or real_entity(g(r, "enrich__ssl_org"))]
    L.append(f"\n## 3. 漏出真实实体的站({len(leaked)} 个,高价值线索)\n")
    L.append("| 域名 | 疑似运营实体 |")
    L.append("|---|---|")
    for dom, ent in sorted(leaked):
        L.append(f"| {dom} | {ent} |")

    # ── privacy-policy substance ──────────────────────────────────
    has = [r for r in rows if g(r, "privacy__has_privacy") == "有"]
    L.append(f"\n## 4. 隐私政策实质(有政策的 {len(has)} 站;{100*len(has)//n}% 覆盖 = 静态下界)\n")
    L.append("> ⚠️ 静态爬虫下界:JS 渲染站会漏抓,Playwright 重抓后此数上升。\n")
    for dim, lab in [("privacy__applicable_law", "适用法律"),
                     ("privacy__third_party_sharing", "第三方共享"),
                     ("privacy__collect_data", "数据收集声明")]:
        L.append(f"\n**{lab}**")
        for k, v in Counter(g(r, dim) or "(空)" for r in has).most_common():
            L.append(f"- {k}: {v} ({100*v//max(len(has),1)}%)")
    nolaw = sum(1 for r in has if g(r, "privacy__applicable_law") in ("未明确说明", "", "(空)"))
    L.append(f"\n> 即便有隐私政策,**{100*nolaw//max(len(has),1)}% 连适用法律都不声明** —— 政策多为形式化空文。\n")

    out = os.path.join(M, "TRACEABILITY.md")
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print(f"可追溯率: {traceable}/{n} ({100*traceable/n:.1f}%) 能追到真实实体")
    print(f"  WHOIS真实 {whois_real} · 证书Org {cert_org} · CDN遮蔽 {cdn} · WHOIS代理 {proxied}")
    print(f"隐私政策: {len(has)}/{n} ({100*len(has)//n}%,静态下界) · 其中 {100*nolaw//max(len(has),1)}% 不声明适用法律")
    print(f"漏出真实实体的站: {len(leaked)}")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
