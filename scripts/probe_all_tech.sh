#!/usr/bin/env bash
# FULL-COVERAGE deep tech-stack fingerprint over ALL 1206 sites — the same
# WASABO-style probe used on the FOFA tail / seed, but on the whole dataset.
# This upgrades the tech-stack labels from weak substring matching (17% deep
# coverage) to rigorous fingerprinting at 100%, with status decomposition
# (dead / blocked / spa_shell / unidentified) instead of a flat "unknown".
#
# Local only (network; sandbox 403s these hosts). Resumable — the probe skips
# domains already in the output CSV, so a stop/restart continues.
#
#   bash scripts/probe_all_tech.sh
#
# Input : results/fulltech/all_domains.txt   (1206 domains, committed)
# Output: results/fulltech/all_fingerprints.csv
set -e
cd "$(dirname "$0")/.."

echo "==> deep tech-stack fingerprint over ALL 1206 sites (resumable)…"
python3 scripts/tech_stack_fingerprint_probe.py \
    --input results/fulltech/all_domains.txt \
    --out   results/fulltech/all_fingerprints.csv \
    --timeout 6 --sleep 0.2

echo
echo "==> coverage + distribution (fork-level: one-api vs new-api NOT merged)…"
python3 - <<'PY'
import csv, collections
rows=list(csv.DictReader(open("results/fulltech/all_fingerprints.csv",encoding="utf-8-sig")))
n=len(rows)
# status decomposition
st=collections.Counter((r.get("status_class") or "?") for r in rows)
# fork-level stack (do NOT merge one-api / new-api)
fork=collections.Counter((r.get("app_stack_guess") or "unknown") for r in rows)
print(f"\n全量深度指纹: {n} 站")
print("\n— 状态分层 —")
for k,v in st.most_common(): print(f"  {k:16s} {v:4d}  {100*v//n}%")
print("\n— 细粒度技术栈(fork级,不合并)Top15 —")
for k,v in fork.most_common(15): print(f"  {k:22s} {v:4d}  {100*v//n}%")
ident=sum(v for k,v in st.items() if k in ("identified","family_only"))
print(f"\n可指纹识别率: {ident}/{n} = {100*ident//n}%  (其余为 死/拦/空壳/真未识别)")
PY

echo
echo "Done. Push results (CSV only, small):"
echo "    git add results/fulltech/all_fingerprints.csv && git commit -m 'full-coverage tech-stack fingerprint' && git push origin claude/session-context-or9q0m"
