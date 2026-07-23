# archive_config — reviewed capture-eligibility register

`capture_exclusions.csv` is a **non-destructive** eligibility layer for the local
WACZ archive planner. It never edits the authoritative inventories
(`data/hvoy_latest.csv`, `data/manual_sites.csv`, `data/master_sites.csv`) or the
historical monitor results — it records human review decisions the planner reads
at plan time.

## Columns

| column | meaning |
|---|---|
| `domain` | host as it appears in the monitor inventory (host-level identity) |
| `status` | `excluded` or `questionable` |
| `reason` | short human-readable justification |
| `evidence` | the observation(s) the decision rests on (monitor redirect target, discovery signal tier, etc.) |
| `reviewed_at` | date of review (UTC date) |
| `review_version` | version tag so decisions are auditable across revisions |

## Semantics

- **`excluded`** — a *confirmed* false positive (an upstream provider, an
  unrelated platform, a blog/doc host, payment infrastructure). The planner
  removes these from the capture queue and reports them under `excluded`.
  Use this status **only** when the entity is clearly not a study-eligible relay.
- **`questionable`** — an uncertain case. The planner leaves it in the queue but
  flags it (`⚑QUESTIONABLE`) and counts it, so a human can decide before capture.
  Uncertain cases are kept questionable rather than excluded by default.

## Principles

1. **Eligibility is a judgment about the entity, not the fingerprint.** A
   discovery endpoint fingerprint (running one-api, answering `/v1/models`) is a
   discovery signal, not proof of study eligibility — an upstream provider
   answers `/v1/models` too (e.g. `tokenhub.tencentcloudmaas.com`). Nothing here
   treats a fingerprint as grounds for *inclusion*.
2. **Aggregators are in scope by role.** The study defines `aggregator` as a
   `site_role` (see `docs/DATA_DICTIONARY.md`), so global independent aggregators
   are not auto-excluded; they are marked `questionable` pending a decision.
3. **Append, don't rewrite.** When revising, bump `review_version` rather than
   silently editing history.

## Usage

```bash
# planner auto-loads this file when present; or point at another register:
python3 archive/scripts/plan_archive_queue.py --dry-run --max-sites 100
python3 archive/scripts/plan_archive_queue.py --dry-run --exclusions-file <path>
python3 archive/scripts/plan_archive_queue.py --dry-run --no-exclusions   # ignore it
```
