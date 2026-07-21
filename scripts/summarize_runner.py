"""Generate summaries while allowing confirmed stopped services to revive.

The legacy summarizer intentionally lets an explicit SERVICE_STOPPED marker
outweigh older reachable observations. After a real stopped-service recheck
finds a domain reachable, that historical marker must no longer keep the domain
permanently classified as DEAD.
"""

import csv
from pathlib import Path

import summarize

BASE_DIR = Path(__file__).parent.parent
RECHECK_CSV = BASE_DIR / "results" / "stopped_service_rechecks.csv"

REACHABLE_STATUSES = {
    "ONLINE",
    "ONLINE_LOGIN_REQUIRED",
    "CLOUDFLARE_OR_BLOCKED",
    "REDIRECTED",
    "HTTP_444",
}


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


def main():
    print("读取检测结果...")
    platforms = summarize.load_results()
    resumed = clear_obsolete_stopped_markers(platforms)
    print(f"共 {len(platforms)} 个平台")
    if resumed:
        print("汇总中解除历史停服标记:", ", ".join(sorted(resumed)))

    path, alive, uncertain, dead = summarize.save_excel(platforms)
    review_count = summarize.save_needs_review(platforms)
    latest_plot_path, daily_plot_path = summarize.save_summary_plot(
        platforms, alive, uncertain, dead, review_count
    )

    print("\n── 综合判断 ──")
    print(f"  ALIVE     {alive}")
    print(f"  UNCERTAIN {uncertain}")
    print(f"  DEAD      {dead}")
    print(f"\n已保存: {path}")
    print(f"最新概览图已覆盖: {latest_plot_path}")
    print(f"每日概览图已覆盖: {daily_plot_path}")
    print(f"需手动确认: {review_count} 个 → {summarize.REVIEW_CSV}")


if __name__ == "__main__":
    main()
