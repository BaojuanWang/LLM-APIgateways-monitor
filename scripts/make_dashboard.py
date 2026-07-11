#!/usr/bin/env python3
"""Regenerate the ecosystem distribution dashboard from the current data.

Reads the analysis outputs (site_stack_labels.csv, operator_clusters.csv,
master_table.csv) and writes a self-contained HTML dashboard with fresh numbers
baked in. Run it whenever the data changes; then re-publish the HTML to refresh
the hosted artifact (same file path -> same URL).

    python3 scripts/build_master.py
    python3 scripts/operator_matching.py
    python3 scripts/site_characterization.py
    python3 scripts/make_dashboard.py        # -> results/master/ecosystem_dashboard.html
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M = os.path.join(BASE_DIR, "results", "master")


def _load(name):
    path = os.path.join(M, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _top(counter, top=None):
    return [[k, v] for k, v in counter.most_common(top)]


def build_data():
    labels = _load("site_stack_labels.csv")
    master = _load("master_table.csv")
    ops = _load("operator_clusters.csv")
    if not labels:
        sys.exit("error: run site_characterization.py first (no site_stack_labels.csv)")

    n = len(labels)
    enriched = [r for r in labels if r.get("enriched") == "yes"]
    enr = len(enriched)
    mk = {r["site_key"]: r for r in master}

    stack = Counter(r["stack_family"] for r in labels)
    fw = Counter((mk.get(r["site_key"], {}).get("disc__framework") or "(未进发现层)") for r in labels)
    tld = Counter(r["tld"] for r in labels)
    host = Counter(r["hosting"] or "(未知)" for r in enriched)
    country = Counter(r["ip_country"] or "(未知)" for r in enriched)
    tier = Counter(r["signal_tier"] or "(无·非发现层)" for r in labels)

    # operator cluster-size distribution
    seen, sizes = set(), Counter()
    for r in ops:
        op = r["operator_id"]
        if op not in seen:
            seen.add(op)
            sizes[int(r["cluster_size"])] += 1
    n_ops = len(seen) if seen else n
    multi = sum(v for k, v in sizes.items() if k > 1)
    size_rows = [[f"{k} 域名" + ("(独立)" if k == 1 else ""), v] for k, v in sorted(sizes.items())]

    # site "birth" year: WHOIS creation date, falling back to cert not_before
    # (first HTTPS cert ~ went live). Combined coverage ~99% vs ~91% WHOIS alone.
    reg = Counter()
    for r in labels:
        row = mk.get(r["site_key"], {})
        d = (row.get("enrich__whois_reg_date") or "")[:4]
        if not d.isdigit():
            d = (row.get("enrich__ssl_not_before") or "")[:4]
        if d.isdigit():
            reg["≤2022" if int(d) <= 2022 else d] += 1
    reg_dated = sum(reg.values())
    reg_rows = [[k, reg.get(k, 0)] for k in ("≤2022", "2023", "2024", "2025", "2026") if reg.get(k)]

    one_api = stack.get("one-api-family", 0)
    cf = sum(v for k, v in host.items() if "cloudflare" in k.lower())
    y2026 = reg.get("2026", 0)

    # ---- extra detailed features ----
    def _g(row, c): return (row.get(c) or "").strip()

    def _health(row):
        st = _g(row, "monitor__online_status"); cert = bool(_g(row, "enrich__ssl_fingerprint"))
        if st == "ONLINE": return "在线(监测)"
        if st == "ONLINE_LOGIN_REQUIRED": return "在线·需登录"
        if st == "CLOUDFLARE_OR_BLOCKED": return "被挡/CF"
        if st in ("DNS_FAIL", "TIMEOUT", "HTTP_ERROR", "SERVICE_STOPPED"): return "疑似失效"
        if cert: return "HTTPS可达·未监测"
        return "未响应"
    hstate = Counter(_health(mk.get(r["site_key"], {})) for r in labels)

    def _ca(s):
        s = s.lower()
        for key, name in [("let's encrypt", "Let's Encrypt"), ("lets encrypt", "Let's Encrypt"),
                          ("google trust", "Google Trust"), ("zerossl", "ZeroSSL"),
                          ("digicert", "DigiCert"), ("trustasia", "TrustAsia"), ("sectigo", "Sectigo")]:
            if key in s: return name
        return "(其它)"
    ca = Counter(_ca(_g(mk[r["site_key"]], "enrich__ssl_issuer")) for r in labels
                 if _g(mk[r["site_key"]], "enrich__ssl_issuer"))
    ca_base = sum(ca.values())
    registrar = Counter(_g(mk[r["site_key"]], "enrich__whois_registrar")[:26] for r in labels
                        if _g(mk[r["site_key"]], "enrich__whois_registrar"))
    reg_base = sum(registrar.values())
    tech = Counter()
    for r in labels:
        for t in (_g(mk[r["site_key"]], "enrich__tech_stack") or "").split(","):
            t = t.strip()
            if t: tech[t] += 1
    monc = Counter()
    for r in labels:
        row = mk[r["site_key"]]; d = _g(row, "enrich__whois_reg_date") or _g(row, "enrich__ssl_not_before")
        if d[:7].startswith("2026"): monc[d[:7]] += 1
    mon_base = sum(monc.values())
    KW = ["api", "ai", "gpt", "chat", "claude", "code", "hub", "proxy", "token", "new", "one"]
    kw = Counter()
    for r in labels:
        d = r["site_key"].lower()
        for k in KW:
            if k in d: kw[k] += 1

    VENDOR = ["claude", "gpt", "openai", "gemini", "grok", "deepseek", "qwen", "llama", "kimi"]
    vend = Counter()
    for r in labels:
        d = r["site_key"].lower()
        for v in VENDOR:
            if v in d: vend[v] += 1

    def _hhi(counter):
        tot = sum(counter.values())
        return sum((c / tot) ** 2 for c in counter.values()) * 10000 if tot else 0
    host_hhi, reg_hhi = _hhi(host), _hhi(registrar)

    # template families (site_similarity.py output, if present)
    fam_rows = []
    fam_covered = 0
    sim_path = os.path.join(M, "site_similarity_clusters.csv")
    if os.path.exists(sim_path):
        sim = list(csv.DictReader(open(sim_path, encoding="utf-8-sig")))
        fam_covered = sum(int(r["size"]) for r in sim)
        for r in sorted(sim, key=lambda x: -int(x["size"]))[:12]:
            lab = (r["shared_features"].split(";")[0] or r["family_id"])[:22]
            fam_rows.append([f"{lab} ({r['family_id'][:12]})", int(r["size"])])

    # capstone classification (classify_sites.py output, if present)
    role, htype, mat = Counter(), Counter(), Counter()
    cls_path = os.path.join(M, "site_classification.csv")
    if os.path.exists(cls_path):
        for r in csv.DictReader(open(cls_path, encoding="utf-8-sig")):
            role[r.get("site_role", "") or "?"] += 1
            htype[r.get("hosting_type", "") or "?"] += 1
            mat[r.get("maturity_tier", "") or "?"] += 1

    # ── §4.1 discovery-method bias: GitHub codesearch (framework fingerprint,
    #    biased toward one-api) vs FOFA cyberspace mapping (framework-agnostic).
    #    Reads the raw discovery list so the framework field is grouped by the
    #    method that found the site, keeping the two distributions comparable.
    def _fwb(fw):
        fw = (fw or "").lower()
        if any(k in fw for k in ("new-api", "one-api", "oneapi", "newapi", "voapi",
                                 "veloera", "one-hub", "done-hub")):
            return "one-api 家族"
        if "sub2api" in fw:
            return "sub2api 转换层"
        if "openai_compatible" in fw or "unknown" in fw or not fw:
            return "openai兼容·未识别尾"
        return fw
    ms_gh, ms_fo = Counter(), Counter()
    ms_path = os.path.join(BASE_DIR, "data", "master_sites.csv")
    if os.path.exists(ms_path):
        for r in csv.DictReader(open(ms_path, encoding="utf-8-sig")):
            b = _fwb(r.get("framework", ""))
            (ms_fo if r.get("origin") == "fofa_g1" else ms_gh)[b] += 1
    gh_n, fo_n = sum(ms_gh.values()), sum(ms_fo.values())
    gh_oaf = ms_gh.get("one-api 家族", 0)
    fo_oaf = ms_fo.get("one-api 家族", 0)

    stats = [
        {"n": str(n), "lab": "分析站点总数", "cap": f"GitHub 发现 {gh_n} ∪ FOFA {fo_n} ∪ 监测"},
        {"n": f"{round(100*one_api/n)}%", "lab": "one-api 家族占比",
         "cap": "技术近乎单一栈 · 指纹级单点脆弱", "warn": True},
        {"n": str(n_ops), "lab": "归并后运营者数",
         "cap": f"{n} 域名 → {multi} 个多站运营者"},
        {"n": f"{round(100*cf/enr)}%" if enr else "—", "lab": "托管于 Cloudflare",
         "cap": f"占已富化 {enr} 站 · CDN 主导"},
        {"n": f"{round(100*y2026/reg_dated)}%" if reg_dated else "—", "lab": "站点出生于 2026 年",
         "cap": f"生态极年轻 · {reg_dated} 站有时间数据", "warn": True},
        {"n": (f"{round(100*gh_oaf/gh_n)}→{round(100*fo_oaf/fo_n)}%" if gh_n and fo_n else "—"),
         "lab": "one-api 占比:GitHub→FOFA",
         "cap": f"§4.1 发现偏差 · 框架无关下 {round(100*fo_oaf/fo_n) if fo_n else 0}% 为集中度保守下界", "warn": True},
    ]
    charts = [
        {"t": "技术栈家族", "note": f"三源统一归类 · base {n}", "base": n,
         "neutral": ["unlabeled", "confirmed-unknown", "openai-compatible-unknown"],
         "d": _top(stack)},
        {"t": "发现层原始框架标注", "note": f"发现层 codesearch 直采 · base {n}", "base": n,
         "neutral": ["(未进发现层)"], "d": _top(fw)},
        {"t": "技术栈 · GitHub 发现(框架指纹→有偏)",
         "note": f"{gh_n} 站 · 代码搜索靠框架指纹→自然偏 one-api({round(100*gh_oaf/gh_n) if gh_n else 0}%)",
         "base": gh_n or 1, "neutral": ["openai兼容·未识别尾"], "d": _top(ms_gh)},
        {"t": "技术栈 · FOFA 发现(框架无关→无偏)",
         "note": f"{fo_n} 站 · 网络空间测绘 · one-api 仍 {round(100*fo_oaf/fo_n) if fo_n else 0}%=集中真实 · 异构尾补回",
         "base": fo_n or 1, "neutral": ["openai兼容·未识别尾"], "d": _top(ms_fo)},
        {"t": "顶级域(TLD)", "note": f"按注册域后缀 · base {n}", "base": n,
         "neutral": [], "d": _top(tld, 12)},
        {"t": "托管商 / ASN", "note": f"仅已富化 {enr} 站 · ASN 归属 · 集中度 HHI {host_hhi:.0f}", "base": enr,
         "neutral": [k for k in host if "cloudflare" in k.lower()], "d": _top(host, 8)},
        {"t": "源站 IP 国家", "note": f"仅已富化 {enr} 站 · CDN 后为边缘位置", "base": enr,
         "neutral": ["(未知)"], "d": _top(country, 8)},
        {"t": "验证信号强度分层", "note": f"发现层确认信号 · base {n}", "base": n,
         "neutral": ["(无·非发现层)"], "d": _top(tier)},
        {"t": "运营者簇规模分布", "note": f"归并后每运营者控制域名数 · {n_ops} 个运营者",
         "base": n_ops, "neutral": [], "d": size_rows},
        {"t": "站点出生年份(生态时间线)",
         "note": f"WHOIS 注册时间(证书 not_before 补) · {reg_dated}/{n} 站可查(~99%) · base {reg_dated}",
         "base": reg_dated, "neutral": [], "d": reg_rows},
        {"t": "2026 按月出生(井喷曲线)", "note": f"2026 各月新站 · {mon_base} 站",
         "base": mon_base or 1, "neutral": [], "d": [[k, monc[k]] for k in sorted(monc)]},
        {"t": "存活状态", "note": f"HTTPS 握手≈活着 · base {n}", "base": n,
         "neutral": ["疑似失效", "未响应", "被挡/CF"], "d": _top(hstate)},
        {"t": "证书 CA(签发机构)", "note": f"{ca_base} 站有证书 · 免费 DV 主导 = 零成本起站",
         "base": ca_base or 1, "neutral": [], "d": _top(ca)},
        {"t": "域名注册商", "note": f"{reg_base} 站有 WHOIS · 集中度 HHI {reg_hhi:.0f}", "base": reg_base or 1,
         "neutral": [], "d": _top(registrar, 10)},
        {"t": "前端 / 服务端技术", "note": "响应头 + HTML 粗提取", "base": n,
         "neutral": [], "d": _top(tech, 10)},
        {"t": "域名关键词主题", "note": "域名中含该词的站数(可重叠)", "base": n,
         "neutral": [], "d": _top(kw)},
        {"t": "域名含上游厂商名", "note": "把模型商写进域名(claude/gpt/...,可重叠)", "base": n,
         "neutral": [], "d": _top(vend)},
        {"t": "相似模板家族 Top(搭建商层)", "note": f"共享稀有特征聚类 · {fam_covered}/{n} 站进入家族 · Jaccard(§D7)",
         "base": n, "neutral": [], "d": fam_rows or [["(需先跑 site_similarity.py)", 0]]},
        {"t": "站点角色分类", "note": "relay / 转换层 / 聚合器 / 未识别", "base": n,
         "neutral": ["unidentified"], "d": _top(role) or [["(需跑 classify_sites.py)", 0]]},
        {"t": "托管类型(不透明性)", "note": "CDN 后 = 源站不可见 · 直连 = 源站可见", "base": n,
         "neutral": ["cdn_fronted", "unknown"], "d": _top(htype) or [["(需跑 classify_sites.py)", 0]]},
        {"t": "站点成熟度分层", "note": "出生年份 + 是否有专属证书", "base": n,
         "neutral": ["unknown"], "d": _top(mat) or [["(需跑 classify_sites.py)", 0]]},
    ]
    snapshot = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {"N": n, "ENR": enr, "OPS": n_ops, "stats": stats, "charts": charts, "snapshot": snapshot}


def render(data):
    payload = (
        f"const N={data['N']}, ENR={data['ENR']};\n"
        f"const stats={json.dumps(data['stats'], ensure_ascii=False)};\n"
        f"const charts={json.dumps(data['charts'], ensure_ascii=False)};"
    )
    return (TEMPLATE.replace("/*__DATA__*/", payload)
            .replace("__SNAPSHOT__", data["snapshot"])
            .replace("__N__", str(data["N"])))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(M, "ecosystem_dashboard.html"))
    args = ap.parse_args()
    data = build_data()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render(data))
    print(f"Wrote {args.out}")
    print(f"  {data['N']} sites · {data['OPS']} operators · snapshot {data['snapshot']}")
    print("  Re-publish this file to the artifact URL to refresh the hosted view.")


TEMPLATE = r"""<title>LLM 中转站生态 · 分布总览</title>
<style>
  :root{
    --plane:#f4f5f7; --surface:#fcfcfd; --ink:#0e1116; --ink-2:#4a5261; --muted:#8b93a3;
    --hairline:rgba(14,17,22,.09); --series:#2a78d6; --series-track:#eef1f6;
    --neutralbar:#b7bdc9; --neutraltrack:#eceef2; --accent:#d03b3b;
    --shadow:0 1px 2px rgba(14,17,22,.04),0 8px 24px rgba(14,17,22,.05); --r:14px;
  }
  @media (prefers-color-scheme:dark){:root{
    --plane:#0c0d0f; --surface:#17191d; --ink:#f4f6fa; --ink-2:#aeb6c4; --muted:#7d8698;
    --hairline:rgba(255,255,255,.09); --series:#4f97ee; --series-track:#22262d;
    --neutralbar:#3f4552; --neutraltrack:#22262d; --accent:#ec6a6a;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 12px 30px rgba(0,0,0,.35);
  }}
  :root[data-theme="light"]{
    --plane:#f4f5f7; --surface:#fcfcfd; --ink:#0e1116; --ink-2:#4a5261; --muted:#8b93a3;
    --hairline:rgba(14,17,22,.09); --series:#2a78d6; --series-track:#eef1f6;
    --neutralbar:#b7bdc9; --neutraltrack:#eceef2; --accent:#d03b3b;
    --shadow:0 1px 2px rgba(14,17,22,.04),0 8px 24px rgba(14,17,22,.05);
  }
  :root[data-theme="dark"]{
    --plane:#0c0d0f; --surface:#17191d; --ink:#f4f6fa; --ink-2:#aeb6c4; --muted:#7d8698;
    --hairline:rgba(255,255,255,.09); --series:#4f97ee; --series-track:#22262d;
    --neutralbar:#3f4552; --neutraltrack:#22262d; --accent:#ec6a6a;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 12px 30px rgba(0,0,0,.35);
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--plane);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
    line-height:1.5;-webkit-font-smoothing:antialiased;padding:clamp(18px,4vw,44px) clamp(14px,4vw,44px) 60px}
  .wrap{max-width:1080px;margin:0 auto}
  header{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;flex-wrap:wrap;margin-bottom:8px}
  .eyebrow{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--series);font-weight:600}
  h1{font-size:clamp(24px,3.4vw,34px);font-weight:680;letter-spacing:-.02em;text-wrap:balance;margin-top:6px}
  .sub{color:var(--ink-2);font-size:15px;margin-top:8px;max-width:60ch}
  .toggle{background:var(--surface);border:1px solid var(--hairline);color:var(--ink-2);border-radius:10px;
    padding:8px 12px;font:inherit;font-size:13px;cursor:pointer;box-shadow:var(--shadow)}
  .toggle:hover{color:var(--ink)} .toggle:focus-visible{outline:2px solid var(--series);outline-offset:2px}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:26px 0 30px}
  .stat{background:var(--surface);border:1px solid var(--hairline);border-radius:var(--r);padding:18px 20px;box-shadow:var(--shadow)}
  .stat .n{font-size:34px;font-weight:700;letter-spacing:-.02em;line-height:1.05}
  .stat .n.warn{color:var(--accent)} .stat .lab{font-size:13px;color:var(--ink-2);margin-top:6px}
  .stat .cap{font-size:12px;color:var(--muted);margin-top:2px}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
  .card{background:var(--surface);border:1px solid var(--hairline);border-radius:var(--r);padding:20px 20px 22px;box-shadow:var(--shadow)}
  .card h3{font-size:15px;font-weight:640;letter-spacing:-.01em}
  .card .note{font-size:12px;color:var(--muted);margin-top:2px;margin-bottom:14px}
  .card.span2{grid-column:1/-1}
  .bars{display:flex;flex-direction:column;gap:9px}
  .row{display:grid;grid-template-columns:130px 1fr auto;align-items:center;gap:12px;cursor:default}
  .row .k{font-size:13px;color:var(--ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .track{position:relative;height:15px;background:var(--series-track);border-radius:5px;overflow:hidden}
  .track.neutral{background:var(--neutraltrack)}
  .fill{position:absolute;inset:0 auto 0 0;background:var(--series);border-radius:5px;min-width:3px;transition:filter .12s ease}
  .fill.neutral{background:var(--neutralbar)}
  .row:hover .fill{filter:brightness(1.08) saturate(1.05)}
  .v{font-size:13px;font-variant-numeric:tabular-nums;color:var(--ink);font-weight:560;white-space:nowrap}
  .v .pct{color:var(--muted);font-weight:400;margin-left:5px;font-size:12px}
  .legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:14px;font-size:12px;color:var(--ink-2)}
  .legend span{display:inline-flex;align-items:center;gap:6px}
  .dot{width:10px;height:10px;border-radius:3px;display:inline-block}
  .dot.s{background:var(--series)} .dot.n{background:var(--neutralbar)}
  footer{margin-top:28px;padding-top:18px;border-top:1px solid var(--hairline);font-size:12.5px;color:var(--muted);line-height:1.65}
  footer b{color:var(--ink-2);font-weight:600}
  #tip{position:fixed;pointer-events:none;z-index:20;background:var(--ink);color:var(--plane);font-size:12px;
    padding:6px 9px;border-radius:7px;opacity:0;white-space:nowrap;font-variant-numeric:tabular-nums;box-shadow:var(--shadow);transition:opacity .1s ease}
  @media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
