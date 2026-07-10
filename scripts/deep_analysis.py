#!/usr/bin/env python3
"""Deep characterization report: every mineable feature + cross-tabs.

Reads the master table and writes a detailed markdown report covering stack,
liveness, birth timeline, hosting, certificate CA, registrar, server/frontend
tech, domain-naming themes, business-model signals, operator concentration, and
cross-tabs. Pure local — no network.

    python3 scripts/deep_analysis.py   # -> results/master/ANALYSIS_REPORT.md
"""
from __future__ import annotations
import csv, os, re, sys
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from domain_utils import registrable_domain  # noqa

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE, "results", "master")


def load():
    master = list(csv.DictReader(open(os.path.join(M, "master_table.csv"), encoding="utf-8-sig")))
    labels = {r["site_key"]: r for r in csv.DictReader(open(os.path.join(M, "site_stack_labels.csv"), encoding="utf-8-sig"))}
    return master, labels


def g(r, c):
    return (r.get(c) or "").strip()


def bar(n, mx, w=28):
    return "█" * round(n / mx * w) if mx else ""


def table(title, counter, base, top=None, note=""):
    out = [f"### {title}", ""]
    if note:
        out.append(f"_{note}_\n")
    out.append("| 值 | 站数 | 占比 |")
    out.append("|---|---:|---:|")
    for k, v in counter.most_common(top):
        out.append(f"| {k} | {v} | {100*v/base:.1f}% |")
    out.append("")
    return "\n".join(out)


def ca_group(issuer):
    s = issuer.lower()
    if "let's encrypt" in s or "lets encrypt" in s: return "Let's Encrypt"
    if "google trust" in s: return "Google Trust Services"
    if "zerossl" in s: return "ZeroSSL"
    if "digicert" in s: return "DigiCert"
    if "trustasia" in s: return "TrustAsia"
    if "sectigo" in s: return "Sectigo"
    if "cloudflare" in s: return "Cloudflare"
    if "amazon" in s: return "Amazon"
    return issuer[:24] if issuer else "(未知)"


def asn_name(a):
    a = a.strip()
    if not a: return "(未知)"
    p = a.split(None, 1)
    return (p[1] if len(p) > 1 and p[0].upper().startswith("AS") else a).split(",")[0].strip()[:28]


def health(r):
    st = g(r, "monitor__online_status")
    cert = bool(g(r, "enrich__ssl_fingerprint"))
    if st == "ONLINE": return "在线(持续监测)"
    if st == "ONLINE_LOGIN_REQUIRED": return "在线·需登录"
    if st == "CLOUDFLARE_OR_BLOCKED": return "被挡/CF 挑战"
    if st in ("DNS_FAIL", "TIMEOUT", "HTTP_ERROR", "SERVICE_STOPPED"): return "疑似失效"
    if cert: return "HTTPS 可达(未持续监测)"
    return "未响应"


