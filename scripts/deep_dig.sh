#!/usr/bin/env bash
# Deep-dig collection: fill the identity + privacy + contact gaps across the
# FULL discovery list (not just the seed), then rebuild the analysis layer.
#
# Why this exists: privacy.py / contacts.py historically only read the seed
# (hvoy + manual), so FOFA/GitHub sites were 0-20% covered. enrich.py stored
# the registrar but not the registrant identity. Those are fixed; this script
# runs the now-full-coverage collectors.
#
# Run on your local machine (needs outbound HTTP + WHOIS port 43 — both blocked
# in the sandbox). Everything is incremental / resumable (autosaves).
#
#   bash scripts/deep_dig.sh
#
# COST: the WHOIS pass re-queries every domain once to backfill the new
# registrant columns (one-time migration) — expect this to be the slow part.
set -e
cd "$(dirname "$0")/.."

echo "==================== IDENTITY + PRIVACY (network) ===================="
echo "==> enrich — WHOIS registrant backfill (org/name/country) + certs/IP…"
python3 scripts/enrich.py
echo "==> privacy — crawl privacy policy across the full list…"
python3 scripts/privacy.py
echo "==> contacts — telegram/qq/discord/affiliate across the full list…"
python3 scripts/contacts.py
echo "==> operations — payment / trust claims / faka…"
python3 scripts/operations_probe.py

echo "==================== REBUILD ANALYSIS (local) ===================="
python3 scripts/build_master.py          >/dev/null && echo "  build_master ok"
python3 scripts/operator_matching.py     | tail -3
python3 scripts/site_characterization.py | tail -3
python3 scripts/operator_profiles.py
python3 scripts/site_similarity.py       | tail -2
python3 scripts/cert_siblings.py         | tail -2
python3 scripts/classify_sites.py
python3 scripts/deep_analysis.py
python3 scripts/make_dashboard.py

echo
echo "Done. Review results/master/, then push:"
echo "    git add data/ results/master/"
echo "    git commit -m 'deep-dig: registrant identity + full-coverage privacy/contacts'"
echo "    git push origin claude/session-context-or9q0m"
