#!/usr/bin/env python3
"""Feature-coverage / missingness audit.

Not every feature is obtainable for every site. Aggregating without saying so
hides the denominator. This script makes missingness explicit:

  * per field: obtained vs missing, coverage %, and WHY it can be missing
    (structural / not-yet-collected / redacted / transient);
  * per dashboard dimension: the distribution WITH the unknown bucket kept as
    its own row, reported both as % of all sites and % of sites-with-data.

It also encodes the "what to do when you can't get it" policy per field, so the
handling is documented, not ad hoc. Pure local; rerun on new data.

    python3 scripts/coverage_audit.py        # -> results/master/COVERAGE_AUDIT.md
"""
from __future__ import annotations
import csv
import os
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")

# Obtainability class → how to handle a miss (the "拿不到怎么办" policy).
POLICY = {
    "structural": "结构上不可得(如 CDN 后真实源站 IP、免费证书无公司名)。"
                  "**缺失本身是信号**(=刻意不透明);报为显式 unknown 桶,永不插补。",
    "collectible": "尚未采集(采集器没覆盖到)。跑对应采集器补齐(deep_dig.sh);"
                   "在补齐前,统计只在'已采子集'上做并注明分母。",
    "redactable": "可能被隐私代理/GDPR 脱敏。报'脱敏率';用备用信号回退"
                  "(注册商→ICP备案→证书Org→关于页公司名)。",
    "transient": "探测时点站点失活/超时。重试;标为 churn,不与'永久缺失'混淆。",
    "derived": "由其他字段派生,缺失=上游字段缺失。跟随上游。",
}

# field, human label, obtainability class
FIELDS = [
    ("disc__framework",            "发现层框架",        "collectible"),
    ("enrich__ssl_not_before",     "证书 not_before",   "structural"),
    ("enrich__ssl_fingerprint",    "证书指纹",          "structural"),
    ("enrich__ssl_org",            "证书公司名(Org)",  "structural"),
    ("enrich__whois_reg_date",     "WHOIS 注册日",      "redactable"),
    ("enrich__whois_registrar",    "WHOIS 注册商",      "redactable"),
    ("enrich__whois_registrant_org","WHOIS 注册人机构",  "redactable"),
    ("enrich__ip",                 "源站 IP",           "structural"),
    ("enrich__ip_asn",             "托管 ASN",          "structural"),
    ("enrich__ip_country",         "IP 国家",           "structural"),
    ("enrich__favicon_hash",       "favicon 指纹",      "transient"),
    ("manual__icp_filing",         "ICP 备案主体",      "collectible"),
    ("privacy__has_privacy",       "隐私政策",          "collectible"),
    ("privacy__applicable_law",    "隐私·适用法律",     "collectible"),
    ("privacy__third_party_sharing","隐私·第三方共享",  "collectible"),
    ("ops__payment_methods",       "支付方式",          "collectible"),
    ("contacts__telegram",         "Telegram 触达",     "collectible"),
    ("hvoy__overallScore",         "第三方榜单评分",    "collectible"),
    ("monitor__online_status",     "存活状态",          "transient"),
]

# dashboard dimensions where the unknown bucket must be shown explicitly
DIMENSIONS = [
    ("stack_family",  "site_stack_labels.csv", "site_key", ("unlabeled", "confirmed-unknown", "openai-compatible-unknown")),
    ("site_role",     "site_classification.csv", "domain", ("unidentified",)),
    ("hosting_type",  "site_classification.csv", "domain", ("unknown",)),
    ("maturity_tier", "site_classification.csv", "domain", ("unknown",)),
]


def load(name):
    p = os.path.join(M, name)
    return list(csv.DictReader(open(p, encoding="utf-8-sig"))) if os.path.exists(p) else []


def main():
    master = load("master_table.csv")
    n = len(master)
    L = [f"# 特征覆盖 / 缺失审计  (N={n} 站)\n",
         "每个特征拿到多少、unknown 占多少、缺失原因、拿不到怎么处理。\n"]

    # ── Part 1: per-field coverage ────────────────────────────────
    L.append("## 1. 逐字段可获取率\n")
    L.append("| 特征 | 已获取 | 覆盖率 | 缺失 | 缺失类别 |")
    L.append("|---|---:|---:|---:|---|")
    print(f"── 逐字段覆盖 (N={n}) ──")
    print(f"  {'特征':22s}{'覆盖':>10s}  缺失类别")
    by_class = {}
    for col, label, cls in FIELDS:
        got = sum(1 for r in master if (r.get(col) or "").strip())
        pct = 100 * got / n if n else 0
        L.append(f"| {label} | {got} | {pct:.0f}% | {n-got} | {cls} |")
        by_class.setdefault(cls, []).append((label, pct))
        bar = "█" * round(pct / 5)
        print(f"  {label:22s}{got:5d} {pct:4.0f}%  {cls:12s} {bar}")

    # ── Part 2: distributions with unknown explicit ───────────────
    L.append("\n## 2. 面板分类分布(unknown 显式,双分母)\n")
    L.append("每类给两个占比:占**全部站**、占**有数据的站**(剔除 unknown 后)。\n")
    print("\n── 分类分布(unknown 显式)──")
    for col, fname, keycol, unknown_vals in DIMENSIONS:
        rows = load(fname)
        if not rows:
            continue
        ctr = Counter((r.get(col) or "(空)").strip() for r in rows)
        tot = sum(ctr.values())
        known = sum(v for k, v in ctr.items() if k not in unknown_vals and k != "(空)")
        L.append(f"\n### {col}  (共 {tot};有数据 {known};unknown {tot-known})\n")
        L.append("| 值 | 站数 | 占全部 | 占有数据 | 类型 |")
        L.append("|---|---:|---:|---:|---|")
        print(f"\n  [{col}]  有数据 {known}/{tot}  unknown {tot-known} ({100*(tot-known)//tot}%)")
        for k, v in ctr.most_common():
            is_unk = k in unknown_vals or k == "(空)"
            cond = "—" if is_unk else f"{100*v/known:.0f}%"
            tag = "⚠unknown" if is_unk else ""
            L.append(f"| {k} | {v} | {100*v/tot:.0f}% | {cond} | {tag} |")
            if is_unk or v >= tot * 0.03:
                print(f"    {k:28s} {v:4d}  全{100*v/tot:3.0f}%  {'有据'+cond if not is_unk else 'UNKNOWN':>10s} {tag}")

    # ── Part 3: the handling policy ───────────────────────────────
    L.append("\n## 3. 拿不到怎么办(按缺失类别的处置策略)\n")
    L.append("| 类别 | 处置策略 | 涉及字段 |")
    L.append("|---|---|---|")
    for cls, pol in POLICY.items():
        flds = ", ".join(lbl for lbl, _ in by_class.get(cls, []))
        L.append(f"| **{cls}** | {pol} | {flds} |")
    L.append("\n**总原则**:①永不插补——缺失作为显式 unknown 桶参与统计;"
             "②每个统计量注明分母(全部 vs 已采子集);"
             "③结构性缺失(CDN/免费证书)**本身当信号**(=刻意不透明);"
             "④可采缺失跑采集器补,脱敏缺失走备用信号回退链。\n")

    out = os.path.join(M, "COVERAGE_AUDIT.md")
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