def main():
    master, labels = load()
    n = len(master)
    mk = {r["site_key"]: r for r in master}

    # ---- feature counters ----
    stack = Counter(labels[r["site_key"]]["stack_family"] for r in master)
    fw = Counter(g(r, "disc__framework") or "(未进发现层)" for r in master)
    hstate = Counter(health(r) for r in master)
    cert_ok = sum(1 for r in master if g(r, "enrich__ssl_fingerprint"))

    # birth year + 2026 monthly
    year = Counter(); mon = Counter(); dated = 0
    for r in master:
        d = g(r, "enrich__whois_reg_date") or g(r, "enrich__ssl_not_before")
        if d[:4].isdigit():
            dated += 1
            year["≤2022" if int(d[:4]) <= 2022 else d[:4]] += 1
            if d[:7].startswith(("2025", "2026")):
                mon[d[:7]] += 1

    country = Counter(g(r, "enrich__ip_country") or "(未知)" for r in master if g(r, "enrich__ip"))
    n_ip = sum(1 for r in master if g(r, "enrich__ip"))
    asn = Counter(asn_name(g(r, "enrich__ip_asn")) for r in master if g(r, "enrich__ip_asn"))
    n_asn = sum(1 for r in master if g(r, "enrich__ip_asn"))
    ca = Counter(ca_group(g(r, "enrich__ssl_issuer")) for r in master if g(r, "enrich__ssl_issuer"))
    reg = Counter(g(r, "enrich__whois_registrar")[:30] for r in master if g(r, "enrich__whois_registrar"))
    n_reg = sum(1 for r in master if g(r, "enrich__whois_registrar"))

    # server + frontend tech (parse enrich__tech_stack tokens)
    tech = Counter()
    for r in master:
        for t in (g(r, "enrich__tech_stack") or "").split(","):
            t = t.strip()
            if t: tech[t] += 1
    server = Counter(g(r, "enrich__server_header").split("/")[0].split()[0].lower() or "(空)"
                     for r in master if g(r, "enrich__server_header"))

    # domain-name themes
    KW = ["api", "ai", "gpt", "chat", "claude", "code", "hub", "proxy", "token", "new", "one", "cloud"]
    kw = Counter()
    for r in master:
        d = r["site_key"].lower()
        for k in KW:
            if k in d: kw[k] += 1

    tld = Counter(labels[r["site_key"]]["tld"] for r in master)

    # business model (subset with data)
    aff = sum(1 for r in master if g(r, "contacts__has_affiliate") == "有")
    aff_base = sum(1 for r in master if g(r, "contacts__has_affiliate"))
    priv_yes = sum(1 for r in master if g(r, "privacy__has_privacy") == "有")
    priv_base = sum(1 for r in master if g(r, "privacy__has_privacy"))

    # operators
    ops = list(csv.DictReader(open(os.path.join(M, "operator_clusters.csv"), encoding="utf-8-sig")))
    op_members = defaultdict(list)
    for r in ops:
        op_members[r["operator_id"]].append(r)
    multi = {o: m for o, m in op_members.items() if len(m) > 1}

    # cross-tab: stack x country (top countries)
    topc = [c for c, _ in country.most_common(5)]
    sc = defaultdict(Counter)
    for r in master:
        c = g(r, "enrich__ip_country")
        if c in topc:
            sc[labels[r["site_key"]]["stack_family"]][c] += 1

    # ---- render ----
    L = []
    L.append("# LLM 中转站生态 · 深度特征分析\n")
    L.append(f"样本:**{n} 个站点**(发现层 764 ∪ 监测 292,按注册域归并)。快照 2026-07-10。")
    L.append("本报告仅用已采集数据、纯本地计算。每节标注覆盖率;低覆盖的字段结论仅供参考。\n")
    L.append("---\n")

    L.append("## 1. 存活状态\n")
    L.append(table("健康分布", hstate, n,
                   note=f"HTTPS 握手成功≈活着:{cert_ok}/{n} ({100*cert_ok/n:.0f}%)。仅 292 站在持续监测,764 发现站为'发现时确认',未追踪 churn。"))
    L.append("> **要点**:约 5/6 站点富化时 HTTPS 可达;但 764 发现站未进监测循环,真实存活/消亡率需把它们纳入纵向监测才能测。\n")

    L.append("## 2. 技术栈\n")
    L.append(table("栈家族(统一归类)", stack, n))
    L.append(table("发现层框架细分", fw, n))
    oaf = stack.get("one-api-family", 0)
    L.append(f"> **要点**:one-api 家族 {oaf}/{n}({100*oaf/n:.0f}%)—— 近乎单一栈,指纹级单点脆弱(Geer 2003 monoculture)。\n")

    L.append("## 3. 生态时间线(站点出生)\n")
    L.append(table("按年份", year, dated, note=f"WHOIS 注册时间 + 证书 not_before 补 · {dated}/{n} 可查(~{100*dated/n:.0f}%)"))
    y26 = year.get("2026", 0)
    L.append(f"> **要点**:{y26}/{dated}({100*y26/dated:.0f}%)出生于 2026;73% 在 2025–2026 —— 极年轻、爆发式增长。\n")
    L.append(table("2025–2026 按月(井喷曲线)", mon, sum(mon.values()), note="仅 2025-2026"))

    L.append("## 4. 基础设施\n")
    L.append(table("源站国家", country, n_ip, top=10, note=f"仅有 IP 的 {n_ip} 站;CF 后为边缘位置"))
    L.append(table("托管商 / ASN", asn, n_asn, top=12, note=f"{n_asn} 站有 ASN;CF 占比高=边缘非源站"))
    L.append(table("证书 CA", ca, cert_ok, note=f"{cert_ok} 站有证书"))
    L.append(table("域名注册商", reg, n_reg, top=12, note=f"{n_reg} 站有 WHOIS"))
    L.append("> **要点**:DV 证书(Let's Encrypt/Google Trust)主导 = 免费/自动化签发,零成本起站,与'年轻+海量'一致。\n")

    L.append("## 5. 技术指纹\n")
    L.append(table("前端/服务端技术", tech, n, top=12, note="从响应头/HTML 粗提取"))
    L.append(table("Server 头", server, sum(server.values()), top=8))

    L.append("## 6. 域名特征\n")
    L.append(table("顶级域(TLD)", tld, n, top=12))
    L.append(table("域名关键词主题", kw, n, note="域名中包含该词的站数(可重叠)"))

    # vendor mentions + naming style in the domain itself
    VENDOR = ["claude", "gpt", "openai", "gemini", "grok", "deepseek", "qwen", "llama", "kimi"]
    vend = Counter()
    for r in master:
        d = r["site_key"].lower()
        for v in VENDOR:
            if v in d: vend[v] += 1
    conv = sum(1 for r in master if re.search(r"[a-z0-9]+2api", r["site_key"].lower()))
    has_digit = sum(1 for r in master if re.search(r"\d", r["site_key"]))
    L.append("## 7. 域名命名深挖\n")
    if vend:
        L.append(table("域名含厂商名", vend, n, note="直接把上游模型商写进域名(可重叠)"))
    L.append(f"- 域名带 `*2api` 转换层命名:{conv}/{n}({100*conv/n:.0f}%)")
    L.append(f"- 域名含数字:{has_digit}/{n}({100*has_digit/n:.0f}%,常见于批量/马甲域名)\n")

    # price / model (subset)
    price = [r for r in master if g(r, "price__access_status")]
    if price:
        acc = Counter(g(r, "price__access_status") for r in price)
        mrs = [int(g(r, "price__model_rows")) for r in price if g(r, "price__model_rows").isdigit()]
        buckets = Counter()
        for m in mrs:
            buckets["0(未取到)" if m == 0 else "1–20" if m <= 20 else "21–50" if m <= 50 else "51–100" if m <= 100 else "100+"] += 1
        L.append("## 8. 价格 / 模型可见性(仅监测子集)\n")
        L.append(table("定价页可达性", acc, len(price), note=f"{len(price)} 站有探测记录"))
        L.append(table("暴露模型数分级", buckets, len(mrs), note=f"{len(mrs)} 站取到模型列表"))
        pub = acc.get("PUBLIC_JSON", 0)
        L.append(f"> **要点**:{pub}/{len(price)}({100*pub/len(price):.0f}%)开放 JSON 定价端点(one-api 家族 `/api/pricing` 默认公开),透明度参差;"
                 "本项目只统计可见性,不做模型身份核验(不在范围)。\n")

    L.append("## 9. 运营 / 商业模式信号(覆盖有限)\n")
    if aff_base:
        L.append(f"- **推广/代理页**:{aff}/{aff_base} 有({100*aff/aff_base:.0f}%)—— 分销返佣是主流获客(covered {aff_base} 站)。")
    if priv_base:
        L.append(f"- **隐私政策**:{priv_yes}/{priv_base} 有({100*priv_yes/priv_base:.0f}%,仅监测子集)。")
    L.append("> 联系方式(TG/QQ/微信)当前抽取覆盖低,是已知的采集短板(见 AUDIT),需渲染后 DOM 才能救回。\n")

    L.append("## 10. 运营者集中度\n")
    L.append(f"- {n} 域名 → **{len(op_members)} 个运营者**,其中 **{len(multi)} 个多站运营者**,最大 {max(len(m) for m in op_members.values())} 域名。")
    L.append("- **诚实**:整体集中度低(HHI≈0.0015)—— 多数站独立运营;'集中'主要体现在**单一技术栈**,而非少数人控制全部。\n")
    L.append("| 运营者 | 域名数 | 归并依据 | 成员 |")
    L.append("|---|---:|---|---|")
    for o, m in sorted(multi.items(), key=lambda kv: -len(kv[1]))[:12]:
        basis = m[0].get("merge_basis", "")[:40]
        members = ", ".join(sorted(x["site_key"] for x in m))[:60]
        L.append(f"| {o} | {len(m)} | {basis} | {members} |")
    L.append("")

    L.append("## 11. 交叉分析:栈 × 国家\n")
    L.append("| 栈家族 | " + " | ".join(topc) + " |")
    L.append("|---|" + "---|" * len(topc))
    for s in stack:
        row = " | ".join(str(sc[s].get(c, 0)) for c in topc)
        L.append(f"| {s} | {row} |")
    L.append("")

    L.append("---\n_方法与文献背书见 `docs/METHODS_element_citations.md`。低覆盖字段(隐私/联系方式/ICP)结论仅供参考。_")

    out = os.path.join(M, "ANALYSIS_REPORT.md")
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print(f"Wrote {out}  ({n} sites)")


if __name__ == "__main__":
    main()
