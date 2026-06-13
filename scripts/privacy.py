"""
隐私政策抓取与分析脚本
运行位置: scripts/privacy.py
- 读取 hvoy_latest.csv + manual_sites.csv
- 尝试抓取每个域名的隐私政策页面
- 保存原始文本快照到 data/privacy_snapshots/
- 对比上次内容，记录变化
- 分析结果写入 data/privacy.csv
"""

import csv
import hashlib
import re
import time
import random
import warnings
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)

BASE_DIR      = Path(__file__).parent.parent
DATA_DIR      = BASE_DIR / "data"
SNAPSHOT_DIR  = DATA_DIR / "privacy_snapshots"
HVOY_CSV      = DATA_DIR / "hvoy_latest.csv"
MANUAL_CSV    = DATA_DIR / "manual_sites.csv"
PRIVACY_CSV   = DATA_DIR / "privacy.csv"

TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

PRIVACY_PATHS = [
    "/privacy", "/privacy-policy", "/privacy_policy",
    "/legal/privacy", "/terms/privacy",
    "/隐私", "/隐私政策", "/隐私协议",
]

FIELDS = [
    "domain", "has_privacy", "privacy_url",
    "collect_data", "applicable_law", "third_party_sharing", "has_contact",
    "content_hash", "content_changed", "last_checked", "last_changed",
]

# ── 关键词模式 ─────────────────────────────────────────────────
DATA_COLLECT_PATTERNS = [
    (re.compile(r'不收集|不存储|不记录|no.?log|not.?collect|zero.?log', re.IGNORECASE), "声称不收集"),
    (re.compile(r'收集.*?(个人|用户|数据|信息)|collect.*?(personal|user|data)', re.IGNORECASE), "会收集数据"),
]
LAW_PATTERNS = [
    (re.compile(r'中华人民共和国|中国法律|Chinese.?law', re.IGNORECASE), "中国法律"),
    (re.compile(r'香港法律|Hong.?Kong.?law', re.IGNORECASE), "香港法律"),
    (re.compile(r'新加坡|Singapore', re.IGNORECASE), "新加坡法律"),
    (re.compile(r'美国法律|US.?law|American.?law', re.IGNORECASE), "美国法律"),
    (re.compile(r'GDPR|欧盟', re.IGNORECASE), "欧盟/GDPR"),
]
THIRD_PARTY_RE = re.compile(r'第三方|third.?party|共享.*?数据|share.*?data|披露|disclose', re.IGNORECASE)
CONTACT_RE     = re.compile(r'contact|联系|邮箱|email|[@＠][a-zA-Z0-9._-]+\.[a-zA-Z]{2,}', re.IGNORECASE)


def extract_domain(url):
    if not url: return None
    url = re.sub(r'^https?://', '', str(url).strip())
    return url.split('/')[0].split('?')[0].lower() or None


def load_platforms():
    domains = {}
    for csv_path in [HVOY_CSV, MANUAL_CSV]:
        if not csv_path.exists(): continue
        with open(csv_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                d = extract_domain(row.get("domain", ""))
                if d: domains[d] = row.get("platform_name", "")
    return domains


def load_existing():
    if not PRIVACY_CSV.exists(): return {}
    with open(PRIVACY_CSV, encoding="utf-8-sig") as f:
        return {row["domain"]: row for row in csv.DictReader(f)}


def save_all(records):
    with open(PRIVACY_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records.values())


def text_hash(text):
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def clean_html(html):
    text = re.sub(r'<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', text).strip()


def fetch_privacy(domain):
    for path in PRIVACY_PATHS:
        for scheme in ["https", "http"]:
            try:
                url = f"{scheme}://{domain}{path}"
                resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                                    verify=False, allow_redirects=True)
                if resp.status_code == 200 and len(resp.text) > 300:
                    text = clean_html(resp.text)
                    if len(text) > 200:
                        return text[:8000], str(resp.url)
            except Exception:
                continue
    return "", ""


def analyze(text):
    collect = "未明确说明"
    for pattern, label in DATA_COLLECT_PATTERNS:
        if pattern.search(text):
            collect = label
            break

    law = "未明确说明"
    for pattern, label in LAW_PATTERNS:
        if pattern.search(text):
            law = label
            break

    return {
        "collect_data":          collect,
        "applicable_law":        law,
        "third_party_sharing":   "提及" if THIRD_PARTY_RE.search(text) else "未提及",
        "has_contact":           "有" if CONTACT_RE.search(text) else "无",
    }


def save_snapshot(domain, text, date_str):
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{domain}_{date_str}.txt"
    # 同一天多次运行加后缀
    if path.exists():
        n = 2
        while (SNAPSHOT_DIR / f"{domain}_{date_str}_{n}.txt").exists():
            n += 1
        path = SNAPSHOT_DIR / f"{domain}_{date_str}_{n}.txt"
    path.write_text(text, encoding="utf-8")


def main():
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    print("读取平台列表...")
    platforms = load_platforms()
    print(f"共 {len(platforms)} 个域名")

    existing = load_existing()
    records  = {d: {f: "" for f in FIELDS} for d in platforms}

    # 保留已有记录
    for domain, row in existing.items():
        if domain in records:
            records[domain] = {f: row.get(f, "") for f in FIELDS}
            records[domain]["domain"] = domain

    date_str = datetime.now().strftime("%Y-%m-%d")
    ts       = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total    = len(platforms)

    for idx, domain in enumerate(platforms, 1):
        print(f"[{idx}/{total}] {domain}", end=" ... ", flush=True)

        text, url = fetch_privacy(domain)

        rec = records[domain]
        rec["domain"] = domain

        if not text:
            rec["has_privacy"]  = "无"
            rec["privacy_url"]  = ""
            rec["last_checked"] = ts
            print("无隐私政策")
            time.sleep(random.uniform(0.5, 1.0))
            continue

        # 对比hash
        new_hash  = text_hash(text)
        old_hash  = rec.get("content_hash", "")
        changed   = (old_hash != "" and old_hash != new_hash)

        rec["has_privacy"]       = "有"
        rec["privacy_url"]       = url
        rec["content_hash"]      = new_hash
        rec["content_changed"]   = "是" if changed else "否"
        rec["last_checked"]      = ts
        if changed:
            rec["last_changed"]  = ts

        rec.update(analyze(text))
        save_snapshot(domain, text, date_str)

        status = f"✓ {rec['collect_data']} | {rec['applicable_law']}"
        if changed:
            status += " | ⚠️内容变化"
        print(status)

        # 每20个保存一次
        if idx % 20 == 0:
            save_all(records)

        time.sleep(random.uniform(1.0, 2.0))

    save_all(records)
    has_count     = sum(1 for r in records.values() if r.get("has_privacy") == "有")
    changed_count = sum(1 for r in records.values() if r.get("content_changed") == "是")
    print(f"\n✅ 完成")
    print(f"   有隐私政策: {has_count}/{total}")
    print(f"   内容有变化: {changed_count}")
    print(f"   已保存: {PRIVACY_CSV}")


if __name__ == "__main__":
    main()
