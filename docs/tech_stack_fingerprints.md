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
- `all-api-hub` / `metapi`: aggregator/meta-router layer.
- `one-api-family` (family-level label): a one-api-family site whose specific
  fork could not be resolved from the observed signals — see Confidence Tiers.

> Note: a generic `*2api` catch-all category was intentionally removed. Matching
> any `<word>2api` token mislabeled unrelated marketing text and double-labeled
> real `sub2api`/`auth2api` sites, so only named forks are now emitted.

### Infrastructure-layer signals

- `cloudflare`: CDN/WAF/challenge layer.
- `nginx`: reverse proxy/server layer.

Infrastructure signals must not be counted as application implementations. For example, `Cloudflare` means the site is behind Cloudflare; it does not mean the relay software is Cloudflare.

## Confidence Tiers

The classifier is layered by discriminative power. A signal never resolves a
label finer than its tier — in particular, a family-level signal must never be
promoted to a specific fork.

### Tier 1 — fork (`confidence = high`)

Signals unique to ONE implementation. Emits a specific fork label.

- HTTP headers that name the implementation: `X-New-Api-Version` (→ new-api,
  also yields the version), `X-Oneapi-*` / `X-One-Api-*` (→ one-api).
- Distinctive project names / author handles in body text: `QuantumNous` or
  `Calcium-Ion/new-api` (→ new-api), `songquanpeng` (→ one-api), `Sub2API` /
  `Subscription to API Conversion Platform`, `auth2api`, `cliproxyapi`,
  `veloera`, `voapi`, `one-hub`, `done-hub`, `shell-api`, `super-api`,
  `neo-api`, `all-api-hub`, `metapi`.

### Tier 2 — family (`confidence = family`)

Signals shared across a whole family; resolves the family, not the fork.

- Generic residual branding: hyphen/underscore/joined `new-api` or `one-api`
  left in page text (spaced "new api" is deliberately NOT matched — too
  generic). → `one-api-family`.
- The one-api-family `/api/status` JSON envelope (keyed on a `system_name`
  field; also yields `version`). Generic `/v1/models` lists are ignored because
  every relay proxies them.

### Tier 3 — domain hint (`confidence = low`)

- Domain name containing `newapi`, `sub2api`, `auth2api`, `cliproxyapi`. Weak:
  an operator can name a domain anything.

### Not identified (`confidence = none`) — split into `status_class` buckets

Rather than collapsing everything unrecognized into one `unknown`, the reason is
recorded so live-but-hidden sites are not counted as dead:

- `blocked`: Cloudflare/JS challenge — the site is alive but the backend is
  hidden behind a WAF challenge.
- `spa_shell`: an empty SPA shell (`<div id="root">` etc.) — the real
  fingerprint is inside an unfetched JS bundle.
- `unreachable`: no HTTP response on any probed path.
- `unidentified`: reachable, has content, but no known signal matched.

Infrastructure-only signals (`nginx`, `cloudflare`) are recorded in
`infrastructure_signals` and never counted as application implementations.

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
- `confidence` (`high` / `family` / `low` / `none`)
- `status_class` (`identified` / `family_only` / `domain_hint` / `blocked` / `spa_shell` / `unreachable` / `unidentified`)
- `version` (extracted from `X-New-Api-Version` header or `/api/status` JSON)
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
