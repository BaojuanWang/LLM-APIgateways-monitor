#!/usr/bin/env python3
"""Operations probe: payment methods, trust claims, and contacts.

Best-effort extraction of business-model signals from each site's public pages:
  * payment / cash-out methods (Alipay, WeChat Pay, Stripe, PayPal, USDT,
    易支付/发卡 card systems),
  * marketing trust claims ("no logging", "no data resale", "not diluted",
    stability/refund promises),
  * contact channels, scanning both link hrefs and text (recovers more than a
    text-only regex, though JS-rendered footers still need a headless browser —
    see the note below).

Reads the same platform list as the other collectors (hvoy + manual +
discovery). Fetches the homepage plus a few common commerce paths, rate-limited
and read-only. Writes data/operations.csv incrementally (safe to resume).

    python3 scripts/operations_probe.py

Note: contacts here improve on contacts.py by scanning href attributes and
multiple pages, but maximum recall needs a rendered DOM (playwright). This stays
requests-only so it runs with just `pip install requests`.
"""
from __future__ import annotations

import csv
import re
import time
import random
import warnings
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
HVOY_CSV = DATA_DIR / "hvoy_latest.csv"
MANUAL_CSV = DATA_DIR / "manual_sites.csv"
MASTER_SITES_CSV = DATA_DIR / "master_sites.csv"
OUT_CSV = DATA_DIR / "operations.csv"

TIMEOUT = 10
PATHS = ["/", "/pricing", "/topup", "/recharge", "/about"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

PAYMENT = [
    ("alipay",      re.compile(r"支付宝|alipay", re.I)),
    ("wechat_pay",  re.compile(r"微信支付|wechat\s?pay|wxpay|weixin", re.I)),
    ("stripe",      re.compile(r"\bstripe\b", re.I)),
    ("paypal",      re.compile(r"paypal", re.I)),
    ("usdt_crypto", re.compile(r"\busdt\b|trc20|erc20|加密货币|crypto\s?pay|区块链支付", re.I)),
    ("epay",        re.compile(r"易支付|epay|码支付|彩虹支付|payjs", re.I)),
    ("faka",        re.compile(r"发卡|卡密|自动发卡|售卡|卡商|购卡", re.I)),
]
CLAIMS = [
    ("no_log",       re.compile(r"不记录|不存储|不保存|无日志|不留存|no[-\s]?log", re.I)),
    ("privacy_first", re.compile(r"不(出售|售卖|卖).{0,4}数据|隐私优先|保护(您的)?隐私|数据安全", re.I)),
    ("no_dilution",  re.compile(r"不掺水|无掺水|原生|纯净|官转|官方直连|直连|正规渠道", re.I)),
    ("stability",    re.compile(r"稳定|高可用|不宕机|\bSLA\b|7[x×]24|24\s?小时", re.I)),
    ("refund",       re.compile(r"退款|不满意.{0,3}退|包退|无理由退", re.I)),
]
TELEGRAM = re.compile(r"(?:t\.me|telegram\.me)/([a-zA-Z0-9_+]{3,})", re.I)
QQ = re.compile(r"(?:qq群|群号|加群|q群)[^\d]{0,6}(\d{5,12})", re.I)
DISCORD = re.compile(r"discord\.(?:gg|com/invite)/([a-zA-Z0-9]+)", re.I)
EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

FIELDS = ["domain", "payment_methods", "has_faka", "trust_claims",
          "telegram", "qq", "discord", "email", "checked_pages", "last_checked"]


def extract_domain(url):
    if not url:
        return None
    url = re.sub(r"^https?://", "", str(url).strip())
    return url.split("/")[0].split("?")[0].lower() or None


def load_platforms():
    domains = {}
    for path in (HVOY_CSV, MANUAL_CSV, MASTER_SITES_CSV):
        if not path.exists():
            continue
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                d = extract_domain(row.get("domain", ""))
                if d:
                    domains.setdefault(d, True)
    return list(domains)


def load_existing():
    if not OUT_CSV.exists():
        return {}
    with open(OUT_CSV, encoding="utf-8-sig") as f:
        return {r["domain"]: r for r in csv.DictReader(f)}


def save(records):
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(records.values())


def fetch_pages(domain):
    """Return (concatenated_html, n_pages_ok)."""
    html, ok = [], 0
    for path in PATHS:
        for scheme in ("https", "http"):
            try:
                r = requests.get(f"{scheme}://{domain}{path}", headers=HEADERS,
                                 timeout=TIMEOUT, verify=False, allow_redirects=True)
                if r.status_code == 200 and r.text:
                    html.append(r.text[:120_000])
                    ok += 1
                    break
            except Exception:
                continue
    return "\n".join(html), ok


def analyze(html):
    pay = [name for name, rx in PAYMENT if name != "faka" and rx.search(html)]
    faka = "Y" if next((rx for n, rx in PAYMENT if n == "faka"), re.compile("x")).search(html) else ""
    claims = [name for name, rx in CLAIMS if rx.search(html)]
    tg = sorted({f"t.me/{m}" for m in TELEGRAM.findall(html)})[:4]
    qq = sorted(set(QQ.findall(html)))[:4]
    dc = sorted({f"discord.gg/{m}" for m in DISCORD.findall(html)})[:2]
    # e-mails: drop obvious asset/example noise
    mails = sorted({m for m in EMAIL.findall(html)
                    if not re.search(r"\.(png|jpg|jpeg|gif|svg|webp)$", m, re.I)
                    and "example." not in m and "@sentry" not in m})[:4]
    return {
        "payment_methods": "|".join(pay),
        "has_faka": faka,
        "trust_claims": "|".join(claims),
        "telegram": ", ".join(tg),
        "qq": ", ".join(qq),
        "discord": ", ".join(dc),
        "email": ", ".join(mails),
    }


def main():
    platforms = load_platforms()
    print(f"平台数: {len(platforms)}")
    records = load_existing()
    print(f"已有记录: {len(records)}(将跳过已探测过的)")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = len(platforms)

    for i, domain in enumerate(platforms, 1):
        if domain in records and records[domain].get("checked_pages"):
            continue
        print(f"[{i}/{total}] {domain}", end=" … ", flush=True)
        html, ok = fetch_pages(domain)
        rec = {f: "" for f in FIELDS}
        rec["domain"] = domain
        rec["checked_pages"] = str(ok)
        rec["last_checked"] = ts
        if html:
            rec.update(analyze(html))
            hit = [rec["payment_methods"] and "pay", rec["has_faka"] and "faka",
                   rec["trust_claims"] and "claims", rec["telegram"] and "tg"]
            print(", ".join(x for x in hit if x) or "无信号")
        else:
            print("无法访问")
        records[domain] = rec
        if i % 20 == 0:
            save(records)
        time.sleep(random.uniform(1.0, 2.0))

    save(records)
    pay = sum(1 for r in records.values() if r.get("payment_methods"))
    faka = sum(1 for r in records.values() if r.get("has_faka") == "Y")
    claims = sum(1 for r in records.values() if r.get("trust_claims"))
    tg = sum(1 for r in records.values() if r.get("telegram"))
    print(f"\n✅ 完成 · 支付信号 {pay} · 发卡 {faka} · 话术 {claims} · Telegram {tg}")
    print(f"   已保存: {OUT_CSV}")


if __name__ == "__main__":
    main()
