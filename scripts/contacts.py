"""
联系方式与推广体系检测脚本
运行位置: scripts/contacts.py
- 读取 hvoy_latest.csv + manual_sites.csv
- 抓取每个域名的联系方式（Telegram/QQ/微信/Discord）
- 检测是否有推广/代理页面
- 结果写入 data/contacts.csv
"""

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

BASE_DIR     = Path(__file__).parent.parent
DATA_DIR     = BASE_DIR / "data"
HVOY_CSV     = DATA_DIR / "hvoy_latest.csv"
MANUAL_CSV   = DATA_DIR / "manual_sites.csv"
MASTER_CSV   = DATA_DIR / "master_sites.csv"   # discovery layer (GitHub + FOFA)
CONTACTS_CSV = DATA_DIR / "contacts.csv"

TIMEOUT = 8
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

AFFILIATE_PATHS = [
    "/invite", "/affiliate", "/agent", "/代理", "/推广",
    "/partner", "/referral", "/aff", "/reseller",
]
AFFILIATE_KEYWORDS = [
    "邀请", "推广", "代理", "佣金", "commission",
    "referral", "affiliate", "invite", "partner",
]

FIELDS = [
    "domain", "telegram", "qq_group", "wechat", "discord",
    "has_affiliate", "affiliate_url", "last_checked",
]

PATTERNS = {
    "telegram": re.compile(r't\.me/([a-zA-Z0-9_+]+)|telegram\.me/([a-zA-Z0-9_+]+)', re.IGNORECASE),
    "qq_group": re.compile(r'[Qq]{2}[\s群号:：]*(\d{5,12})|群号[\s:：]*(\d{5,12})|加群[\s:：]*(\d{5,12})|群[:：](\d{5,12})'),
    "wechat":   re.compile(r'微信[\s:：号]*([a-zA-Z0-9_\-]{4,20})|wechat[\s:：]*([a-zA-Z0-9_\-]{4,20})', re.IGNORECASE),
    "discord":  re.compile(r'discord\.gg/([a-zA-Z0-9]+)|discord\.com/invite/([a-zA-Z0-9]+)', re.IGNORECASE),
}


def extract_domain(url):
    if not url: return None
    url = re.sub(r'^https?://', '', str(url).strip())
    return url.split('/')[0].split('?')[0].lower() or None


def load_platforms():
    # include the full discovery list so affiliate/contact crawling reaches the
    # FOFA + GitHub sites, not just the hand-curated seed.
    domains = {}
    for csv_path in [HVOY_CSV, MANUAL_CSV, MASTER_CSV]:
        if not csv_path.exists(): continue
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                d = extract_domain(row.get("domain", ""))
                if d: domains.setdefault(d, row.get("platform_name", "") or row.get("verified_site_name", ""))
    return domains


def load_existing():
    if not CONTACTS_CSV.exists(): return {}
    with open(CONTACTS_CSV, encoding="utf-8-sig") as f:
        return {row["domain"]: row for row in csv.DictReader(f)}


def save_all(records):
    with open(CONTACTS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records.values())


def fetch_html(domain):
    for scheme in ["https", "http"]:
        try:
            resp = requests.get(f"{scheme}://{domain}", headers=HEADERS,
                                timeout=TIMEOUT, verify=False, allow_redirects=True)
            if resp.status_code == 200 and resp.text:
                return resp.text
        except Exception:
            continue
    return ""


def check_affiliate(domain):
    for path in AFFILIATE_PATHS:
        try:
            url = f"https://{domain}{path}"
            resp = requests.get(url, headers=HEADERS, timeout=5,
                                verify=False, allow_redirects=True)
            if resp.status_code == 200 and len(resp.text) > 300:
                if any(k in resp.text.lower() for k in AFFILIATE_KEYWORDS):
                    return url
        except Exception:
            continue
    return ""


def extract_contacts(html):
    # Telegram
    tg = list({f"t.me/{m[0] or m[1]}" for m in PATTERNS["telegram"].findall(html) if m[0] or m[1]})

    # QQ群
    qq = list({m[0] or m[1] or m[2] or m[3] for m in PATTERNS["qq_group"].findall(html) if any(m)})

    # 微信
    wc = PATTERNS["wechat"].search(html)
    wechat = (wc.group(1) or wc.group(2)) if wc else ""

    # Discord
    dc = list({f"discord.gg/{m[0] or m[1]}" for m in PATTERNS["discord"].findall(html) if m[0] or m[1]})

    return {
        "telegram":  ", ".join(tg[:3]),
        "qq_group":  ", ".join(qq[:3]),
        "wechat":    wechat,
        "discord":   ", ".join(dc[:2]),
    }


def main():
    print("读取平台列表...")
    platforms = load_platforms()
    print(f"共 {len(platforms)} 个域名")

    existing = load_existing()
    records  = {}

    # 保留已有记录
    for domain in platforms:
        if domain in existing:
            records[domain] = {f: existing[domain].get(f, "") for f in FIELDS}
        else:
            records[domain] = {f: "" for f in FIELDS}
        records[domain]["domain"] = domain

    ts    = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = len(platforms)

    for idx, domain in enumerate(platforms, 1):
        print(f"[{idx}/{total}] {domain}", end=" ... ", flush=True)

        html = fetch_html(domain)
        if not html:
            records[domain]["last_checked"] = ts
            print("无法访问")
            time.sleep(random.uniform(0.5, 1.0))
            continue

        contacts = extract_contacts(html)
        affiliate_url = check_affiliate(domain)

        records[domain].update(contacts)
        records[domain]["has_affiliate"] = "有" if affiliate_url else "无"
        records[domain]["affiliate_url"] = affiliate_url
        records[domain]["last_checked"]  = ts

        found = [f"{k}:{v}" for k, v in contacts.items() if v]
        if affiliate_url:
            found.append(f"推广:{affiliate_url}")
        print(", ".join(found) if found else "无")

        if idx % 20 == 0:
            save_all(records)

        time.sleep(random.uniform(1.0, 2.0))

    save_all(records)
    has_tg  = sum(1 for r in records.values() if r.get("telegram"))
    has_qq  = sum(1 for r in records.values() if r.get("qq_group"))
    has_aff = sum(1 for r in records.values() if r.get("has_affiliate") == "有")
    print(f"\n✅ 完成")
    print(f"   有Telegram: {has_tg}")
    print(f"   有QQ群:     {has_qq}")
    print(f"   有推广页:   {has_aff}")
    print(f"   已保存: {CONTACTS_CSV}")


if __name__ == "__main__":
    main()