<div class="wrap">
  <header>
    <div>
      <div class="eyebrow">生态测绘 · 快照 __SNAPSHOT__</div>
      <h1>LLM 中转站生态 · 分布总览</h1>
      <p class="sub">__N__ 个站点(发现层已确认 + 监测,按注册域归并)的技术栈、TLD、托管、运营者集中度分布。归类依据见 <b>METHODS_element_citations</b>。</p>
    </div>
    <button class="toggle" id="tog" aria-label="切换深浅色">◐ 主题</button>
  </header>
  <section class="stats" id="stats"></section>
  <section class="grid" id="grid"></section>
  <footer>
    <b>口径与局限</b><br>
    · 站点总集 = 发现层(codesearch 确认)∪ 监测,按 eTLD+1 归并去重。<br>
    · <b>托管 / IP 国家</b>仅覆盖已富化站(证书/IP/favicon 只对这批采过);其余待富化。<br>
    · <b>unlabeled</b> = 发现层未覆盖且无富化 tech_stack 的站,待 tech_stack 探针补全。<br>
    · 快照非定稿:发现层 v2 会让 domain 数上涨,换输入重跑即刷新。<br>
    · 归类方法均有文献背书(WASABO USENIX'24 / Geer 2003 monoculture / Zembruzki'22 HHI)。
  </footer>
