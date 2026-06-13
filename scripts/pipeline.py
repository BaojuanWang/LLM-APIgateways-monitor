"""
LLM中转站监测流水线
运行位置: scripts/pipeline.py
"""

import csv
import hashlib
import re
import time
import random
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE_DIR    = Path(__file__).parent.parent
DATA_DIR    = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"

HVOY_CSV    = DATA_DIR / "hvoy_latest.csv"
MANUAL_CSV  = DATA_DIR / "manual_sites.csv"
RESULTS_CSV = RESULTS_DIR / "monitor_results.csv"

TIMEOUT     = 15
MAX_WORKERS = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

RESULT_FIELDS = [
    "timestamp", "domain", "platform_name", "source",
    "online_status", "http_status", "final_url",
    "page_title", "html_hash", "redirect_chain", "error"
]


def extract_domain(url):
    if not url:
        return None
    url = str(url).strip()
    url = re.sub(r'^https?://', '', url)
    return url.split('/')[0].split('?')[0].lower() or None


def html_hash(text):
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:12] if text else ""


def classify_status(resp=None, error=None):
    if error:
        err = str(error).lower()
        if "timeout" in err: return "TIMEOUT"
        if any(x in err for x in ["dns", "name", "resolve", "nodename"]): return "DNS_FAIL"
        return "HTTP_ERROR"
    code  = resp.status_code
    lower = (resp.text[:3000] if resp.text else "").lower()
    if "cloudflare" in lower and ("challenge" in lower or "checking your browser" in lower):
        return "CLOUDFLARE_OR_BLOCKED"
    if any(x in lower for x in ["domain for sale", "buy this domain", "域名出售"]):
        return "PARKED_OR_FOR_SALE"
    if code == 200:  return "ONLINE"
    if code in (301, 302, 303, 307, 308): return "REDIRECTED"
    if code in (401, 403): return "ONLINE_LOGIN_REQUIRED"
    if code == 429:  return "ONLINE"
    if code in (521, 522): return "CLOUDFLARE_OR_BLOCKED"
    if code >= 500:  return "HTTP_ERROR"
    return f"HTTP_{code}"


def extract_title(text):
    if not text: return ""
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip()[:120] if m else ""


def load_platforms():
    platforms = {}

    if HVOY_CSV.exists():
        with open(HVOY_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                domain = extract_domain(row.get("domain", ""))
                if domain:
                    platforms[domain] = {
                        "domain":        domain,
                        "platform_name": row.get("platform_name", ""),
                        "source":        "hvoy",
                    }
        print(f"hvoy来源: {len(platforms)} 个")
    else:
        print(f"⚠️  找不到 {HVOY_CSV}")

    manual_count = 0
    if MANUAL_CSV.exists():
        with open(MANUAL_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                domain = extract_domain(row.get("domain", ""))
                if domain and domain not in platforms:
                    platforms[domain] = {
                        "domain":        domain,
                        "platform_name": row.get("platform_name", ""),
                        "source":        row.get("source", "manual"),
                    }
                    manual_count += 1
    else:
        print(f"⚠️  找不到 {MANUAL_CSV}")

    print(f"manual来源新增: {manual_count} 个")
    print(f"合并去重后共: {len(platforms)} 个平台")
    return list(platforms.values())


def check_one(p):
    domain = p["domain"]
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = {f: "" for f in RESULT_FIELDS}
    result.update({
        "timestamp":     ts,
        "domain":        domain,
        "platform_name": p.get("platform_name", ""),
        "source":        p.get("source", ""),
    })
    try:
        time.sleep(random.uniform(0.3, 1.0))
        resp = requests.get(f"https://{domain}", headers=HEADERS,
                            timeout=TIMEOUT, allow_redirects=True)
        result["http_status"]    = resp.status_code
        result["final_url"]      = str(resp.url)
        result["redirect_chain"] = " -> ".join(
            [str(r.url) for r in resp.history] + [str(resp.url)]
        ) if resp.history else str(resp.url)
        result["online_status"]  = classify_status(resp=resp)
        result["page_title"]     = extract_title(resp.text)
        result["html_hash"]      = html_hash(resp.text)
    except Exception as e:
        result["online_status"]  = classify_status(error=e)
        result["error"]          = str(e)[:200]
    return result


def append_results(results):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = RESULTS_CSV.exists()
    with open(RESULTS_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(results)


def print_summary(results):
    from collections import Counter
    counts = Counter(r["online_status"] for r in results)
    print("\n── 检测结果小结 ──")
    for status, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {status:<30} {n}")


def main():
    print(f"\n{'='*50}")
    print(f"开始检测  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    platforms = load_platforms()
    if not platforms:
        print("没有平台可检测，退出")
        return

    print(f"\n正在检测 {len(platforms)} 个平台...\n")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(check_one, p): p for p in platforms}
        done = 0
        for future in as_completed(futures):
            done += 1
            r = future.result()
            results.append(r)
            print(f"  [{done:3d}/{len(platforms)}] {r['domain']:<35} {r['online_status']}")

    append_results(results)
    print_summary(results)
    print(f"\n✅ 结果已追加到 {RESULTS_CSV}")


if __name__ == "__main__":
    main()
