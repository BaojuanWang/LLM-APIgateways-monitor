# LLM API Gateway Monitor

A measurement pipeline for the **LLM API relay ("中转站") ecosystem** — the
third-party gateways that resell or re-broker access to commercial LLM APIs. The
project builds a reproducible, longitudinally-updated map of this supply side:
which software stacks the sites run, how they are deployed and hosted, when they
appeared, and how many nominally-independent domains actually trace back to the
same operator.

The research question is **supply-side infrastructure characterization**, not
data-plane abuse (model-identity mismatch, token dilution, etc.) — that space is
covered elsewhere and is deliberately out of scope here.

---

## What it measures

The pipeline is organised as two layers with a clean interface between them.

**1. Discovery + collection** produces, for each site, a set of raw
observations:

- **Liveness** — periodic reachability / status classification.
- **Application stack** — new-api / one-api family, sub2api, and related forks,
  via HTTP header, body, and unauthenticated-endpoint fingerprints.
- **Infrastructure** — WHOIS (registration date, registrar), TLS certificate
  (issuer, SAN, SHA-256 fingerprint, `not_before`), IP / ASN / hosting / geo,
  server headers, favicon hash.
- **Operations** — privacy-policy presence, contact channels, affiliate pages,
  model/pricing visibility.

**2. Analysis** turns those observations into findings:

- **Master merge** — every source outer-joined into one row per site, keyed on
  the registrable domain (eTLD+1), so host variants collapse.
- **Operator grouping** — a union-find over shared signals (TLS certificate,
  certificate SAN, favicon, origin IP, operator display name) that collapses
  domains into operators, with explicit guardrails against CDN- and
  default-asset false merges.
- **Characterization** — stack taxonomy, birth timeline, hosting / CA /
  registrar / country / TLD distributions, domain-naming themes, and
  concentration metrics (HHI).
- **Seed feedback** — certificate-SAN sibling domains extracted as new discovery
  seeds.

Methodology and the literature grounding for every signal and heuristic are in
[`docs/METHODS_element_citations.md`](docs/METHODS_element_citations.md).

---

## Pipeline

```
 discovery list ─┐
 hvoy / manual ──┤
                 ▼
        collection (network)
   pipeline.py · enrich.py · privacy.py · contacts.py · model_price_probe.py
                 │
                 ▼
        build_master.py            one row per site (eTLD+1)
                 │
      ┌──────────┼───────────────┬────────────────────┐
      ▼          ▼               ▼                    ▼
 operator_    site_          deep_analysis.py    cert_siblings.py
 matching.py  characterization.py  (report)      (new seeds)
      │          │               │
      └──────────┴───────────────┘
                 ▼
        make_dashboard.py          interactive distribution dashboard
```

Run the whole analysis chain locally with
[`scripts/refresh_all.sh`](scripts/refresh_all.sh); only the collection step
touches the network.

---

## Scripts

### Collection (require network)

| Script | Purpose |
|---|---|
| `pipeline.py` | Liveness / status classification, appended to `results/monitor_results.csv`. |
| `enrich.py` | WHOIS, TLS cert (issuer/SAN/fingerprint/`not_before`), IP/ASN/geo, server headers, favicon → `data/enrichment.csv`. |
| `privacy.py` | Privacy-policy fetch + snapshot + rule-based coding → `data/privacy.csv`. |
| `contacts.py` | Contact channels (Telegram/QQ/WeChat/Discord) + affiliate detection → `data/contacts.csv`. |
| `model_price_probe.py` | Model list / pricing-page visibility → `results/model_prices/`. |
| `tech_stack_fingerprint_probe.py` | Tiered stack fingerprint (fork / family / domain confidence) with distinct blocked / SPA / unreachable buckets. |
| `screenshot.py` | Page screenshots. |
| `hvoy_tracker*.py` | Legacy hvoy list tracker (retained; not on the monitor path). |

### Analysis (local, no network)

| Script | Purpose |
|---|---|
| `build_master.py` | Defensive outer-join of every source into `results/master/master_table.csv`, keyed on eTLD+1. |
| `operator_matching.py` | Union-find operator grouping → `operator_clusters.csv` + `operator_summary.csv` (HHI). |
| `site_characterization.py` | Unified stack taxonomy + per-site labels → `site_stack_labels.csv`. |
| `deep_analysis.py` | Full feature report (liveness, timeline, infra, CA, registrar, naming, price, cross-tabs) → `ANALYSIS_REPORT.md`. |
| `operator_profiles.py` | Per-operator aggregate profiles + favicon families → `operator_profiles.csv`, `favicon_families.csv`. |
| `cert_siblings.py` | Certificate-SAN sibling-domain extraction → `cert_sibling_seeds.csv`. |
| `make_dashboard.py` | Regenerate the interactive distribution dashboard (`ecosystem_dashboard.html`). |
| `quality_audit.py` | Privacy-snapshot text-quality audit. |
| `summarize.py` | Monitor-result summary tables / status graphics. |

