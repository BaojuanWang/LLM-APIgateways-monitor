#!/usr/bin/env python3
"""Rendering pilot: does a headless browser recover the coverage that static
`requests` scraping misses on JS-rendered sites?

For a small balanced sample (JS vs non-JS sites) this fetches each site TWICE —
once with requests (static HTML), once with Playwright (rendered DOM) — runs the
SAME payment / privacy detectors on both, and reports the coverage lift. Run
this BEFORE committing to a full re-crawl, to measure whether the ~5-15s/site
Playwright cost is worth it.

Local only (the sandbox can't reach these sites). Needs:
    pip install playwright requests
    playwright install chromium      # or reuse screenshot.py's browser

    python3 scripts/render_pilot.py                 # 40-site sample
    python3 scripts/render_pilot.py --n 60 --out results/tail/render_pilot.csv
"""
from __future__ import annotations
import argparse
import csv
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# same payment detectors as operations_probe.py (comparable)
PAYMENT = [
    ("alipay",      re.compile(r"支付宝|alipay", re.I)),
    ("wechat_pay",  re.compile(r"微信支付|wechat\s?pay|wxpay|weixin", re.I)),
    ("stripe",      re.compile(r"\bstripe\b", re.I)),
    ("paypal",      re.compile(r"paypal", re.I)),
    ("usdt_crypto", re.compile(r"\busdt\b|trc20|erc20|加密货币|crypto\s?pay|区块链支付", re.I)),
    ("epay",        re.compile(r"易支付|epay|码支付|彩虹支付|payjs", re.I)),
    ("faka",        re.compile(r"发卡|卡密|自动发卡|售卡|卡商|购卡", re.I)),
]
PRIVACY_RE = re.compile(r"隐私政策|隐私协议|privacy\s?policy|个人信息保护", re.I)
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
PATHS = ["/", "/pricing"]


def detect(html):
    pay = [n for n, rx in PAYMENT if rx.search(html)]
    return ("|".join(pay), "Y" if PRIVACY_RE.search(html) else "")


def is_js(tech):
    t = (tech or "").lower()
    return any(k in t for k in ("vue", "react", "next", "nuxt"))


def pick_sample(n):
    p = os.path.join(BASE, "results", "master", "master_table.csv")
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
    js, non = [], []
    for r in rows:
        d = r.get("site_key", "")
        if not d or "." not in d:
            continue
        (js if is_js(r.get("enrich__tech_stack")) else non).append(d)
    half = n // 2
    return js[:half] + non[:n - half]


def static_fetch(domain):
    import requests
    html = ""
    for path in PATHS:
        for scheme in ("https", "http"):
            try:
                r = requests.get(f"{scheme}://{domain}{path}", headers=HEADERS,
                                 timeout=8, verify=False, allow_redirects=True)
                if r.status_code == 200:
                    html += " " + r.text
                break
            except Exception:
                continue
    return html


def rendered_fetch(page, domain):
    html = ""
    for path in PATHS:
        for scheme in ("https", "http"):
            try:
                page.goto(f"{scheme}://{domain}{path}", timeout=20000,
                          wait_until="networkidle")
                html += " " + page.content()
                break
            except Exception:
                continue
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--out", default="results/tail/render_pilot.csv")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("需要 Playwright: pip install playwright && playwright install chromium")
        return 1
    import warnings, urllib3
    warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

    sample = pick_sample(args.n)
    print(f"样本 {len(sample)} 站(JS/非JS 各半),静态 vs 渲染对比…\n")
    out = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        for i, d in enumerate(sample, 1):
            s_html = static_fetch(d)
            r_html = rendered_fetch(page, d)
            s_pay, s_pri = detect(s_html)
            r_pay, r_pri = detect(r_html)
            gained = (not s_pay and r_pay) or (not s_pri and r_pri)
            print(f"[{i}/{len(sample)}] {d:30s} 静态[{s_pay or '-'}|{s_pri or '-'}] "
                  f"→ 渲染[{r_pay or '-'}|{r_pri or '-'}]{'  ⬆恢复' if gained else ''}")
            out.append({"domain": d,
                        "static_payment": s_pay, "static_privacy": s_pri,
                        "rendered_payment": r_pay, "rendered_privacy": r_pri,
                        "recovered": "Y" if gained else ""})
        browser.close()

    n = len(out)
    sp = sum(1 for r in out if r["static_payment"])
    rp = sum(1 for r in out if r["rendered_payment"])
    spr = sum(1 for r in out if r["static_privacy"])
    rpr = sum(1 for r in out if r["rendered_privacy"])
    op = os.path.join(BASE, args.out)
    os.makedirs(os.path.dirname(op), exist_ok=True)
    with open(op, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader(); w.writerows(out)

    print("\n" + "=" * 52)
    print(f"支付:  静态 {sp}/{n} ({100*sp//n}%)  →  渲染 {rp}/{n} ({100*rp//n}%)   提升 +{rp-sp}")
    print(f"隐私:  静态 {spr}/{n} ({100*spr//n}%)  →  渲染 {rpr}/{n} ({100*rpr//n}%)   提升 +{rpr-spr}")
    print("=" * 52)
    print(f"渲染回收了信息的站: {sum(1 for r in out if r['recovered'])}/{n}")
    print(f"\nWrote {args.out}")
    print("若提升明显 → 值得把采集器全量升级到 Playwright;若微弱 → 低覆盖多是真缺,不必全量。")


if __name__ == "__main__":
    raise SystemExit(main())
