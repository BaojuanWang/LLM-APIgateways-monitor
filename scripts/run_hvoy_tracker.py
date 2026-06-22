"""Run hvoy tracking without blocking the monitor when hvoy rejects Actions."""

import csv
import json
import time
from datetime import datetime, timezone

import hvoy_tracker as tracker


FETCH_STATUS_JSON = tracker.DATA_DIR / "hvoy_fetch_status.json"
DEFAULT_MANUAL_FIELDS = [
    "source", "platform_name", "domain", "tech_stack", "favicon_group",
    "icp_filing", "has_privacy_policy", "contact_telegram", "contact_qq", "notes",
]


def save_fetch_status(status, item_count=0, error="", used_cache=False):
    payload = {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "item_count": item_count,
        "used_cache": used_cache,
        "error": str(error)[:500],
    }
    FETCH_STATUS_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_with_retry():
    last_error = None
    for attempt in range(1, 4):
        try:
            return tracker.fetch_payload()
        except tracker.requests.HTTPError as exc:
            last_error = exc
            if exc.response is not None and exc.response.status_code == 403:
                break
        except tracker.requests.RequestException as exc:
            last_error = exc

        if attempt < 3:
            delay = attempt * 5
            print(f"请求失败，{delay} 秒后重试（{attempt}/3）: {last_error}")
            time.sleep(delay)
    raise last_error


def save_removed_to_manual(removed):
    if not removed:
        return

    fieldnames = DEFAULT_MANUAL_FIELDS
    existing_domains = set()
    manual_exists = tracker.MANUAL_CSV.exists()
    if manual_exists:
        with open(tracker.MANUAL_CSV, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or DEFAULT_MANUAL_FIELDS
            existing_domains = {
                row.get("domain", "").strip().lower() for row in reader
            }

    to_add = [
        item for item in removed
        if item.get("siteDomain", "").strip().lower() not in existing_domains
    ]
    if not to_add:
        print("  (已在 manual_sites.csv 中，无需重复写入)")
        return

    with open(tracker.MANUAL_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not manual_exists or tracker.MANUAL_CSV.stat().st_size == 0:
            writer.writeheader()
        for item in to_add:
            row = {field: "" for field in fieldnames}
            row.update({
                "source": "hvoy_removed",
                "platform_name": item.get("siteName", ""),
                "domain": item.get("siteDomain", ""),
            })
            writer.writerow(row)
    print(f"  已将 {len(to_add)} 个消失平台写入 manual_sites.csv")


def main():
    tracker.HVOY_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    latest_json = tracker.DATA_DIR / "hvoy_latest.json"
    latest_csv = tracker.DATA_DIR / "hvoy_latest.csv"
    old_data = tracker.load_last(latest_json)

    try:
        items, updated_at = fetch_with_retry()
        save_fetch_status("SUCCESS", item_count=len(items))
    except Exception as exc:
        if not old_data or not latest_csv.exists():
            save_fetch_status("FAILED_NO_CACHE", error=exc)
            raise
        save_fetch_status(
            "FALLBACK_TO_CACHE", len(old_data), error=exc, used_cache=True
        )
        print(
            f"::warning::hvoy 抓取失败，继续使用最近缓存"
            f"（{len(old_data)}个平台）: {exc}"
        )
        print(f"缓存文件: {latest_csv}")
        return

    added, removed = tracker.compare(old_data, items)
    tracker.print_diff(added, removed)
    if removed:
        print("\n将消失平台写入 manual_sites.csv ...")
        save_removed_to_manual(removed)

    today_json = tracker.make_path(tracker.HVOY_DIR, f"hvoy_{date_str}", "json")
    today_xlsx = tracker.make_path(tracker.HVOY_DIR, f"hvoy_{date_str}", "xlsx")
    tracker.save_json(items, today_json)
    tracker.save_json(items, latest_json)
    tracker.save_csv(items, latest_csv)
    tracker.save_excel(items, added, removed, today_xlsx, updated_at, date_str)

    if added or removed:
        diff_file = tracker.make_path(tracker.HVOY_DIR, f"diff_{date_str}", "json")
        tracker.save_json(
            {"date": date_str, "added": added, "removed": removed}, diff_file
        )

    print(
        f"\n总平台数: {len(items)} | 新增: {len(added)} | 消失: {len(removed)}"
    )


if __name__ == "__main__":
    main()