### Utilities

| Script | Purpose |
|---|---|
| `domain_utils.py` | Registrable-domain (eTLD+1) and host normalization (stdlib only). |
| `refresh_all.sh` | One-command local run: enrich → build_master → operator_matching → site_characterization → make_dashboard. |

---

## Outputs

Analysis artifacts are written to `results/master/`:

| File | Contents |
|---|---|
| `master_table.csv` | One row per site, all sources joined (namespaced columns). |
| `all_sites_merged.csv` | Human-readable one-row-per-site summary (curated columns). |
| `operator_clusters.csv` / `operator_summary.csv` | Domain→operator assignment + concentration metrics. |
| `operator_profiles.csv` | Multi-site operators with aggregated features and tie signals. |
| `favicon_families.csv` | Sites sharing a non-default favicon (template / operator families). |
| `site_stack_labels.csv` | Per-site unified stack family + feature flags. |
| `ANALYSIS_REPORT.md` | Full deep-characterization report. |
| `cert_sibling_seeds.csv` | Operator sibling domains for discovery expansion. |
| `ecosystem_dashboard.html` | Self-contained interactive dashboard. |

---

## Running

Collection must run on an ordinary network (a TLS-intercepting environment
corrupts certificate data). The repository is public, so GitHub Actions is free;
local execution is equally supported.

```bash
pip install requests openpyxl python-whois dnspython
bash scripts/refresh_all.sh          # enrich (~60-90 min) + full analysis chain
git add data/enrichment.csv results/master/
git commit -m "refresh: enrich + rebuild analysis"
git push
```

`enrich.py` autosaves every 10 domains and is resumable. Analysis-only reruns
(after new data lands) skip the network:

```bash
python3 scripts/build_master.py
python3 scripts/operator_matching.py
python3 scripts/site_characterization.py
python3 scripts/deep_analysis.py
python3 scripts/operator_profiles.py
python3 scripts/make_dashboard.py
```

Workflows under `.github/workflows/` (`monitor`, `enrich`, `model-prices`,
`screenshot`, `tech-stack`) run the collectors on a schedule or on demand.

---

## Selected findings

Current snapshot (809 sites; discovery set union monitored set, collapsed to
registrable domains):

- **Near-monoculture stack** — ~78% of sites run the one-api family; a
  fingerprint-level single point of failure.
- **Very young ecosystem** — ~99% of sites have a resolvable birth date (WHOIS
  with certificate `not_before` fallback); ~73% appeared in 2025-2026 and ~55%
  in 2026 alone, peaking mid-2026.
- **Zero-cost startup profile** — ~85% use free DV certificates (Let's Encrypt +
  Google Trust Services); hosting concentrated on Cloudflare edges.
- **Apparent diversity, structural concentration** — grouping reveals single
  operators running several differently-branded sites (e.g. one operator across
  six domains under five brand names), even though population-level operator
  concentration is otherwise low.

Numbers refresh with each collection run; see `ANALYSIS_REPORT.md` and the
dashboard for current values and full caveats.

---

## Ethics

All probing is read-only: unauthenticated GETs and standard TLS handshakes to
public endpoints, rate-limited, with no login attempts, no state-changing
requests, and no attack-shaped payloads. Endpoint checks test for existence
only. Low-coverage fields (contacts, privacy, ICP) are reported with explicit
coverage caveats rather than over-claimed.

---

## Documentation

- [`docs/analysis_pipeline.md`](docs/analysis_pipeline.md) — analysis stages and the discovery-layer interface.
- [`docs/METHODS_element_citations.md`](docs/METHODS_element_citations.md) — every method mapped to published precedent.
- [`docs/METHODS_literature_grounding_2026-07-08.md`](docs/METHODS_literature_grounding_2026-07-08.md) — higher-level methodology grounding.
- [`docs/tech_stack_fingerprints.md`](docs/tech_stack_fingerprints.md) — fingerprint taxonomy and confidence tiers.
- [`docs/AUDIT_collectors_2026-07-08.md`](docs/AUDIT_collectors_2026-07-08.md) — collector audit and known limitations.
