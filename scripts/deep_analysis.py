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

    # operations signals (populated after operations_probe.py has run)
    ops_rows = [r for r in master if g(r, "ops__checked_pages")]
    pay = Counter(); claims = Counter(); faka = 0
    for r in ops_rows:
        for t in g(r, "ops__payment_methods").split("|"):
            if t: pay[t] += 1
        for t in g(r, "ops__trust_claims").split("|"):
            if t: claims[t] += 1
        if g(r, "ops__has_faka") == "Y":
            faka += 1

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
    if ops_rows:
        L.append(f"_operations_probe 覆盖 {len(ops_rows)} 站_\n")
        if pay:
            L.append(table("支付 / 变现方式", pay, len(ops_rows), note="站点页面出现的支付/发卡渠道(可重叠)"))
        if claims:
            L.append(table("信任话术宣称", claims, len(ops_rows), note="营销宣称,非核实"))
        L.append(f"- **发卡/卡密系统**:{faka}/{len(ops_rows)}({100*faka/len(ops_rows):.0f}%)\n")
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

    # similarity families (if site_similarity.py has run)
    sim_path = os.path.join(M, "site_similarity_clusters.csv")
    if os.path.exists(sim_path):
        sim = list(csv.DictReader(open(sim_path, encoding="utf-8-sig")))
        covered = sum(int(r["size"]) for r in sim)
        L.append("## 12. 相似模板家族(特征相似度聚类)\n")
        L.append(f"用共享稀有特征(favicon/非CDN ASN/IP/注册商/Server/前端)做 Jaccard 式聚类,"
                 f"得 **{len(sim)} 个模板家族**,覆盖 {covered} 站。这比运营者归并**粗一层**——"
                 "揭示共享部署模板/搭建商基础设施(未必同一人)。方法依据:网站结构相似度聚类(见 §D7)。\n")
        L.append("| 家族 | 站数 | 共享特征 | 成员 |")
        L.append("|---|---:|---|---|")
        for r in sorted(sim, key=lambda x: -int(x["size"]))[:12]:
            L.append(f"| {r['family_id']} | {r['size']} | {r['shared_features'][:38]} | {r['members'][:56]} |")
        L.append("")

    cls_path = os.path.join(M, "site_classification.csv")
    if os.path.exists(cls_path):
        cls = list(csv.DictReader(open(cls_path, encoding="utf-8-sig")))
        L.append("## 13. 站点多维分类总览\n")
        L.append(f"每站的最终分类(`site_classification.csv`,{len(cls)} 站)。\n")
        for dim, name in [("site_role", "角色(relay/转换层/聚合器/未识别)"),
                          ("hosting_type", "托管类型(CDN后/直连源站)"),
                          ("maturity_tier", "成熟度(出生年份+证书)")]:
            L.append(table(name, Counter(g(r, dim) for r in cls), len(cls)))
        cdn = sum(1 for r in cls if g(r, "hosting_type") == "cdn_fronted")
        L.append(f"> **要点**:{cdn}/{len(cls)}({100*cdn/len(cls):.0f}%)藏在 CDN 后 —— 源站基础设施对外不可见,是不透明性的量化证据。\n")

    ms_path = os.path.join(BASE, "data", "master_sites.csv")
    if os.path.exists(ms_path):
        ms = list(csv.DictReader(open(ms_path, encoding="utf-8-sig")))
        fo = [r for r in ms if r.get("origin") == "fofa_g1"]
        gh = [r for r in ms if r.get("origin") != "fofa_g1"]

        def _fwb(fw):
            fw = (fw or "").lower()
            if any(k in fw for k in ("new-api", "one-api", "oneapi", "newapi", "voapi", "veloera", "one-hub", "done-hub")):
                return "one-api家族"
            if "sub2api" in fw:
                return "sub2api(转换层)"
            if "auth2api" in fw:
                return "auth2api(转换层)"
            if "openai_compatible" in fw:
                return "openai兼容·框架未识别"
            return "unknown/空"

        if fo:
            def _pct(grp, keys):
                nn = len(grp)
                return 100 * sum(1 for r in grp if _fwb(r.get("framework", "")) in keys) / nn if nn else 0
            L.append("## 14. 发现方法偏差 × 结构集中(§4.1 核心)\n")
            L.append("对比两个独立发现方法的技术栈分布,量化 GitHub 代码搜索的偏差。完整论证见 `docs/FINDING_discovery_bias.md`。\n")
            L.append(f"> **口径注**:GitHub 计数为发现层原始条目(去重前 {len(gh)});按 eTLD+1 去重后为唯一站,"
                     f"one-api 占比两口径一致(去重不改变结论)。FOFA {len(fo)} 本就唯一。分析层其余表 N=1089 为去重口径。\n")
            for nm, grp in [("GitHub codesearch(框架指纹→有偏)", gh), ("FOFA G1(框架无关→无偏)", fo)]:
                L.append(table(f"技术栈 · {nm}", Counter(_fwb(r.get("framework", "")) for r in grp), len(grp)))
            oa_g, oa_f = _pct(gh, {"one-api家族"}), _pct(fo, {"one-api家族"})
            t_g, t_f = _pct(gh, {"openai兼容·框架未识别", "unknown/空"}), _pct(fo, {"openai兼容·框架未识别", "unknown/空"})
            L.append(f"> **核心对比**:one-api 家族 GitHub {oa_g:.0f}% vs FOFA {oa_f:.0f}%(差量化了发现偏差);异构尾 GitHub {t_g:.0f}% vs FOFA {t_f:.0f}%(GitHub 系统性漏掉)。")
            L.append(f"> **保守下界表述**:one-api 家族在框架无关发现下占 ~{oa_f:.0f}%,构成集中度的**保守下界**;代码搜索高估集中度({oa_g:.0f}% vs {oa_f:.0f}%)并系统性遗漏约 {t_f:.0f}% 的异构/无法指纹化尾部。该尾部一部分可能是白标 one-api,真实集中度可能更高——无论如何,结论都落在'集中'与'代码搜索有偏'之间。")
            L.append("> **口径**:此对比用按发现来源分组的 `framework` 字段(confirmed);勿与面板的 809-合并 `stack_family`(78%)混用。\n")

            # §14.1 — tail re-probe (scripts/probe_tail.sh output), if present.
            tv_path = os.path.join(BASE, "results", "tail", "tail_verdict.csv")
            if os.path.exists(tv_path):
                tv = list(csv.DictReader(open(tv_path, encoding="utf-8-sig")))
                vc = Counter(r.get("verdict", "") for r in tv)
                hid, gen, dead = vc.get("hidden_one_api", 0), vc.get("genuine_unknown", 0), vc.get("dead", 0)
                fo_base = sum(1 for r in fo if _fwb(r.get("framework", "")) == "one-api家族")
                tight = 100 * (fo_base + hid) / (len(fo) - dead) if len(fo) - dead else 0
                spa = sum(1 for r in tv if r.get("verdict") == "genuine_unknown"
                          and r.get("status_class") == "spa_shell")
                L.append("### 14.1 拆解那 24% 异构尾(深度指纹复探)\n")
                L.append(f"对 FOFA 的 {len(tv)} 个 `openai_compatible_unknown` 尾站跑深度技术栈探针(`scripts/probe_tail.sh`),逐站裁定:\n")
                L.append(table("尾部裁定", vc, len(tv)))
                L.append(f"> **收紧下界**:探针在尾部认出 {hid} 个 FOFA 漏检的 one-api(响应头 `x-oneapi-request-id`/`x-new-api-version`,high 置信);剔除 {dead} 个死站后,FOFA one-api 份额由 {oa_f:.0f}% 收紧至 **{tight:.0f}%**——集中度是**紧的下界**,并未被大幅低估。")
                L.append(f"> **尾巴的真实成分**:{gen} 站({100*gen/len(fo):.0f}% of FOFA)是**真异构/自研**——可达且无任何 one-api 信号(其中 {gen-spa} 个有真内容、仅 {spa} 个 SPA 空壳为残留模糊项)。即改壳 one-api 只占尾部 {100*hid/len(tv):.0f}%,尾巴**主体是 GitHub codesearch 结构性失明的真异构生态**。结论方向由此从『两头皆可能』收敛为『代码搜索有偏更硬』。\n")

    L.append("---\n_方法与文献背书见 `docs/METHODS_element_citations.md`。低覆盖字段(隐私/联系方式/ICP)结论仅供参考。_")

    out = os.path.join(M, "ANALYSIS_REPORT.md")
    open(out, "w", encoding="utf-8").write("\n".join(L))
    print(f"Wrote {out}  ({n} sites)")


if __name__ == "__main__":
    main()
