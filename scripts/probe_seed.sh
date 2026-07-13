#!/usr/bin/env bash
# Identify the 143 UNLABELED SEED sites with the SAME deep tech-stack
# fingerprint probe used on the FOFA tail (probe_tail.sh) — so the seed
# cross-validation is methodologically comparable to §4.1 / §14.1.
#
# Local only (needs outbound HTTP; sandbox 403s these hosts). Resumable.
#
#   bash scripts/probe_seed.sh
#
# Input : results/seed/unlabeled_seed_domains.txt  (143 domains, committed)
# Output: results/seed/seed_fingerprints.csv       (raw probe)
#         + printed bucket summary
set -e
cd "$(dirname "$0")/.."

echo "==> probing 143 unlabeled seed sites (same probe as FOFA tail)…"
python3 scripts/tech_stack_fingerprint_probe.py \
    --input results/seed/unlabeled_seed_domains.txt \
    --out   results/seed/seed_fingerprints.csv \
    --timeout 6 --sleep 0.2

echo
echo "==> bucket summary (one-api vs other vs genuine-unknown vs dead)…"
python3 - <<'PY'
import csv, collections
rows=list(csv.DictReader(open("results/seed/seed_fingerprints.csv",encoding="utf-8-sig")))
def bucket(r):
    fam=(r.get("app_family") or "").lower(); st=(r.get("status_class") or "").lower()
    if "one-api" in fam or "new-api" in fam: return "one-api(补认)"
    if st in ("identified","family_only") and (r.get("app_stack_guess") or "") not in ("","unknown"): return "其他框架"
    if st in ("unidentified","spa_shell","domain_hint"): return "真未识别"
    return "探不通/死站"
c=collections.Counter(bucket(r) for r in rows); n=len(rows)
print(f"\n未识别种子站复认结果 (n={n}):")
for k,v in c.most_common(): print(f"  {k:16s} {v:4d}  {100*v//n}%")
ident=sum(v for k,v in c.items() if "one-api" in k)
reach=n - c.get("探不通/死站",0)
print(f"\n可达站中 one-api 占比: {ident}/{reach} = {100*ident//max(reach,1)}%  (对照 FOFA 71% / GitHub 96%)")
PY

echo
echo "Done. Push results:"
echo "    git add results/seed/ && git commit -m 'seed unlabeled re-probe' && git push origin claude/session-context-or9q0m"
