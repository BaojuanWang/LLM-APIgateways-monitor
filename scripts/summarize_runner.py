"""Generate historical summaries plus a separate current-state view.

The legacy summary intentionally answers whether a site has ever been observed
reachable. This wrapper preserves that longitudinal metric while also writing a
current-state CSV based on the latest observations, filtering malformed domain
values, and limiting XLSX growth to one summary file per day.
"""

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

import summarize
from domain_utils import is_valid_host

BASE_DIR = Path(__file__).parent.parent
RESULTS_DIR = BASE_DIR / "results"
RECHECK_CSV = RESULTS_DIR / "stopped_service_rechecks.csv"
CURRENT_STATUS_CSV = RESULTS_DIR / "current_status.csv"
CURRENT_REVIEW_CSV = RESULTS_DIR / "current_needs_review.csv"

REACHABLE_STATUSES = {
    "ONLINE",
    "ONLINE_LOGIN_REQUIRED",
    "CLOUDFLARE_OR_BLOCKED",
    "REDIRECTED",
    "HTTP_444",
    "ALIVE_BLOCKED",
}
HARD_DEAD_STATUSES = {"DNS_FAIL", "PARKED_OR_FOR_SALE"}


def latest_rechecks():
    latest = {}
    if not RECHECK_CSV.exists():
        return latest

    with open(RECHECK_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            domain = row.get("domain", "").strip().lower()
            timestamp = row.get("timestamp", "")
            if not domain:
                continue
            if domain not in latest or timestamp > latest[domain].get("timestamp", ""):
                latest[domain] = row
    return latest


def clear_obsolete_stopped_markers(platforms):
    resumed = []
    for domain, row in latest_rechecks().items():
        if row.get("online_status") not in REACHABLE_STATUSES:
            continue
        platform = platforms.get(domain)
        if not platform:
            continue
        if platform["status_counts"].pop("SERVICE_STOPPED", None) is not None:
            resumed.append(domain)
    return resumed


def remove_invalid_domains(platforms):
    rejected = []
    for domain in list(platforms):
        if not is_valid_host(domain):
            rejected.append(domain or "<empty>")
            platforms.pop(domain, None)
    return rejected


def ordered_checks(platform):
    return sorted(
        [c for c in platform.get("checks", []) if c.get("timestamp")],
        key=lambda c: c["timestamp"],
    )


def classify_current(checks):
    """Classify current state without declaring a site dead after one failure."""
    if not checks:
        return "UNCERTAIN"

    latest = checks[-1].get("status", "")
    if latest in REACHABLE_STATUSES:
        return "ALIVE"
    if latest == "SERVICE_STOPPED":
        return "DEAD"

    recent = [c.get("status", "") for c in checks[-3:]]
    if len(recent) >= 3 and all(status in HARD_DEAD_STATUSES for status in recent):
        return "DEAD"
    return "UNCERTAIN"


def consecutive_non_alive(checks):
    count = 0
    for check in reversed(checks):
        if check.get("status", "") in REACHABLE_STATUSES:
            break
        count += 1
    return count


def current_rows(platforms):
    rows = []
    for domain, platform in platforms.items():
        checks = ordered_checks(platform)
        statuses = [c.get("status", "") for c in checks]
        alive_checks = [c for c in checks if c.get("status", "") in REACHABLE_STATUSES]
        latest = checks[-1] if checks else {"status": "", "timestamp": ""}
        rows.append({
            "domain": domain,
            "platform_name": platform.get("platform_name", ""),
            "current_state": classify_current(checks),
            "latest_status": latest.get("status", ""),
            "latest_timestamp": latest.get("timestamp", ""),
            "recent_statuses": " -> ".join(statuses[-3:]),
            "consecutive_non_alive": consecutive_non_alive(checks),
            "ever_seen_alive": "yes" if alive_checks else "no",
            "last_seen_alive": alive_checks[-1].get("timestamp", "") if alive_checks else "",
            "first_seen": checks[0].get("timestamp", "") if checks else "",
            "total_checks": len(checks),
        })

    order = {"DEAD": 0, "UNCERTAIN": 1, "ALIVE": 2}
    rows.sort(key=lambda row: (order.get(row["current_state"], 9), row["domain"]))
    return rows


def save_current_status(platforms):
    rows = current_rows(platforms)
    fields = [
        "domain", "platform_name", "current_state", "latest_status",
        "latest_timestamp", "recent_statuses", "consecutive_non_alive",
        "ever_seen_alive", "last_seen_alive", "first_seen", "total_checks",
    ]

    for path, selected in (
        (CURRENT_STATUS_CSV, rows),
        (CURRENT_REVIEW_CSV, [r for r in rows if r["current_state"] != "ALIVE"]),
    ):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(selected)

    return Counter(row["current_state"] for row in rows)


def canonicalize_daily_summary(path):
    """Keep one XLSX snapshot per day instead of four numbered copies."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    canonical = RESULTS_DIR / f"summary_{date_str}.xlsx"
    path = Path(path)

    if path != canonical:
        if canonical.exists():
            canonical.unlink()
        path.replace(canonical)

    for extra in RESULTS_DIR.glob(f"summary_{date_str}_*.xlsx"):
        extra.unlink()
    return canonical


def main():
    print("读取检测结果...")
    platforms = summarize.load_results()
    rejected = remove_invalid_domains(platforms)
    resumed = clear_obsolete_stopped_markers(platforms)

    print(f"有效平台: {len(platforms)} 个")
    if rejected:
        print("汇总中跳过无效域名:", ", ".join(sorted(set(rejected))[:20]))
    if resumed:
        print("汇总中解除历史停服标记:", ", ".join(sorted(resumed)))

    path, alive, uncertain, dead = summarize.save_excel(platforms)
    path = canonicalize_daily_summary(path)
    review_count = summarize.save_needs_review(platforms)
    latest_plot_path, daily_plot_path = summarize.save_summary_plot(
        platforms, alive, uncertain, dead, review_count
    )
    current_counts = save_current_status(platforms)

    print("\n── 历史综合判断（是否曾确认可达）──")
    print(f"  ALIVE     {alive}")
    print(f"  UNCERTAIN {uncertain}")
    print(f"  DEAD      {dead}")
    print("\n── 当前状态（最近三次规则）──")
    print(f"  ALIVE     {current_counts.get('ALIVE', 0)}")
    print(f"  UNCERTAIN {current_counts.get('UNCERTAIN', 0)}")
    print(f"  DEAD      {current_counts.get('DEAD', 0)}")
    print(f"\n每日汇总: {path}")
    print(f"当前状态表: {CURRENT_STATUS_CSV}")
    print(f"当前待复核表: {CURRENT_REVIEW_CSV}")
    print(f"最新概览图: {latest_plot_path}")
    print(f"每日概览图: {daily_plot_path}")


if __name__ == "__main__":
    main()
