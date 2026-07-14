#!/usr/bin/env python3
"""Cross-tabulations over the per-site classification.

Marginals (single-dimension bars) are on the dashboard already; the structure
lives in the *joint* distributions. This prints and writes the key cross-tabs:
role×maturity, stack×hosting, role×hosting, maturity×hosting. Pure local.

    python3 scripts/cross_tabs.py     # -> results/master/CROSS_TABS.md
"""
from __future__ import annotations
import csv
import os
from collections import Counter, defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")


def load(name):
    p = os.path.join(M, name)
    return list(csv.DictReader(open(p, encoding="utf-8-sig"))) if os.path.exists(p) else []


def g(r, c):
    return (r.get(c) or "").strip() or "?"


def crosstab(rows, rowdim, coldim, L, title, note=""):
    cells = defaultdict(Counter)
    rowtot, coltot = Counter(), Counter()
    for r in rows:
        rv, cv = g(r, rowdim), g(r, coldim)
        cells[rv][cv] += 1
        rowtot[rv] += 1
        coltot[cv] += 1
    cols = [c for c, _ in coltot.most_common()]
    L.append(f"\n## {title}\n")
    if note:
        L.append(note + "\n")
    L.append("| " + f"{rowdim} ↓ / {coldim} →" + " | " + " | ".join(cols) + " | **合计** |")
    L.append("|" + "---|" * (len(cols) + 2))
    for rv, _ in rowtot.most_common():
        line = f"| **{rv}** | " + " | ".join(
            (f"{cells[rv][c]} ({100*cells[rv][c]//rowtot[rv]}%)" if cells[rv][c] else "·") for c in cols)
        line += f" | **{rowtot[rv]}** |"
        L.append(line)
    L.append("| **合计** | " + " | ".join(f"**{coltot[c]}**" for c in cols) + f" | **{sum(rowtot.values())}** |")

    print(f"\n── {title} ──")
    print(f"  {'':14s}" + "".join(f"{c[:10]:>12s}" for c in cols) + f"{'总':>7s}")
    for rv, _ in rowtot.most_common():
        print(f"  {rv[:14]:14s}" + "".join(f"{cells[rv][c]:>12d}" for c in cols) + f"{rowtot[rv]:>7d}")


def main():
    cls = load("site_classification.csv")
    L = [f"# 交叉表 · 联合分布  (N={len(cls)} 站)\n",
         "单维分布在面板上;结构在联合分布里。括号=行内占比。\n"]

    crosstab(cls, "site_role", "maturity_tier", L,
             "1. 角色 × 成熟度",
             "看新生代(2026)里 relay/conversion/unidentified 的构成变化。")
    crosstab(cls, "stack_family", "hosting_type", L,
             "2. 技术栈 × 托管类型",
             "看哪种栈更爱藏 CDN 后(不透明性 × 技术选择)。")
    crosstab(cls, "site_role", "hosting_type", L,
             "3. 角色 × 托管类型")
    crosstab(cls, "maturity_tier", "hosting_type", L,
             "4. 成熟度 × 托管类型",
             "看新站是否比老站更倾向 CDN 遮蔽。")
    crosstab(cls, "site_role", "has_faka", L,
             "5. 角色 × 是否发卡站(faka)",
             "发卡=自动化售卡变现;看哪类角色更商业化。")

    out = os.path.join(M, "CROSS_TABS.md")
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