</div>
<div id="tip"></div>
<script>
/*__DATA__*/
const $=(s,r=document)=>r.querySelector(s);
const statsEl=$("#stats"),gridEl=$("#grid"),tip=$("#tip");
stats.forEach(s=>{const el=document.createElement("div");el.className="stat";
  el.innerHTML=`<div class="n${s.warn?' warn':''}">${s.n}</div><div class="lab">${s.lab}</div><div class="cap">${s.cap}</div>`;
  statsEl.appendChild(el);});
charts.forEach(c=>{
  const max=Math.max(...c.d.map(x=>x[1]));
  const span=(c.t.indexOf("原始框架")>=0||c.t.indexOf("TLD")>=0||c.t.indexOf("时间线")>=0||c.t.indexOf("井喷")>=0||c.t.indexOf("注册商")>=0||c.t.indexOf("模板家族")>=0)?" span2":"";
  const card=document.createElement("div");card.className="card"+span;
  const hasN=c.d.some(x=>c.neutral.indexOf(x[0])>=0);
  card.innerHTML=`<h3>${c.t}</h3><div class="note">${c.note}</div><div class="bars"></div>`;
  const bars=$(".bars",card);
  c.d.forEach(([k,v])=>{const isN=c.neutral.indexOf(k)>=0,pct=(100*v/c.base).toFixed(1);
    const row=document.createElement("div");row.className="row";
    row.innerHTML=`<div class="k" title="${k}">${k}</div>`+
      `<div class="track${isN?' neutral':''}"><div class="fill${isN?' neutral':''}" style="width:${Math.max(2,100*v/max).toFixed(1)}%"></div></div>`+
      `<div class="v">${v}<span class="pct">${pct}%</span></div>`;
    row.addEventListener("mousemove",e=>{tip.textContent=`${k} · ${v} 站 · ${pct}%`;tip.style.opacity="1";
      tip.style.left=Math.min(e.clientX+12,innerWidth-tip.offsetWidth-8)+"px";tip.style.top=(e.clientY-34)+"px";});
    row.addEventListener("mouseleave",()=>tip.style.opacity="0");
    bars.appendChild(row);});
  if(hasN){const lg=document.createElement("div");lg.className="legend";
    lg.innerHTML=`<span><i class="dot s"></i>已识别 / 主体</span><span><i class="dot n"></i>未识别 · 待分类 · CDN</span>`;
    card.appendChild(lg);}
  gridEl.appendChild(card);});
const root=document.documentElement;
$("#tog").addEventListener("click",()=>root.setAttribute("data-theme",root.getAttribute("data-theme")==="dark"?"light":"dark"));
</script>
"""


if __name__ == "__main__":
    main()
