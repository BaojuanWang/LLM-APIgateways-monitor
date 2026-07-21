"""Run the regular monitor while honoring stopped-service recheck results.

A domain remains in ``pipeline.STOPPED_SERVICES`` until a real weekly recheck
returns a reachable status. Once reachable, the synthetic SERVICE_STOPPED
shortcut is removed for that run and normal six-hour probing resumes.
"""

import csv
from pathlib import Path

import pipeline

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


def main():
    rechecks = latest_rechecks()
    resumed = []

    for domain in list(pipeline.STOPPED_SERVICES):
        row = rechecks.get(domain)
        if row and row.get("online_status") in REACHABLE_STATUSES:
            pipeline.STOPPED_SERVICES.pop(domain, None)
            resumed.append(domain)

    if resumed:
        print("复查后恢复常规监控:", ", ".join(sorted(resumed)))

    pipeline.main()


if __name__ == "__main__":
    main()
