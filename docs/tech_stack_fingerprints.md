# Tech Stack Fingerprint Methodology

This project should treat API relay tech-stack detection as a best-effort classification problem, not as ground truth. A site can hide or rewrite its backend implementation behind Cloudflare, Nginx, a custom landing page, or a white-label frontend.

## Categories

### Application-layer relay implementations

- `one-api`: original One API family.
- `new-api`: QuantumNous/new-api family and close forks.
- `veloera`: new-api fork/variant.
- `one-hub` / `done-hub`: one-api/new-api derived hub variants.
- `voapi`: modified one-api/new-api style implementation.
- `shell-api`, `super-api`, `neo-api`: named one-api-like variants.
- `sub2api`: subscription-to-API conversion layer.
- `auth2api`: OAuth-to-API conversion layer.
- `cliproxyapi`: CLI proxy API / CPA-style conversion layer.
- `xxx2api`: generic conversion-layer marker when only a `*2api` token is visible.
- `all-api-hub` / `metapi`: aggregator/meta-router layer.
- `white_label_or_custom`: visible relay service, but recognizable upstream project is hidden.

### Infrastructure-layer signals

- `cloudflare`: CDN/WAF/challenge layer.
- `nginx`: reverse proxy/server layer.

Infrastructure signals must not be counted as application implementations. For example, `Cloudflare` means the site is behind Cloudflare; it does not mean the relay software is Cloudflare.

## Evidence Strength

### Strong Evidence

- HTTP headers that explicitly name the implementation:
  - `X-New-Api-Version`
  - `X-Oneapi-*`
  - `X-One-Api-*`
- HTML or JavaScript text that explicitly names a project:
  - `new-api`
  - `New API`
  - `one-api`
  - `Sub2API`
  - `Subscription to API Conversion Platform`
  - `auth2api`
  - `cliproxyapi`
  - `veloera`
  - `voapi`
  - `one-hub`
  - `done-hub`
- Known unauthenticated endpoints whose JSON/schema clearly matches a project.

### Medium Evidence

- Static asset paths, favicon/title strings, or frontend route names strongly associated with an implementation, but without an explicit project name.
- Domain names containing `newapi`, `sub2api`, or another implementation token.

### Weak Evidence

- Server/CDN headers only: `nginx`, `cloudflare`.
- Generic API routes like `/v1/models` or `/api/status` without distinctive schema.

## Bias Warning

If the fingerprint list only covers `new-api`, the dataset will over-count `new-api` and under-count other implementations such as `sub2api`, `one-api`, `auth2api`, and white-label forks. `unknown` and `infrastructure_only` rows should be treated as missing-not-at-random, because many relay sites actively hide or customize their backend.

## Recommended Output Fields

- `domain`
- `input_url`
- `final_url`
- `http_status`
- `infrastructure_signals`
- `app_stack_guess`
- `app_family`
- `confidence`
- `evidence`
- `probed_paths`
- `error`

## Current Probe Script

Run from the repository root:

```bash
python3 scripts/tech_stack_fingerprint_probe.py
```

By default the script merges `data/hvoy_latest.csv` and `data/manual_sites.csv`, probes each unique domain, and writes:

```text
results/tech_stack_fingerprints.csv
```

For a small smoke test:

```bash
python3 scripts/tech_stack_fingerprint_probe.py --limit 10
```

For a custom input CSV or newline-delimited URL/domain file:

```bash
python3 scripts/tech_stack_fingerprint_probe.py --input path/to/sites.csv --out results/tech_stack_fingerprints_custom.csv
```
