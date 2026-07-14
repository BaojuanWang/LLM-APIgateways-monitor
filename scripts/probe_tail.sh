#!/usr/bin/env bash
# Tighten the §4.1 concentration lower bound: re-probe the FOFA "openai-
# unidentified" tail with the deep tech-stack fingerprint probe, then adjudicate
# how much of it is actually reskinned one-api.
#
# Must run where outbound HTTP to arbitrary relay sites is allowed (your local
# machine) — NOT in the sandbox (proxy 403s arbitrary hosts) and not needed in
# CI unless you prefer it there.
#
#   bash scripts/probe_tail.sh
#
# Inputs : results/tail/fofa_tail_domains.txt   (the 66 tail domains, committed)
# Outputs: results/tail/fofa_tail_fingerprints.csv  (raw probe)
#          results/tail/tail_verdict.csv            (per-site verdict)
set -e
cd "$(dirname "$0")/.."

echo "==> probing FOFA heterogeneous tail (deep tech-stack fingerprint)…"
python3 scripts/tech_stack_fingerprint_probe.py \
    --input results/tail/fofa_tail_domains.txt \
    --out   results/tail/fofa_tail_fingerprints.csv \
    --timeout 12 --sleep 0.3

echo
echo "==> adjudicating: hidden one-api vs genuine heterogeneous…"
python3 scripts/analyze_tail.py \
    --probe  results/tail/fofa_tail_fingerprints.csv \
    --master data/master_sites.csv

echo
echo "Done. Review results/tail/tail_verdict.csv, then push:"
echo "    git add results/tail/"
echo "    git commit -m 'Tighten §4.1 bound: re-probe FOFA heterogeneous tail'"
echo "    git push origin claude/session-context-or9q0m"
