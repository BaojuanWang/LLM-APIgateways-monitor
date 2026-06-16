"""
站点截图脚本
运行位置: scripts/screenshot.py
- 读取 monitor_results.csv 最新一轮的在线站点
- 新站点或 html_hash 变化才截图
- 截图保存到 data/screenshots/
- 失败记录到 data/screenshot_failures.csv
"""

import csv
import time
import random
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR       = Path(__file__).parent.parent
DATA_DIR       = BASE_DIR / "data"
RESULTS_DIR    = BASE_DIR / "results"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
RESULTS_CSV    = RESULTS_DIR / "monitor_results.csv"
FAILURES_CSV   = DATA_DIR / "screenshot_failures.csv"

SKIP_STATUSES = {"DNS_FAIL", "TIMEOUT", "HTTP_ERROR", "PARKED_OR_FOR_SALE"}

FAILURE_FIELDS = [
    "checked_at", "domain", "platform_name", "final_url", "error"
]


def load_latest_round(results_csv):
    """
    读取 monitor_results.csv，取最新一轮（timestamp 最大的那批）的在线站点。
    返回 {domain: {"hash": ..., "final_url": ..., "platform_name": ..., "status": ...}}
    """
    if not results_csv.exists():
        return {}, ""

    # 先找最新 timestamp
    latest_ts = ""
    with open(results_csv, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ts = row.get("timestamp", "")
            if ts > latest_ts:
                latest_ts = ts

    if not latest_ts:
        return {}, ""

    # 读取最新一轮数据（同一轮的 timestamp 精确到秒可能有细微差异，取最近1分钟内的）
    from datetime import datetime
    latest_dt = datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))

    sites = {}
    with open(results_csv, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ts = row.get("timestamp", "")
            if not ts:
                continue
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            # 同一轮：在最新 timestamp 的 5 分钟窗口内
            if abs((latest_dt - dt).total_seconds()) <= 300:
                domain = row.get("domain", "").strip()
                status = row.get("online_status", "")
                if domain and status not in SKIP_STATUSES:
                    sites[domain] = {
                        "hash":          row.get("html_hash", ""),
                        "final_url":     row.get("final_url", ""),
                        "platform_name": row.get("platform_name", ""),
                        "status":        status,
                    }

    return sites, latest_ts


def load_last_hashes():
    """读取每个域名上一次成功截图时的 hash（从截图文件名推断不了，改从CSV记录）。"""
    hash_file = DATA_DIR / "screenshot_hashes.csv"
    if not hash_file.exists():
        return {}
    with open(hash_file, encoding="utf-8-sig") as f:
        return {row["domain"]: row["html_hash"] for row in csv.DictReader(f) if row.get("domain")}


def save_hashes(hashes):
    hash_file = DATA_DIR / "screenshot_hashes.csv"
    with open(hash_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["domain", "html_hash"])
        writer.writeheader()
        for domain, h in hashes.items():
            writer.writerow({"domain": domain, "html_hash": h})


def has_any_screenshot(domain):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    safe = domain.replace(".", "_").replace("/", "_")
    return any(SCREENSHOT_DIR.glob(f"{safe}_*.png"))


def close_popups(page):
    """尝试关闭弹窗：ESC + 常见关闭按钮。"""
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception:
        pass

    for selector in [
        "button[class*='close']", "button[class*='Close']",
        "[aria-label='close']", "[aria-label='Close']",
        "button:has-text('关闭')", "button:has-text('Close')",
        "button:has-text('Close Today')", "button:has-text('Close Notice')",
        "button:has-text('×')", "button:has-text('✕')",
        ".modal-close", ".popup-close", ".dialog-close",
    ]:
        try:
            el = page.query_selector(selector)
            if el and el.is_visible():
                el.click()
                time.sleep(0.5)
                break
        except Exception:
            continue


def take_screenshot(page, domain, final_url, date_str):
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
        page.goto(url, timeout=25000, wait_until="domcontentloaded")
        # 等待动态内容
        time.sleep(2)
        # 滚动到底触发懒加载
        page.evaluate("""
            () => new Promise(resolve => {
                let total = document.body.scrollHeight;
                let step = Math.ceil(total / 8);
                let current = 0;
                let timer = setInterval(() => {
                    current += step;
                    window.scrollTo(0, current);
                    if (current >= total) {
                        clearInterval(timer);
                        resolve();
                    }
                }, 150);
            })
        """)
        time.sleep(1)
        # 回顶
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.5)
        # 关弹窗
        close_popups(page)
        time.sleep(0.3)
        # 截全页
        page.screenshot(path=str(path), full_page=True)
        return str(path), None
    except Exception as e:
        return None, str(e)


def append_failure(domain, platform_name, final_url, error, ts):
    file_exists = FAILURES_CSV.exists()
    with open(FAILURES_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FAILURE_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            "checked_at":    ts,
            "domain":        domain,
            "platform_name": platform_name,
            "final_url":     final_url,
            "error":         error[:300],
        })


def main():
    from playwright.sync_api import sync_playwright

    print(f"\n{'='*50}")
    print(f"开始截图  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    sites, latest_ts = load_latest_round(RESULTS_CSV)
    if not sites:
        print("⚠️  没有找到在线站点，退出")
        return

    print(f"最新一轮: {latest_ts}")
    print(f"在线站点: {len(sites)} 个\n")

    last_hashes = load_last_hashes()
    date_str    = datetime.now().strftime("%Y-%m-%d")
    ts_now      = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 筛选需要截图的站点
    to_screenshot = []
    for domain, info in sites.items():
        is_new    = not has_any_screenshot(domain)
        new_hash  = info["hash"]
        old_hash  = last_hashes.get(domain, "")
        changed   = (old_hash != "" and new_hash != "" and old_hash != new_hash)

        if is_new or changed:
            reason = "新站点" if is_new else "内容变化"
            to_screenshot.append((domain, info, reason))

    print(f"需要截图: {len(to_screenshot)} 个\n")

    if not to_screenshot:
        print("✅ 本轮无需截图")
        return

    success_count = 0
    fail_count    = 0
    new_hashes    = dict(last_hashes)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--lang=zh-CN"]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0.0.0 Safari/537.36",
            locale="zh-CN",
        )
        page = context.new_page()

        for idx, (domain, info, reason) in enumerate(to_screenshot, 1):
            print(f"  [{idx:3d}/{len(to_screenshot)}] {domain} ({reason})")
            path, error = take_screenshot(page, domain, info["final_url"], date_str)

            if path:
                print(f"    ✅ {Path(path).name}")
                new_hashes[domain] = info["hash"]
                success_count += 1
            else:
                print(f"    ⚠️  失败: {error[:80]}")
                append_failure(domain, info["platform_name"], info["final_url"], error, ts_now)
                fail_count += 1

            time.sleep(random.uniform(0.5, 1.5))

        browser.close()

    save_hashes(new_hashes)

    print(f"\n── 截图完成 ──")
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")
    if fail_count:
        print(f"  失败记录: {FAILURES_CSV}")
    print(f"  截图目录: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()
