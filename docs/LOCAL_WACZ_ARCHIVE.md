# Local WACZ archive subsystem

A local, research-grade longitudinal web archive for the services this project
monitors. It captures full WACZ web archives to an **external disk** — or, when
explicitly authorized, to this Mac's own disk — keeps them append-only and
hash-verified, and publishes only sanitized metadata to this public GitHub
repository.

The existing six-hour GitHub Actions monitor is unchanged. It remains the
lightweight change detector: cheap, frequent, and it tells this subsystem *when*
a full capture is worth taking. This is the heavyweight local capture layer.

---

## Contents

- [Architecture](#architecture)
- [Threat model](#threat-model)
- [Why GitHub does not store WACZ](#why-github-does-not-store-wacz)
- [The three layers: raw, derived, classification](#the-three-layers-raw-derived-classification)
- [Storage modes](#storage-modes)
- [External disk setup](#external-disk-setup)
- [Authorized local storage](#authorized-local-storage)
- [Commands](#commands)
- [Replaying a WACZ](#replaying-a-wacz)
- [Behaviour when the disk is unavailable](#behaviour-when-the-disk-is-unavailable)
- [Recovering from an interrupted capture](#recovering-from-an-interrupted-capture)
- [Immutability policy](#immutability-policy)
- [Retention policy](#retention-policy)
- [Tombstone semantics](#tombstone-semantics)
- [Sensitive-data handling](#sensitive-data-handling)
- [Verifying SHA256](#verifying-sha256)
- [Inspecting an old capture without modifying it](#inspecting-an-old-capture-without-modifying-it)
- [Migrating the corpus to another disk](#migrating-the-corpus-to-another-disk)
- [Scheduling with launchd](#scheduling-with-launchd)
- [Testing](#testing)
- [Known limitations](#known-limitations)

---

## Architecture

```
 GitHub Actions (every 6h, unchanged)          Local machine + external disk
 ───────────────────────────────────           ─────────────────────────────
 scripts/pipeline.py                            archive_preflight.py
   └─ results/monitor_results.csv                 └─ verify disk, pin images
        │                                       plan_archive_queue.py
        │  status / hash / title / URL            └─ read monitor + public index
        └──────────────────────────────────────►  └─ bounded, ordered queue
                                                process_archive_queue.py
                                                  └─ run_archive_capture.py
                                                       ├─ discover_capture_seeds
                                                       ├─ Browsertrix  → WACZ  ◄── canonical
                                                       ├─ Playwright   → DOM, screenshots,
                                                       │                 network summary,
                                                       │                 browser state names
                                                       ├─ SingleFile   → convenience copy
                                                       ├─ sha256 manifest + directory digest
                                                       └─ validate
                                                build_public_archive_index.py
                                                  └─ data/archive_public/  ──► Git
```

Two facts define the design:

1. **The WACZ is the canonical artifact.** SingleFile HTML and standalone
   screenshots are secondary representations. They are convenient, they are not
   a replacement, and no code path treats them as one. A capture whose WACZ is
   missing or corrupt is `invalid` no matter how good its screenshots are.
2. **Raw material never enters Git.** It lives only under `$ARCHIVE_ROOT`, on a
   verified external volume by default, or on this Mac's own disk when that is
   explicitly authorized. Either way it is outside every Git working tree, and
   no mode will place a corpus inside one.

### Tool pinning

| Tool | Pin | Recorded per capture |
|---|---|---|
| Browsertrix Crawler | `webrecorder/browsertrix-crawler:1.12.4`, run **by digest** | image, tag, digest, reference |
| SingleFile CLI | npm `single-file-cli@2.0.83` (or a digest-pinned image) | version or digest |
| Playwright | installed version + resolved browser build | both |

Preflight resolves the tag to a digest and the crawl runs against
`webrecorder/browsertrix-crawler@sha256:…`. A tag is a mutable pointer; a
capture that recorded only `:1.12.4` could not prove which bytes produced it.
Configuration validation rejects the `latest` tag outright.

---

## Threat model

What this subsystem defends against, and what it does not.

### Defended

| Risk | Control |
|---|---|
| Raw archival data committed to a public repo | Storage boundary refuses any root inside any Git repo or worktree, in *every* mode; narrow `.gitignore`; public export is a field allowlist; secret scan gates the export; validator fails a capture located inside the repo |
| Credentials or tokens published | Only allowlisted fields reach `data/archive_public/`; network summaries are built field-by-field so headers and bodies cannot leak by omission; browser state records **names** only; secret scan as backstop |
| Operator de-anonymization | No username, no raw hostname (a truncated hash instead), no absolute paths in public output; validator fails on absolute-path leakage |
| Writing a multi-GB corpus to the boot disk **unintentionally** | `ARCHIVE_ROOT` under `/Volumes` must pass symlink resolution and `diskutil` `Internal=false`; a non-`/Volumes` path is refused unless local storage is *explicitly* authorized, and then only after every guard in [Authorized local storage](#authorized-local-storage) passes |
| An authorized local corpus landing somewhere replicated or committable | Refused if inside any Git repo or worktree, inside Desktop/Downloads/Documents/Library, iCloud-synchronized, a symlink at any level, or outside `$HOME` |
| Silent fallback when the disk is missing | There is no fallback. Every command fails closed; the scheduled path exits 0 with a SKIP line |
| Overwriting earlier evidence | Capture directories are created with `exist_ok=False`; manifests and tombstones refuse to overwrite; retries get new capture ids |
| Undetected corruption or tampering | Per-file SHA256 plus a content-only directory digest; the validator detects modified, missing, and post-hoc-added files, and catches a manifest edited to match tampered bytes |
| Path traversal / symlink escape | Every identifier is validated as a single safe path component; symlinks pointing outside a capture fail manifest generation and validation |
| Accidental interaction with a live service | No form submission, no account creation, no logout, no purchases, no authenticated areas; scope is per-page, one worker, bounded page and time limits |
| Credential leakage *into* a capture | Fresh unauthenticated browser contexts; no saved profile, no cookies, no API keys; `NPM_TOKEN`/`GITHUB_TOKEN` and similar are stripped from the SingleFile subprocess environment |

### Not defended

- **The manifest is not notarization.** It detects corruption and modification
  by anyone who is not deliberately rewriting the manifest too — and the
  directory digest catches that as well. But whoever controls the disk controls
  both. Real tamper-evidence needs an external anchor: an offsite copy, a
  third-party timestamp, or publishing digests (which the public index does, and
  Git history then dates them — see the caveat below).
- **A single vantage point.** Everything here is what one machine on one network
  saw. Geo-blocking, CDN behaviour, and A/B variation are invisible.
- **A hostile crawl target.** A site can serve different content to Browsertrix
  than to a browser. The capture records what was served to *this* crawler.
- **Disk failure.** One external volume is one copy. Backups are the operator's
  responsibility; see [Retention policy](#retention-policy).

> **Git history alone does not make raw evidence immutable.** It is worth being
> precise about this. Committing digests to Git means a later change to a
> published digest is visible in history — but Git history can be rewritten and
> force-pushed, and, more importantly, *the raw material is not in Git at all*.
> Git dates a claim about a capture. It does not preserve the capture, and it
> cannot prove the bytes on the external disk were never touched. Treat the
> manifest as an integrity check, not a chain of custody.

---

## Why GitHub does not store WACZ

Four independent reasons, any one of which would be sufficient:

1. **Size.** A WACZ per service per month across ~1,200 tracked services is
   hundreds of gigabytes per year. This exceeds what GitHub is for, and would
   make the repository unusable to clone.
2. **Sensitivity.** A WACZ preserves what the browser observed, including
   response headers, `Set-Cookie` values, session tokens issued to the crawler,
   and any personal data the site happened to render. That is appropriate to
   keep as local research data under access control. It is not appropriate to
   publish to the world, permanently, in a public repository.
3. **Third-party content.** The archives contain other people's copyrighted
   pages, captured for research. Local retention for scholarship is a very
   different posture from republication.
4. **Irrevocability.** A public Git repository is effectively append-only to the
   internet: forks, mirrors, and caches survive deletion. A mistake cannot be
   taken back.

What Git *does* store is the sanitized index: which service was captured, when,
why, how big the WACZ was, its SHA256, the capture-directory digest, the tool
digests, and whether validation passed. That is enough for anyone to cite a
capture and to verify a copy they were given, without holding the material.

---

## The three layers: raw, derived, classification

| Layer | Location | Contents | Mutability |
|---|---|---|---|
| **Raw** | `$ARCHIVE_ROOT/corpus/**/raw/` | WACZ, WARC, CDX indexes, crawl logs, pages JSONL, rendered DOM, screenshots, SingleFile HTML | Append-only. Never regenerated in place. Sensitive. |
| **Derived** | `$ARCHIVE_ROOT/corpus/**/{manifests,validation,config}/`, `capture.json`, network summaries, browser-state names | Machine-generated from raw: hashes, validation reports, reduced observations | Written once when the capture is sealed. Validation reports may be re-derived alongside, never replacing. |
| **Public / classification** | `data/archive_public/` (in Git) | Sanitized index rows, tombstone rows, manifest summaries | Regenerated in full from the corpus by an explicit command. A pure function of the raw layer. |

The classification layer of the wider project — lineage, operator attribution,
site categorization in `results/` and `data/` — is **not touched by this
subsystem**. Nothing here writes to the existing inventories, monitor results,
or classifications. It reads them.

### Local corpus layout

```
$ARCHIVE_ROOT/
  corpus/
    <service_id>/
      site.json                    identity + the exact inventory row and its SHA256
      discovery/
        discovery_evidence.jsonl   append-only: why each capture was scheduled
      captures/
        <capture_id>/
          capture.json
          raw/
            browsertrix/collections/<collection>/
              <collection>.wacz    ◄── canonical artifact
              archive/             WARC (page, screenshot, and text records)
              indexes/             CDXJ
              logs/                crawl logs (JSONL)
              pages/               pages.jsonl, extraPages.jsonl
            rendered/
              final_dom.html       + final_dom_NN-<type>.html per extra page
              singlefile.html      + singlefile_NN.html
              screenshots/         viewport.png, fullpage.png (+ per page)
              network_summary.jsonl
              browser_state_names.json
          config/
            effective_archive_config.json
            browsertrix_config.yaml
            seeds.txt
            environment.json
          manifests/
            sha256_manifest.json
            sha256sums.txt
          validation/
            validation.json
            browsertrix_exit.json
      tombstones/
        <timestamp>.json
  operational/
    queue/  logs/  locks/
  public-export/
```

`service_id` is `<sanitized-host>_<8 hex of sha256(host)>`. **Identity is
host-level.** `api.example.com` and `example.com` are different services and are
never merged by eTLD+1 — that would destroy exactly the distinction this project
tracks. The hash suffix is load-bearing: `a-b.example.com` and `a.b.example.com`
both sanitize to `a-b-example-com`, and without it they would share a directory.

`capture_id` is `<YYYYMMDDTHHMMSSZ>_<service_id>_<12 hex>`, where the hash covers
the service, the sorted seeds, the effective config hash, and the timestamp.

---

## Storage modes

Three modes, each of which has to be asked for. The mode is decided by the
*path*, not by preference: a `/Volumes` path is always evaluated as an external
volume, so authorizing local storage can never weaken the external checks.

| Mode | When | How it is enabled |
|---|---|---|
| `external_volume` | **Recommended default.** `ARCHIVE_ROOT` is under `/Volumes` and `diskutil` confirms the backing volume is external and writable. | Nothing extra. |
| `explicitly_authorized_local` | Corpus on this Mac's own disk. | `--allow-local-storage`, **or** `[storage] allow_local_storage = true`, **or** `ARCHIVE_ALLOW_LOCAL_STORAGE=1` |
| `test_only` | Unit tests and the synthetic smoke test, against a scratch directory. | `--test-only-allow-nonexternal` **and** `ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL=1` |

The mode is recorded in every `capture.json` as `storage_mode` and published in
`data/archive_public/captures.csv`. The archive root **path** is never recorded
in either — it would carry the operator's username, and it is not a property of
the capture anyway, since a corpus can be migrated between disks without
invalidating anything.

### Why external is still the recommendation

An external volume can be unmounted, shelved, and physically separated from the
laptop that made it. A local corpus shares the fate of the machine: one theft,
one disk failure, one wipe-and-reinstall and the primary evidence is gone. It
also sits in the same home directory as the Git repository it must never enter,
which is why the local guards are stricter than the external ones.

Local storage is a reasonable choice when no external disk is available and the
alternative is *not capturing at all* — a corpus on the internal disk is far more
valuable than a site that vanished before anyone archived it. Treat it as the
working copy and back it up.

---

## External disk setup

In the default mode the subsystem refuses to write captures anywhere except a
volume `diskutil` confirms is external and writable.

1. Attach the disk. Give it a distinctive name (`ResearchArchive`, not
   `Untitled`) — if two writable external volumes are mounted, selection is
   ambiguous and the subsystem refuses to guess rather than scattering a
   longitudinal corpus across media.
2. Format it case-sensitive APFS if you can. Case-insensitive filesystems can
   collide two hosts that differ only in case; the `service_id` hash suffix
   already prevents corpus-level collisions, but case sensitivity avoids
   surprises inside WACZ payloads.
3. Export the variable:

```bash
export ARCHIVE_ROOT=/Volumes/<external-volume>/LLM-APIgateways-corpus
```

Put it in your shell profile so scheduled and interactive runs agree.

4. Verify:

```bash
python3 archive/scripts/archive_preflight.py
```

Exit 0 means real captures are permitted. Exit 1 means they are not, and the
output says why.

### What is rejected, and why

| `ARCHIVE_ROOT` | Result |
|---|---|
| unset | Refused. There is no default. |
| `/Volumes/Macintosh HD/corpus` | Refused: resolves through a symlink to `/`. This is the internal disk. |
| `/Volumes/NoSuchDisk/corpus` | Refused: backed by the root filesystem mount. |
| `~/corpus` **without** `--allow-local-storage` | Refused: not on an external volume, and local storage is not authorized. |
| `/tmp/corpus` **with** `--allow-local-storage` | Refused: not under the home directory. Authorization is not a bypass. |
| anywhere inside a Git repository or worktree | Refused **in every mode**, including tests and authorized local storage. |
| a verified external writable volume | Accepted → `external_volume`. |
| an authorized local root that passes every guard | Accepted → `explicitly_authorized_local`. |

There is no fallback. A missing disk is an error, never a quiet redirect — and
enabling local storage does not change that, it only makes a second explicit
destination available.

---

## Authorized local storage

Keeping the corpus on the MacBook's own disk is supported, opt-in, and guarded.

### Enable it

```bash
export ARCHIVE_ROOT=$HOME/LLM-APIgateways-corpus
python3 archive/scripts/archive_preflight.py --allow-local-storage
```

Any one of these three authorizes it, and all three default to off — silence is
never authorization:

| Signal | Scope | Use for |
|---|---|---|
| `--allow-local-storage` | one invocation | interactive runs |
| `[storage] allow_local_storage = true` in `archive/config/archive.toml` | persistent | a machine that has no external disk |
| `ARCHIVE_ALLOW_LOCAL_STORAGE=1` | environment | launchd jobs, where there is no place to put a flag |

`ARCHIVE_ROOT` still has to be set explicitly. Authorization permits a local
path; it never picks one for you. The documented default is
`$HOME/LLM-APIgateways-corpus`.

> The default is expressed relative to `$HOME` rather than written out as an
> absolute path. This repository is public, and a literal `/Users/<name>/…` in
> committed source would publish the operator's account name in every clone. A
> test enforces that no shipped source file contains one.

### What a local root must satisfy

Every one of these is checked, and all failures are reported at once so they can
be fixed in a single pass:

| Guard | Why |
|---|---|
| Outside **every** Git repository and worktree | The whole point of the storage boundary. Checked by walking up for a `.git` entry — as a directory *and* as a file, since a linked worktree uses a file — plus `git rev-parse --show-toplevel` as a cross-check. |
| Outside the project's own repositories | The monitor and archive working trees are refused by name as well. |
| Not inside Desktop, Downloads, Documents, Library, Movies, Music, Pictures, Public, Applications | The first three replicate to iCloud; the rest are managed by macOS. |
| Not iCloud-synchronized | Detected three ways: literally under `Library/Mobile Documents`; under Desktop/Documents while "Desktop & Documents Folders" sync is on (where the paths *look* normal but the contents replicate); or a directory containing `.icloud` placeholder stubs. Uploading gigabytes of third-party page captures to Apple would be a serious mistake. |
| Not a symlink, at the root **or any ancestor** | An ancestor link can be repointed after authorization, silently relocating the corpus. |
| Under the home directory | So an authorized flag cannot aim a corpus at a system directory. |
| Writable | Probed by actually writing a file, not by reading a permission bit. |
| At least `safety.min_free_bytes` free (default 5 GiB) | A capture that runs out of disk halfway produces a truncated WACZ. |

Preflight reports how the default local root would fare whenever local storage
is authorized, so problems surface before you point `ARCHIVE_ROOT` at it.

### What local storage costs you

Everything in [Retention policy](#retention-policy) applies with more force. The
corpus now shares the fate of one machine, and macOS backup tooling is not aware
that these files are irreplaceable. Back the corpus up to a second disk and
verify it with the digest procedure in
[Migrating the corpus](#migrating-the-corpus-to-another-disk) — the same
procedure works for verifying a backup, not just a migration.

---

## Commands

All commands are run from the repository root.

### Preflight

```bash
python3 archive/scripts/archive_preflight.py
python3 archive/scripts/archive_preflight.py --allow-local-storage   # local corpus
```

Verifies the storage boundary, resolves and pins the Docker image digests,
checks Playwright and SingleFile, and confirms the `.gitignore` rules. Add
`--json` for machine-readable output.

### Plan the queue (dry run)

```bash
python3 archive/scripts/plan_archive_queue.py --dry-run --max-sites 10
```

Reads `results/monitor_results.csv` and the sanitized public capture index —
**not** the corpus — so this works with the external disk unplugged. Ordering is
deterministic: `(priority, service_id)`.

Trigger reasons, highest priority first: `tombstone_evidence`,
`status_transition`, `reappearance`, `first_capture`, `final_url_change`,
`homepage_hash_change`, `title_change`, `retry_failure`, `monthly_interval`.

Useful flags: `--service-id`, `--domain`, `--reason`, `--max-sites`,
`--monthly-days`, `--retry-failures`.

### Capture one service

```bash
python3 archive/scripts/run_archive_capture.py --domain example.com --reason manual
python3 archive/scripts/run_archive_capture.py --domain example.com --allow-local-storage
```

`--allow-local-storage` is accepted by every command that resolves storage.
Add `--dry-run` to see the seeds without writing anything, or `--max-seeds 3` to
tighten the cap. Storage is verified **before** the first request to the target,
so a missing disk never causes pointless traffic against someone else's server.

### Inspect seeds only

```bash
python3 archive/scripts/discover_capture_seeds.py --domain example.com
```

### Process the queue

```bash
python3 archive/scripts/process_archive_queue.py --max-sites 5
python3 archive/scripts/process_archive_queue.py --resume
python3 archive/scripts/process_archive_queue.py --dry-run
```

Lock-protected, bounded concurrency (default 1), per-service cooldown. A service
that fails does not abort the run — the remaining entries are independent
observations.

### Validate

```bash
python3 archive/scripts/validate_archive_capture.py --all
python3 archive/scripts/validate_archive_capture.py --capture-dir "$ARCHIVE_ROOT/corpus/<sid>/captures/<cid>"
python3 archive/scripts/validate_archive_capture.py --all --no-write --json
```

### Export public metadata

```bash
python3 archive/scripts/build_public_archive_index.py
```

Rebuilds `data/archive_public/` from the corpus and runs the secret scan; a
non-clean scan fails the command. To scan without the disk attached:

```bash
python3 archive/scripts/build_public_archive_index.py --scan-only
```

---

## Replaying a WACZ

A WACZ is a self-contained, standards-based ZIP. Nothing in this subsystem is
needed to read one.

**ReplayWeb.page (no upload).** Open <https://replayweb.page>, drag the `.wacz`
in. It is a client-side application: the file is loaded in your browser and is
**not** uploaded to a server. This matters — a research WACZ may contain
sensitive material, and it should not be handed to a third party.

**Local replay, fully offline:**

```bash
pip install wabac
wb-manager init archive-replay
# or serve directly with the standalone replay server:
npx @webrecorder/wabac-cli serve "$ARCHIVE_ROOT/corpus/<sid>/captures/<cid>/raw/browsertrix/collections/<collection>/<collection>.wacz"
```

**Inspect without replaying:**

```bash
CAP="$ARCHIVE_ROOT/corpus/<sid>/captures/<cid>"
WACZ=$(find "$CAP" -name '*.wacz')
unzip -l "$WACZ"                              # members
unzip -p "$WACZ" datapackage.json | python3 -m json.tool
unzip -p "$WACZ" pages/pages.jsonl            # captured pages + titles
unzip -p "$WACZ" indexes/index.cdxj | cut -d' ' -f1   # every archived URL
```

`urn:view:` and `urn:fullPage:` entries in the CDXJ are the in-WACZ screenshots;
`urn:text:` entries are the extracted page text.

---

## Behaviour when the disk is unavailable

| Command | Behaviour |
|---|---|
| `archive_preflight.py` | Reports the problem, exit 1. |
| `plan_archive_queue.py --dry-run` | **Works.** Planning reads the repo, not the disk. |
| `plan_archive_queue.py` (writing) | Fails closed, exit 2. |
| `run_archive_capture.py --dry-run` | Works; contacts the site for seed discovery only. |
| `run_archive_capture.py` | Fails closed **before** contacting the target, exit 2. |
| `process_archive_queue.py` | Fails closed, exit 2. |
| `process_archive_queue.py --scheduled` | Prints one `SKIP` line, **exit 0**. |
| `validate_archive_capture.py --capture-dir <path>` | Works on any path you can read. |
| `build_public_archive_index.py --scan-only` | Works: scans the existing export in Git. |

The `--scheduled` distinction exists so an unplugged disk is a no-op for
launchd rather than a recurring failure notification — while still making it
impossible to fall back to internal storage *implicitly*. With an authorized
local corpus these rows do not apply: the storage is always present, which is
convenient and is also exactly the property that makes an external volume
safer.

---

## Recovering from an interrupted capture

A capture killed mid-run (Ctrl-C, sleep, disk eject, power loss) leaves a
directory with no manifest, or with artifacts but no `validation.json`.

**Do not delete it, and do not resume into it.** Both would violate the
append-only rule, and the partial directory is itself evidence of what happened.

1. Identify it:
   ```bash
   find "$ARCHIVE_ROOT/corpus" -maxdepth 3 -name 'captures' -type d \
     -exec sh -c 'for d in "$1"/*/; do [ -f "$d/manifests/sha256_manifest.json" ] || echo "$d"; done' _ {} \;
   ```
2. Seal it so it can be cited as a partial observation:
   ```bash
   python3 - <<'PY'
   import sys; sys.path.insert(0, "archive")
   from archivelib.manifest import generate_manifest
   from archivelib.validate import validate_capture
   cap = "<the capture directory>"
   generate_manifest(cap, capture_id="<cid>", service_id="<sid>")
   print(validate_capture(cap)["status"])
   PY
   ```
   It will validate as `invalid` if the WACZ is missing or truncated. That is the
   correct outcome: the record now says "this capture was interrupted."
3. Retry, which creates a **new** capture id:
   ```bash
   python3 archive/scripts/run_archive_capture.py --domain example.com --reason retry_failure
   ```
4. If a stale lock blocks the retry, inspect it before removing it:
   ```bash
   cat "$ARCHIVE_ROOT/operational/locks/"*.lock
   ```
   Locks record pid, machine, and purpose, and are auto-broken when the owning
   process is provably gone or the lock is older than six hours.

---

## Immutability policy

Once a capture is **sealed** — the moment `manifests/sha256_manifest.json` is
written — nothing inside it is ever modified.

- Raw files are never regenerated in place.
- Previous captures are never updated or deleted.
- Failed, blocked, challenge-page, and dead-site captures are **kept**. "We tried
  on this date and this is what we saw" is exactly the evidence a longitudinal
  study needs; deleting failures would bias the corpus toward sites that were
  healthy and reachable.
- A screenshot is never replaced. Replacing one is detectable and fails
  validation.
- Retries create new capture ids. Nothing is ever resumed into an existing
  capture directory.
- Tombstones are immutable. A service that reappears gets a *new* record; the old
  one stays, because it remains true that the service looked dead then.
- Discovery evidence is append-only JSONL.

Two deliberate exceptions, both before or outside the seal:

1. **Crawler scratch pruning.** Browsertrix leaves its throwaway Chrome
   user-data directory inside the collection — about 50 MB per crawl of bundled
   extension assets plus Cookies/History/Local Storage databases. It contains no
   archived site content (every byte the site served is in the WARC) and it *is*
   the "Browsertrix profile" that must never leave the machine. It is removed
   **before** the manifest is generated, and exactly what was removed is recorded
   in `capture.json` under `pruned_crawler_scratch`. In the smoke test this took
   a capture from 289 files / 53 MB to 36 files / 444 KB with an identical WACZ.
   The validator fails any sealed capture that still contains a browser profile.
2. **Validation reports.** Re-validating a ten-year-old capture must be possible
   without invalidating its manifest, so `validation/validation*.json` is
   excluded from the manifest and a re-run writes a timestamped sibling rather
   than replacing the original.

### macOS metadata is allowlisted, nothing else

macOS injects `.DS_Store` (Finder) and `._*` (AppleDouble) sidecar files into any
directory it browses, copies, or indexes. These are **not** archived content, so
they are ignored — by exact basename only — when generating manifests, computing
the directory digest, checking for post-manifest additions, and validating.

This allowlist is deliberately narrow and is **not** a "hidden file" rule:
`.env`, `.secret`, a hidden `.json`, a hidden `.html`, and any other unexpected
file are still fully manifested, and adding, modifying, or removing any of them
still fails validation. A `.DS_Store` sitting next to a smuggled `.env` does not
hide the `.env`. Storage initialization also drops a best-effort
`$ARCHIVE_ROOT/.metadata_never_index` marker to discourage Spotlight from
indexing the corpus, but integrity does **not** depend on it — the allowlist is
the fix.

---

## Retention policy

- **Raw captures: keep indefinitely.** They are the primary evidence and cannot
  be recreated — the sites change and disappear, which is the whole point.
- **Failed and dead-site captures: keep indefinitely.** Same reason; deleting
  them would bias the corpus.
- **Nothing is auto-deleted.** No command in this subsystem removes a real
  capture. The only deletion path is the smoke test cleaning up its own
  synthetic output, and it refuses to run against a real corpus at all.
- **Operational logs and queue files** under `operational/` are disposable and
  may be pruned by hand; they are not evidence.
- **Backups are your responsibility.** One external volume is one copy. Use a
  second disk and verify it with the digest procedure below. If storage becomes
  a constraint, prefer adding disks over deleting captures; if you must reduce,
  drop the *rendered* secondary representations (screenshots, SingleFile) and
  keep the WACZ, never the reverse.

---

## Tombstone semantics

A tombstone records that a service **appears** to have ended. It is evidence
with a confidence level, not a death certificate.

The monitor sees the web from one vantage point every six hours. A timeout can
mean the service is gone, or that a CDN dropped one request, or that this
machine's network was briefly unhappy. So:

- **One transient failure never produces a tombstone.** Emission requires both a
  minimum number of consecutive non-live observations (default 3) *and* a
  minimum elapsed span (default 48h).
- **Confidence is explicit**: `insufficient` → `provisional` → `probable` →
  `high`. `insufficient` means do not cite this as termination.
- **A Cloudflare challenge is never evidence of death.** It proves the origin is
  answering. Such runs are classified `unknown_not_live` with confidence
  `insufficient` and emit nothing, no matter how long they persist.
- **Directly observed states outrank inferred ones.** An explicit "service
  stopped" notice, a for-sale page, or an offsite redirect is testimony; a pile
  of timeouts is circumstantial, and confidence reflects that.
- **A successful request is not proof of life.** A 200 that lands on unrelated
  parking is recorded as `redirects_offsite`, not as the service being alive.

Recorded states: `dns_failure_persistent`, `http_failure_persistent`,
`unreachable_persistent`, `service_stopped`, `parked_or_for_sale`,
`redirects_offsite`, `unavailable_persistent`, `unknown_not_live`.

Every tombstone carries the supporting observations, the count of inconclusive
observations that weaken it, the last successful capture id and WACZ SHA256, and
a mandatory `uncertainty` statement. Thresholds are configurable under
`[tombstone]` in the config.

---

## Sensitive-data handling

### What the raw corpus may contain

Treat the entire WACZ and all raw browser output as **sensitive research data**.
It preserves what the browser observed: response headers, `Set-Cookie` values,
session tokens issued to the crawler, and whatever the pages rendered. Keep the
disk encrypted (FileVault or APFS encryption) and do not share raw captures
casually.

### What is never collected

No credentials are ever supplied. Fresh unauthenticated browser contexts, no
saved profiles, no cookies, no API keys, no attempt to bypass authentication. No
form submission, no account creation, no purchases, no logout links, no
authenticated areas. Config validation rejects turning any of that on.

### What may leave the disk

| Data | Local raw | Public export |
|---|---|---|
| WACZ / WARC | yes | **never** |
| HTML, response bodies | yes | **never** |
| Response headers | yes (inside WACZ) | **never** |
| Cookie / storage **values** | yes (inside WACZ) | **never** |
| Cookie / storage **names** | yes | **never** (local-only, `derived_restricted`) |
| Screenshots, SingleFile HTML | yes | **never** |
| Crawl logs | yes | **never** unless separately sanitized |
| URL with query string | yes | query **stripped** |
| Absolute local paths | yes, normalized | **never** |
| Archive root path | not recorded at all | **never** — only `storage_mode` |
| Hashes, sizes, timestamps, tool digests, validation status | yes | yes |

The public export is an **allowlist**: each row is assembled field by field in
`archive/archivelib/publicexport.py`. No dict from the corpus is ever copied
wholesale, so a new key in `capture.json` cannot leak by accident. The secret
scan is a backstop, not the primary control.

Every manifest entry carries a sensitivity class: `raw_sensitive` (never leaves
the volume), `derived_restricted` (local-only), `metadata_public_ok`. Unknown
file types default to `raw_sensitive`.

---

## Verifying SHA256

**One WACZ:**

```bash
CAP="$ARCHIVE_ROOT/corpus/<sid>/captures/<cid>"
shasum -a 256 "$CAP"/raw/browsertrix/collections/*/*.wacz
```

Compare against `wacz.sha256` in `capture.json`, or `wacz_sha256` in
`data/archive_public/captures.csv`.

**Every file in a capture:**

```bash
cd "$CAP" && shasum -a 256 -c manifests/sha256sums.txt
```

**The whole capture, including detecting added or removed files:**

```bash
python3 archive/scripts/validate_archive_capture.py --capture-dir "$CAP"
```

**The capture-directory digest**, which is what the public index publishes:

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, "archive")
from archivelib.manifest import build_entries, capture_directory_digest
cap = "<the capture directory>"
print(capture_directory_digest(build_entries(cap)))
PY
```

The digest is computed over `(path, size_bytes, sha256)` triples only —
deliberately excluding timestamps — so it is a function of content alone and
survives a faithful copy to different media. It also catches a manifest that was
edited to match tampered bytes, because the per-file hashes would then agree
while the recorded digest would not.

---

## Inspecting an old capture without modifying it

Reading never modifies a capture, but two habits keep it that way:

```bash
CAP="$ARCHIVE_ROOT/corpus/<sid>/captures/<cid>"

# Metadata
python3 -m json.tool "$CAP/capture.json"
python3 -m json.tool "$CAP/validation/validation.json"

# Archived URLs, without unpacking
unzip -p "$CAP"/raw/browsertrix/collections/*/*.wacz indexes/index.cdxj | cut -d' ' -f1

# Screenshots and DOM — open read-only, never edit in place
open -a Preview "$CAP/raw/rendered/screenshots/fullpage.png"
```

1. **Never unzip a WACZ into its own capture directory.** New files there are
   detected as added-after-manifest and the capture becomes `invalid`. Extract
   to a scratch directory instead:
   ```bash
   mkdir -p /tmp/wacz-inspect && unzip "$CAP"/raw/browsertrix/collections/*/*.wacz -d /tmp/wacz-inspect
   ```
2. **Re-validate with `--no-write`** when you only want the verdict:
   ```bash
   python3 archive/scripts/validate_archive_capture.py --capture-dir "$CAP" --no-write
   ```

To make this structural, mark old captures read-only once you are confident:

```bash
chmod -R a-w "$CAP"
```

---

## Migrating the corpus to another disk

The capture-directory digest is content-only, so a correct copy is provably
identical.

1. Record the current digests **before** copying:
   ```bash
   python3 archive/scripts/validate_archive_capture.py --all --no-write --json > /tmp/before.json
   ```
2. Copy, preserving everything. `rsync -a` keeps permissions, times, and
   symlinks; `--checksum` verifies content rather than trusting size+mtime:
   ```bash
   rsync -a --checksum --progress "$ARCHIVE_ROOT/" /Volumes/<new-volume>/LLM-APIgateways-corpus/
   ```
3. Point the variable at the new disk:
   ```bash
   export ARCHIVE_ROOT=/Volumes/<new-volume>/LLM-APIgateways-corpus
   ```
4. Verify the copy independently:
   ```bash
   python3 archive/scripts/archive_preflight.py
   python3 archive/scripts/validate_archive_capture.py --all --no-write --json > /tmp/after.json
   python3 - <<'PY'
   import json
   before = {r["capture_dir"]: r["capture_directory_digest"] for r in json.load(open("/tmp/before.json"))["reports"]}
   after  = {r["capture_dir"]: r["capture_directory_digest"] for r in json.load(open("/tmp/after.json"))["reports"]}
   missing = sorted(set(before) - set(after))
   changed = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
   print(f"{len(before)} before, {len(after)} after")
   print(f"missing: {missing or 'none'}")
   print(f"digest changed: {changed or 'none'}")
   PY
   ```
   Both lists must be empty. A changed digest means the copy is not faithful —
   investigate before retiring the old disk.
5. Rebuild the public index and confirm it is unchanged (it should be: the digests
   are the same):
   ```bash
   python3 archive/scripts/build_public_archive_index.py
   git diff --stat data/archive_public/
   ```
6. **Keep the old disk until step 4 passes.** Do not reformat it first.

Digests are independent of the mount point because nothing in the digest input
is an absolute path — this is why `corpus_relpath` is relative everywhere.

---

## Scheduling with launchd

Local scheduling only. There is deliberately **no GitHub Actions WACZ workflow**:
CI has no external disk, and giving a hosted runner the job would mean either
storing WACZ in the repo or shipping it somewhere else. Neither is acceptable.

```bash
python3 archive/scripts/install_launchd_template.py --out ./edu.drexel.llm-api-archive.plist \
  --archive-root "$ARCHIVE_ROOT" --hour 4 --minute 0 --max-sites 5
```

This **renders only**. It never writes to `~/Library/LaunchAgents` and never
calls `launchctl` — refusing both, in fact. After reading the file:

```bash
cp ./edu.drexel.llm-api-archive.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/edu.drexel.llm-api-archive.plist
```

To stop it:

```bash
launchctl unload ~/Library/LaunchAgents/edu.drexel.llm-api-archive.plist
```

If the corpus lives on the internal disk, add `ARCHIVE_ALLOW_LOCAL_STORAGE=1`
to the plist's `EnvironmentVariables` — a launchd job has nowhere to put a CLI
flag, and the job must be authorized as explicitly as an interactive run.

The job runs `process_archive_queue.py --scheduled`, which exits 0 with a SKIP
line when the volume is absent. `RunAtLoad` is false so reattaching the disk does
not trigger a backlog burst. The job does **not** run the public export and does
not touch Git; publishing stays a manual, reviewed step.

---

## Testing

```bash
python3 -m pytest archive/tests/ -q
```

321 tests, no network access, no dependency on any live third-party site. They
run against a synthetic fixture site served from `archive/tests/fixtures/site/`
and a scratch `ARCHIVE_ROOT` gated by an explicit test-only opt-in.

The end-to-end smoke test needs Docker and is a script, not a pytest test:

```bash
export ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL=1
export ARCHIVE_ROOT=/some/scratch/dir
python3 archive/tests/smoke_browsertrix.py
```

It runs a real Browsertrix crawl against the local fixture, produces a real WACZ,
renders with Playwright and SingleFile, hashes, validates, exports, and scans. It
refuses to run against a real external corpus.

### The test-only storage opt-in

Non-external storage requires **two** independent signals: the environment
variable `ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL=1` *and* the
`--test-only-allow-nonexternal` flag. A stray flag alone cannot redirect real
captures off the external disk, and neither signal permits a root inside the Git
repository.

---

## Seed discovery on unreachable hosts

Discovery always fetches the **canonical homepage first**, with a per-request
timeout set by `seeds.request_timeout_seconds` (default **10 s**). What happens
next depends on whether the homepage answered:

- **Network-layer failure** — DNS failure, connection timeout, connection
  refused, TLS handshake failure, network unreachable, or a read timeout with no
  HTTP response — the host is unreachable, so the homepage is retained as the
  **sole seed** and no known-path or API probing happens. `capture.json` records
  `seed_discovery.probing_skipped` and the `probing_skipped_reason`.
- **Any HTTP response** — including 404, 502, 503, 520, challenge pages, and
  redirects — the server is answering, so bounded discovery proceeds as normal.

This matters because the queue's highest-priority trigger (`tombstone_evidence`)
selects dying services. Before this bound, a silently-hanging host cost ~13
sequential probes each waiting the full timeout (~90 s+); now it costs one
homepage timeout. It is purely an efficiency and politeness change — a dead
host still produces a complete, manifested, retained `failed_no_wacz` capture.

---

## Capture eligibility (exclusions register)

The discovery inventory contains false positives — GitHub-codesearch matches an
upstream provider, an unrelated platform, a blog, or payment infrastructure that
merely mentions the one-api framework. Rather than edit the authoritative
inventories or the historical monitor results, eligibility decisions live in a
**non-destructive, versioned register**:

```
data/archive_config/capture_exclusions.csv
  domain, status, reason, evidence, reviewed_at, review_version
```

- `status = excluded` — a *confirmed* false positive. The planner holds it out
  of the queue and reports it under `excluded`.
- `status = questionable` — an uncertain case. The planner keeps it selectable
  but flags it (`⚑QUESTIONABLE`) so a human decides before capture.

The planner auto-loads the register when present; `--exclusions-file <path>`
points at another one and `--no-exclusions` ignores it. Two principles govern
what gets excluded:

1. **Eligibility is a judgment about the entity, not the fingerprint.** A
   discovery endpoint signal (running one-api, answering `/v1/models`) is not
   proof of study eligibility — an upstream provider answers `/v1/models` too
   (`tokenhub.tencentcloudmaas.com` is a Tencent Cloud MaaS endpoint, still
   out of scope). So a fingerprint never justifies *inclusion*, and only clearly
   confirmed non-relays are `excluded`.
2. **Aggregators are in scope by role.** The study defines `aggregator` as a
   `site_role`, so global independent aggregators (e.g. `openrouter.com`) are
   marked `questionable`, never auto-excluded.

### Monitor sentinels

`monitor_results.csv` contains the literal sentinel `hvoy_removed` in its
`domain` column to mark hvoy-delisted services. It is not a real host, so it is
dropped at **read time** (`MONITOR_SENTINELS`) and never counted as an observed
service or considered for capture. The CSV rows are never edited.

---

## Known limitations

- **macOS only.** Volume verification uses `diskutil`. Porting means replacing
  `archive/archivelib/volumes.py`.
- **Docker required** for Browsertrix. There is no non-container fallback, by
  design: the pinned image is what makes captures reproducible.
- **One vantage point.** No geographic or network diversity.
- **`reports/` is optional.** Browsertrix 1.12.4 does not emit a `reports/`
  directory for these crawl settings; the validator treats it as a warning, not
  an error, and retains it when present.
- **Concurrency is effectively 1.** The flag exists and is bounded, but
  sequential is the supported and tested mode; it is also the polite one.
- **SingleFile downloads via `npx` at capture time** unless a digest-pinned image
  is configured. The version is pinned exactly, but the first run needs network
  access to the npm registry.
- **No external tamper-evidence anchor.** See [Threat model](#threat-model).
