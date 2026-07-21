"""Perform real network checks for manually stopped services.

The regular monitor intentionally records these domains as SERVICE_STOPPED.
This script bypasses that shortcut, performs a real request, appends the result
to the main longitudinal file, and maintains a compact recheck history used by
``monitor_runner.py`` to detect service resurrection.
"""

import csv
from pathlib import Path

import pipeline

BASE_DIR = Path(__file__).parent.parent
RECHECK_CSV = BASE_DIR / "results" / "stopped_service_rechecks.csv"


def append_rechecks(results):
    RECHECK_CSV.parent.mkdir(parents=True, exist_ok=True)
    exists = RECHECK_CSV.exists()
    with open(RECHECK_CSV, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=pipeline.RESULT_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerows(results)


def main():
    stopped = dict(pipeline.STOPPED_SERVICES)
    if not stopped:
        print("没有人工标记的停服站点。")
        return

    results = []
    for domain, info in sorted(stopped.items()):
        # Remove the sentinel so check_one performs a real network request.
        pipeline.STOPPED_SERVICES.pop(domain, None)
        platform = {
            "domain": domain,
            "platform_name": info.get("platform_name", ""),
            "source": "stopped_recheck",
        }
        result = pipeline.check_one(platform)
        result["source"] = "stopped_recheck"
        results.append(result)
        print(f"{domain:<35} {result['online_status']}")

    pipeline.append_results(results)
    append_rechecks(results)
    print(f"已追加 {len(results)} 条真实复查结果到 {RECHECK_CSV}")


if __name__ == "__main__":
    main()
