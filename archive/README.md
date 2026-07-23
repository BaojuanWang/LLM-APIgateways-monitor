# `archive/` — local WACZ archival subsystem

Full documentation: [`docs/LOCAL_WACZ_ARCHIVE.md`](../docs/LOCAL_WACZ_ARCHIVE.md)

Captures full WACZ web archives of monitored services to an **external disk**,
keeps them append-only and hash-verified, and publishes only sanitized metadata
to this public repository.

The six-hour GitHub Actions monitor is unchanged and remains the lightweight
change detector. This is the local full-capture layer it triggers.

## Two rules everything else follows from

1. **The WACZ is the canonical artifact.** SingleFile HTML and standalone
   screenshots are secondary representations, never substitutes. A capture with a
   missing or corrupt WACZ is `invalid` however good its screenshots are.
2. **Raw material never enters Git.** It lives only under `$ARCHIVE_ROOT` — on a
   volume `diskutil` confirms is external and writable by default, or on this
   Mac's own disk when explicitly authorized with `--allow-local-storage`. There
   is no fallback: a missing disk is an error, never a quiet redirect, and no
   mode places a corpus inside a Git working tree.

## Storage modes

| Mode | How to get it |
|---|---|
| `external_volume` (recommended default) | `ARCHIVE_ROOT` under `/Volumes` on a verified external disk |
| `explicitly_authorized_local` | `--allow-local-storage`, or `[storage] allow_local_storage = true`, or `ARCHIVE_ALLOW_LOCAL_STORAGE=1` |
| `test_only` | `--test-only-allow-nonexternal` **and** `ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL=1` |

An authorized local root must be outside every Git repository and worktree,
outside Desktop/Downloads/Documents and iCloud, not a symlink at any level,
under `$HOME`, writable, and have enough free space. The mode is recorded per
capture and published; the archive root **path** never is.

## Quick start

```bash
export ARCHIVE_ROOT=/Volumes/<external-volume>/LLM-APIgateways-corpus
# or, to keep the corpus on this Mac:
#   export ARCHIVE_ROOT=$HOME/LLM-APIgateways-corpus
#   ...and pass --allow-local-storage to each command below
python3 archive/scripts/archive_preflight.py                    # verify disk + pin images
python3 archive/scripts/plan_archive_queue.py --dry-run         # works without the disk
python3 archive/scripts/run_archive_capture.py --domain example.com --reason manual
python3 archive/scripts/validate_archive_capture.py --all
python3 archive/scripts/build_public_archive_index.py           # the only writer into Git
```

## Layout

```
archive/
  archivelib/     library: storage boundary, identity, seeds, capture,
                  manifests, validation, tombstones, queue, public export
  config/         archive.example.toml, browsertrix.template.yaml
  schemas/        JSON Schemas for site / capture / tombstone / public index
  scripts/        the CLI entry points listed above
  tests/          249 tests + a synthetic fixture site + a Docker smoke test
  launchd/        plist template (rendered on request; never auto-installed)
```

Public output lives in `data/archive_public/` and is regenerated in full from
the corpus — it is a pure function of the raw layer, never edited by hand.

## Pinned tools

| Tool | Pin |
|---|---|
| Browsertrix Crawler | `webrecorder/browsertrix-crawler:1.12.4`, run by resolved digest |
| SingleFile CLI | npm `single-file-cli@2.0.83` (or a digest-pinned image) |
| Playwright | installed version + resolved browser build, both recorded |

The `latest` tag is rejected by configuration validation.

## Safety properties

Fresh unauthenticated browser contexts; no saved profiles, cookies, or API keys.
No form submission, account creation, purchases, logout, or authenticated areas.
Per-page scope, one worker, at most 8 seeds, bounded page and time limits.
Capture directories are created fail-closed and never overwritten; retries get
new capture ids; failed and dead-site captures are kept as evidence.

## Tests

```bash
python3 -m pytest archive/tests/ -q
```

No network access and no dependency on any live third-party site. The Docker
smoke test is separate:

```bash
ARCHIVE_TEST_ONLY_ALLOW_NONEXTERNAL=1 ARCHIVE_ROOT=/some/scratch \
  python3 archive/tests/smoke_browsertrix.py
```
