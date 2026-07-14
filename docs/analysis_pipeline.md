# Analysis layer pipeline

Turns the per-site data sources into findings. Two stages, run from the repo root:

```bash
python3 scripts/build_master.py        # 1. merge everything into one row per site
python3 scripts/operator_matching.py   # 2. collapse domains into operators
```

## Stage 1 — `build_master.py`

Outer-joins every per-site source (monitor status, tech-stack, enrichment,
privacy, contacts, price, and the discovery-layer `master_sites.csv` when it
exists) into **one row per site**, keyed on the registrable domain (eTLD+1).

- Host variants collapse to one key: `https://Api.Toknex.ai/`, `www.toknex.ai`
  and `toknex.ai` → `toknex.ai` (see `scripts/domain_utils.py`).
- Domain columns are auto-detected (`domain` / `siteDomain` / `url` / …).
- Missing files/columns are skipped and recorded, never fatal.
- Columns are namespaced per source (`enrich__ip_asn`, `contacts__telegram`).
- Each run writes a timestamped snapshot under `results/master/snapshots/`
  (gitignored) plus the canonical `results/master/master_table.csv` and a
  `master_coverage.csv` report.

### Discovery-layer interface

The discovery window's deliverable is `data/master_sites.csv` (one row per
confirmed relay). `build_master.py` already lists it as source `disc` and picks
it up automatically once present — no code change needed. Expected columns:
`domain, origin, discovery_methods, verdict, framework, platform_name,
verified_site_name, api_status_hit, html_framework_hit, content_hits`. The
`framework` field is trusted as-is (no re-probing) and surfaces as
`disc__framework`.

## Stage 2 — `operator_matching.py`

Unions sites that share operator-linking signals into operator clusters
(union-find), producing the "N domains → M operators" concentration finding
(`results/master/operator_clusters.csv` + `operator_summary.csv` with an HHI).

Signals by reliability: (1) cert fingerprint, (2) shared cert SAN, (3) favicon
hash, (4) origin IP, (5) contact handle. Guardrails against over-merging:

- the one-api **default favicon** (auto-detected, ~35% of sites) is excluded;
- **CDN-fronted sites are dropped from IP edges** — a Cloudflare edge IP is
  shared by unrelated sites, so it is not an origin tie;
- **ASN is annotation only**, never a merge edge (too coarse — 43.5% of sites
  are on Cloudflare AS13335);
- any medium signal shared by more than `--max-share` sites is dropped as
  generic (this is what caught the `_oauth_enabled` WeChat-regex false positive).

Cert signals (the strongest) activate automatically once `enrich.py` populates
`ssl_fingerprint` / `ssl_san`; until then matching falls back to
favicon + IP + contacts, so concentration reads low. Re-run after an enrichment
pass to get the cert-backed clusters.

Methodology grounding: `docs/METHODS_literature_grounding_2026-07-08.md` §4–5.
