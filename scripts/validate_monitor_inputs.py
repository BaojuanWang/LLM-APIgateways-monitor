"""Lightweight validation for curated monitor inputs.

Generated discovery files may legitimately contain noisy candidates, so they are
reported as warnings. The curated manual list is required to contain only valid
hostnames and correctly shaped CSV rows.
"""

import csv
import sys
from pathlib import Path

from domain_utils import is_valid_host

BASE_DIR = Path(__file__).parent.parent
MANUAL_CSV = BASE_DIR / "data" / "manual_sites.csv"
GENERATED_INPUTS = [
    BASE_DIR / "data" / "hvoy_latest.csv",
    BASE_DIR / "data" / "master_sites.csv",
]


def read_domains(path):
    if not path.exists():
        return [], [f"missing file: {path}"]

    invalid = []
    domains = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if "domain" not in (reader.fieldnames or []):
            return [], [f"missing domain column: {path}"]

        expected_columns = len(reader.fieldnames or [])
        for line_no, row in enumerate(reader, 2):
            if None in row:
                invalid.append(
                    f"{path}:{line_no}: extra CSV fields beyond {expected_columns} columns"
                )
            domain = (row.get("domain") or "").strip()
            if not domain:
                continue
            domains.append(domain)
            if not is_valid_host(domain):
                invalid.append(f"{path}:{line_no}: invalid domain {domain!r}")
    return domains, invalid


def main():
    failures = []
    manual_domains, manual_errors = read_domains(MANUAL_CSV)
    failures.extend(manual_errors)

    duplicates = sorted({d for d in manual_domains if manual_domains.count(d) > 1})
    if duplicates:
        failures.append(f"duplicate manual domains: {', '.join(duplicates)}")

    for path in GENERATED_INPUTS:
        _, warnings = read_domains(path)
        for warning in warnings[:20]:
            print(f"WARNING: {warning}")
        if len(warnings) > 20:
            print(f"WARNING: {len(warnings) - 20} additional warnings in {path}")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1

    print(f"Validated {len(manual_domains)} curated manual domains.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
