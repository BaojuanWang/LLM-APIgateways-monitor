"""
LLM中转站监测流水线
运行位置: scripts/pipeline.py
"""

import csv
import hashlib
import re
import time
import random
import warnings
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
warnings.filterwarnings("ignore", category=InsecureRequestWarning)

BASE_DIR       = Path(__file__).parent.parent
DATA_DIR       = BASE_DIR / "data"
RESULTS_DIR    = BASE_DIR / "results"
SCREENSHOT_DIR = DATA_DIR / "screenshots"

HVOY_CSV       = DATA_DIR / "hvoy_latest.csv"
MANUAL_CSV     = DATA_DIR / "manual_sites.csv"
RESULTS_CSV    = RESULTS_DIR / "monitor_results.csv"
REVIEW_CSV     = RESULTS_DIR / "needs_review.csv"

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

REVIEW_FIELDS = [
    "checked_at", "domain", "platform_name", "source",
    "online_status", "final_url", "error", "note"
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


def load_last_hashes():
    """读取每个域名上一轮的 html_hash，用于判断内容是否变化。"""
    if not RESULTS_CSV.exists():
        return {}
    last = {}
    with open(RESULTS_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            domain = row.get("domain", "").strip()
            ts     = row.get("timestamp", "")
            h      = row.get("html_hash", "")
            if domain and h:
                if domain not in last or ts > last[domain]["ts"]:
                    last[domain] = {"ts": ts, "hash": h}
    return {d: v["hash"] for d, v in last.items()}


def has_any_screenshot(domain):
    """判断这个域名是否已有任何历史截图。"""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    safe = domain.replace(".", "_").replace("/", "_")
    return any(SCREENSHOT_DIR.glob(f"{safe}_*.png"))


def take_screenshot(domain, final_url, date_str):
    """用 playwright 截图，保存到 data/screenshots/域名_日期.png。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"    ⚠️  playwright 未安装，跳过截图")
        return

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    safe = domain.replace(".", "_").replace("/", "_")

    path = SCREENSHOT_DIR / f"{safe}_{date_str}.png"
    if path.exists():
        n = 2
        while (SCREENSHOT_DIR / f"{safe}_{date_str}_{n}.png").exists():
            n += 1
        path = SCREENSHOT_DIR / f"{safe}_{date_str}_{n}.png"

    url = final_url or f"https://{domain}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(path), full_page=False)
            browser.close()
        print(f"    📸 截图已保存: {path.name}")
    except Exception as e:
        print(f"    ⚠️  截图失败 {domain}: {e}")


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

    if domain.startswith("www."):
        urls_to_try = [f"https://{domain}", f"http://{domain}"]
    else:
        urls_to_try = [f"https://{domain}", f"https://www.{domain}", f"http://{domain}"]

    time.sleep(random.uniform(0.3, 1.0))
    last_error = None

    for url in urls_to_try:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                                allow_redirects=True, verify=False)
            result["http_status"]    = resp.status_code
            result["final_url"]      = str(resp.url)
            result["redirect_chain"] = " -> ".join(
                [str(r.url) for r in resp.history] + [str(resp.url)]
            ) if resp.history else str(resp.url)
            result["online_status"]  = classify_status(resp=resp)
            result["page_title"]     = extract_title(resp.text)
            result["html_hash"]      = html_hash(resp.text)
            if result["online_status"] != "HTTP_ERROR":
                return result
        except Exception as e:
            last_error = e
            continue

    if last_error:
        result["online_status"] = classify_status(error=last_error)
        result["error"]         = str(last_error)[:200]
    return result


def append_results(results):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = RESULTS_CSV.exists()
    with open(RESULTS_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(results)


def append_needs_review(results):
    """把本轮 TIMEOUT 的站点追加到 needs_review.csv，供人工用国内网络确认。"""
    timeout_results = [r for r in results if r.get("online_status") == "TIMEOUT"]
    if not timeout_results:
        return 0

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = REVIEW_CSV.exists()

    with open(REVIEW_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        if not file_exists:
            writer.writeheader()
        for r in timeout_results:
            writer.writerow({
                "checked_at":    r["timestamp"],
                "domain":        r["domain"],
                "platform_name": r["platform_name"],
                "source":        r["source"],
                "online_status": r["online_status"],
                "final_url":     r["final_url"],
                "error":         r["error"],
                "note":          "需要手动确认：本轮检测超时，可能是网络/IP/站点不稳定",
            })

    return len(timeout_results)


def process_screenshots(results, last_hashes, date_str):
    """
    截图触发条件：
    - 新站点（screenshots/ 里没有任何历史截图）→ 截
    - html_hash 和上一轮不同 → 截
    - DNS_FAIL / TIMEOUT / HTTP_ERROR 的站跳过（没有可截的页面）
    """
    skip_statuses = {"DNS_FAIL", "TIMEOUT", "HTTP_ERROR", "PARKED_OR_FOR_SALE"}
    screenshot_count = 0

    for r in results:
        domain = r["domain"]
        status = r.get("online_status", "")

        if status in skip_statuses:
            continue

        new_hash = r.get("html_hash", "")
        old_hash = last_hashes.get(domain, "")
        is_new   = not has_any_screenshot(domain)
        changed  = (old_hash != "" and new_hash != "" and old_hash != new_hash)

        if is_new or changed:
            reason = "新站点" if is_new else "内容变化"
            print(f"  📸 {domain} ({reason})")
            take_screenshot(domain, r.get("final_url", ""), date_str)
            screenshot_count += 1

    return screenshot_count


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

    last_hashes = load_last_hashes()
    date_str    = datetime.now().strftime("%Y-%m-%d")

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
    review_count     = append_needs_review(results)
    print_summary(results)

    print(f"\n── 截图处理 ──")
    screenshot_count = process_screenshots(results, last_hashes, date_str)

    print(f"\n✅ 结果已追加到 {RESULTS_CSV}")
    if review_count:
        print(f"⚠️  {review_count} 个超时站点已追加到 {REVIEW_CSV}，请手动确认")
    else:
        print(f"✅ 本轮无超时站点")
    print(f"📸 本轮截图: {screenshot_count} 张")


if __name__ == "__main__":
    main()
