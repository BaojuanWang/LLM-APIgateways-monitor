#!/usr/bin/env bash
# Complete end-to-end run — use this when the site list changes (e.g. a bigger
# discovery v2 list). Workflow:
#   1. drop the new data/master_sites.csv into place
#   2. bash scripts/full_refresh.sh
#   3. commit + push the printed files
#
# Cost note: collection is incremental. enrich.py skips WHOIS/SSL for domains it
# already has (only genuinely new sites pay the full static-lookup cost); IP /
# favicon / operations are refreshed for everyone. So a v2 run is roughly
# "(new sites) x full + (all sites) x light", not a full re-crawl from zero.
set -e
cd "$(dirname "$0")/.."

echo "==================== COLLECTION (network) ===================="
echo "==> enrich (WHOIS / TLS cert / IP / ASN / favicon) — incremental"
python3 scripts/enrich.py
echo "==> operations (payment / trust claims / contacts)"
python3 scripts/operations_probe.py
# Optional churn tracking for the full list (appends a liveness snapshot):
# python3 scripts/pipeline.py

echo "==================== ANALYSIS (local, seconds) ===================="
python3 scripts/build_master.py            >/dev/null && echo "  build_master ok"
python3 scripts/operator_matching.py       | tail -3
python3 scripts/site_characterization.py   | tail -3
python3 scripts/operator_profiles.py
python3 scripts/site_similarity.py         | tail -2
python3 scripts/cert_siblings.py           | tail -2
python3 scripts/classify_sites.py
python3 scripts/deep_analysis.py
python3 scripts/make_dashboard.py

echo
echo "Done. Review, then push:"
echo "    git add data/enrichment.csv data/operations.csv results/master/"
echo "    git commit -m 'full refresh: new site list'"
echo "    git push origin claude/session-context-or9q0m"
