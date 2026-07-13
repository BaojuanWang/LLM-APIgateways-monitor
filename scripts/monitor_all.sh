#!/usr/bin/env bash
# Full-coverage liveness + evidence pass over ALL discovered sites (1205),
# same flow as the seed sites: check status, then screenshot new/changed sites
# for evidence. Run locally (needs network + Playwright); the sandbox 403s
# these hosts. Everything is incremental (screenshot skips already-captured).
#
#   bash scripts/monitor_all.sh
#
# Outputs:
#   results/monitor_results.csv   — per-site liveness/status this round
#   data/screenshots/*.png        — homepage evidence for new/changed sites
#   results/summary*              — summary
set -e
cd "$(dirname "$0")/.."

echo "==> [1/3] liveness — status of all 1205 sites (pipeline.py)…"
python3 scripts/pipeline.py

echo "==> [2/3] evidence — screenshot NEW / changed sites (skips already-shot)…"
python3 scripts/screenshot.py

echo "==> [3/3] summary…"
python3 scripts/summarize.py || true

echo
echo "Done. Review, then push (screenshots included):"
echo "    git add data/ results/"
echo "    git commit -m 'full liveness + evidence screenshots'"
echo "    git push origin claude/session-context-or9q0m"
