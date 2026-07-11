#!/usr/bin/env bash
# Run the whole analysis chain locally, then you review + commit + push.
# Only enrich.py touches the network (~60-90 min for ~925 hosts); the rest is
# fast local computation. enrich.py autosaves every 10 domains, so it is safe to
# Ctrl-C and re-run — it resumes from data/enrichment.csv.
#
# Usage (from repo root):
#   pip install requests openpyxl python-whois dnspython
#   bash scripts/refresh_all.sh
set -e
cd "$(dirname "$0")/.."

echo "==> [1/5] enrich (network — WHOIS / SSL incl. not_before / IP / favicon)…"
python3 scripts/enrich.py

echo "==> [2/5] build_master (merge every source into one row per site)…"
python3 scripts/build_master.py >/dev/null

echo "==> [3/5] operator_matching (group domains into operators)…"
python3 scripts/operator_matching.py | tail -6

echo "==> [4/7] site_characterization (stack taxonomy + distributions)…"
python3 scripts/site_characterization.py | tail -4

echo "==> [5/7] operator_profiles + site_similarity + cert_siblings + classify_sites…"
python3 scripts/operator_profiles.py
python3 scripts/site_similarity.py | tail -2
python3 scripts/cert_siblings.py | tail -2
python3 scripts/classify_sites.py

echo "==> [6/7] deep_analysis (full report)…"
python3 scripts/deep_analysis.py

echo "==> [7/7] make_dashboard (regenerate the distribution dashboard)…"
python3 scripts/make_dashboard.py

echo
echo "Done. Review the changes, then push:"
echo "    git add data/enrichment.csv results/master/"
echo "    git commit -m 'refresh: enrich the 764 + rebuild analysis'"
echo "    git push origin claude/session-context-or9q0m"
