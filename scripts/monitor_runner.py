"""Run the regular monitor with stopped-service recovery and input validation."""

import csv
from pathlib import Path

import pipeline
from domain_utils import is_valid_host

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


def validated_platform_loader(original_loader):
    """Wrap pipeline.load_platforms and drop malformed or placeholder domains."""

    def load_validated():
        platforms = original_loader()
        valid = []
        rejected = []
        for platform in platforms:
            domain = platform.get("domain", "")
            if is_valid_host(domain):
                valid.append(platform)
            else:
                rejected.append(domain or "<empty>")

        if rejected:
            print(
                f"跳过 {len(rejected)} 个无效域名输入: "
                + ", ".join(sorted(set(rejected))[:20])
            )
        return valid

    return load_validated


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

    pipeline.load_platforms = validated_platform_loader(pipeline.load_platforms)
    pipeline.main()


if __name__ == "__main__":
    main()
