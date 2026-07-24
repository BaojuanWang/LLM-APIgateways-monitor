"""SHA256 manifests and the capture-directory digest.

Integrity model:

* Every regular file in a capture directory is hashed after capture completes.
* The manifest records path, size, SHA256, role, sensitivity class, and mtime.
* A single **capture-directory digest** is derived from a canonicalized view of
  the manifest containing only ``(path, size, sha256)`` triples.

The digest deliberately excludes timestamps so it is a function of *content
only*: copy a capture to another disk and the digest must still match. That
property is what makes the migration procedure in the docs verifiable.

Note what this does and does not prove. The manifest detects accidental
corruption, truncation, silent bit-rot, and files added or altered after the
fact. It is not a notarization service: anyone who can rewrite the files can
also rewrite the manifest. External anchoring (offsite copy, third-party
timestamp) is out of scope here and is called out in the documentation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .canonical import canonical_json, read_json, sha256_file, sha256_text, write_json
from .envmeta import utc_now_iso
from .errors import ManifestError
from .paths import assert_no_symlink_escape, iter_capture_files

MANIFEST_RELPATH = "manifests/sha256_manifest.json"
SHASUMS_RELPATH = "manifests/sha256sums.txt"

# Files that cannot appear in the manifest because they are written from it or
# after it. Validation reports are re-derivable at any time from the archived
# bytes, so excluding them costs nothing evidentially and lets a capture be
# re-validated years later without invalidating its manifest.
SELF_EXCLUDED = frozenset({MANIFEST_RELPATH, SHASUMS_RELPATH})
VALIDATION_REPORT_PREFIX = "validation/validation"


def is_excluded(relpath: str) -> bool:
    if relpath in SELF_EXCLUDED:
        return True
    return relpath.startswith(VALIDATION_REPORT_PREFIX) and relpath.endswith(".json")

MANIFEST_VERSION = 1

# Sensitivity classes:
#   raw_sensitive       -> may contain response bodies, headers, credentials.
#                          Never leaves the external volume.
#   derived_restricted  -> machine-derived, already reduced, still local-only.
#   metadata_public_ok  -> safe to summarize into the public export.
SENSITIVITY_CLASSES = ("raw_sensitive", "derived_restricted", "metadata_public_ok")

_ROLE_RULES: tuple[tuple[str, str, str], ...] = (
    # (match kind, pattern, role)
    ("suffix", ".wacz", "wacz"),
    ("suffix", ".warc.gz", "warc"),
    ("suffix", ".warc", "warc"),
    ("suffix", ".cdxj", "cdx_index"),
    ("suffix", ".cdx", "cdx_index"),
    ("suffix", ".idx", "cdx_index"),
)

_ROLE_BY_PATH: tuple[tuple[str, str], ...] = (
    ("raw/browsertrix/collections/", "browsertrix_output"),
    ("raw/rendered/screenshots/", "screenshot"),
    ("raw/rendered/final_dom", "rendered_dom"),
    ("raw/rendered/singlefile", "singlefile"),
    ("raw/rendered/network_summary", "network_summary"),
    ("raw/rendered/browser_state_names", "browser_state_names"),
    ("config/seeds.txt", "seeds"),
    ("config/environment.json", "environment"),
    ("config/effective_archive_config.json", "effective_config"),
    ("config/browsertrix_config.yaml", "browsertrix_config"),
    ("manifests/", "manifest"),
    ("validation/validation.json", "validation"),
    ("validation/browsertrix_exit.json", "exit_status"),
    ("capture.json", "capture_metadata"),
)

_SENSITIVITY_BY_ROLE = {
    "wacz": "raw_sensitive",
    "warc": "raw_sensitive",
    "cdx_index": "raw_sensitive",
    "browsertrix_output": "raw_sensitive",
    "crawl_log": "raw_sensitive",
    "pages_jsonl": "raw_sensitive",
    "rendered_dom": "raw_sensitive",
    "singlefile": "raw_sensitive",
    "screenshot": "raw_sensitive",
    "network_summary": "derived_restricted",
    "browser_state_names": "derived_restricted",
    "seeds": "metadata_public_ok",
    "environment": "derived_restricted",
    "effective_config": "metadata_public_ok",
    "browsertrix_config": "metadata_public_ok",
    "manifest": "derived_restricted",
    "validation": "derived_restricted",
    "exit_status": "derived_restricted",
    "capture_metadata": "derived_restricted",
    "other": "raw_sensitive",  # unknown files are treated as sensitive
}


def classify_role(relpath: str) -> str:
    lowered = relpath.lower()
    for kind, pattern, role in _ROLE_RULES:
        if kind == "suffix" and lowered.endswith(pattern):
            return role
    if "/logs/" in lowered and lowered.endswith((".log", ".jsonl", ".txt")):
        return "crawl_log"
    if "/pages/" in lowered and lowered.endswith(".jsonl"):
        return "pages_jsonl"
    if "/reports/" in lowered:
        return "crawl_report"
    for prefix, role in _ROLE_BY_PATH:
        if lowered.startswith(prefix):
            return role
    return "other"


def classify_sensitivity(role: str) -> str:
    return _SENSITIVITY_BY_ROLE.get(role, "raw_sensitive")


@dataclass
class ManifestEntry:
    path: str
    size_bytes: int
    sha256: str
    role: str
    sensitivity: str
    created_at_utc: str

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "role": self.role,
            "sensitivity": self.sensitivity,
            "created_at_utc": self.created_at_utc,
        }


def _mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_entries(capture_root: Path) -> list[ManifestEntry]:
    capture_root = Path(capture_root)
    entries: list[ManifestEntry] = []
    for file_path in iter_capture_files(capture_root):
        rel = str(file_path.relative_to(capture_root))
        if is_excluded(rel):
            continue
        role = classify_role(rel)
        entries.append(
            ManifestEntry(
                path=rel,
                size_bytes=file_path.stat().st_size,
                sha256=sha256_file(file_path),
                role=role,
                sensitivity=classify_sensitivity(role),
                created_at_utc=_mtime_utc(file_path),
            )
        )
    return sorted(entries, key=lambda e: e.path)


def digest_payload(entries: list[ManifestEntry]) -> list[dict]:
    """Content-only view used for the directory digest.

    Timestamps and classification labels are excluded: they can change without
    the archived bytes changing, and the digest must survive a faithful copy.
    """
    return [{"path": e.path, "size_bytes": e.size_bytes, "sha256": e.sha256} for e in sorted(entries, key=lambda x: x.path)]


def capture_directory_digest(entries: list[ManifestEntry]) -> str:
    payload = {"algorithm": "sha256", "manifest_version": MANIFEST_VERSION, "files": digest_payload(entries)}
    return "sha256:" + sha256_text(canonical_json(payload))


def generate_manifest(capture_root: Path, *, capture_id: str, service_id: str) -> dict:
    """Hash the capture directory and write both manifest files."""
    capture_root = Path(capture_root)
    if not capture_root.is_dir():
        raise ManifestError(f"capture directory does not exist: {capture_root}")

    escapes = assert_no_symlink_escape(capture_root)
    if escapes:
        raise ManifestError(f"symlinks escape the capture directory: {escapes}")

    entries = build_entries(capture_root)
    if not entries:
        raise ManifestError(f"capture directory contains no files: {capture_root}")

    manifest = {
        "schema": "sha256_manifest",
        "manifest_version": MANIFEST_VERSION,
        "algorithm": "sha256",
        "capture_id": capture_id,
        "service_id": service_id,
        "generated_at_utc": utc_now_iso(),
        "file_count": len(entries),
        "total_bytes": sum(e.size_bytes for e in entries),
        "excluded_from_manifest": sorted(SELF_EXCLUDED) + [f"{VALIDATION_REPORT_PREFIX}*.json"],
        "digest_note": (
            "capture_directory_digest is computed over (path, size_bytes, sha256) "
            "triples only, so it is stable across faithful copies of the corpus"
        ),
        "files": [e.as_dict() for e in entries],
        "capture_directory_digest": capture_directory_digest(entries),
    }

    manifest_path = capture_root / MANIFEST_RELPATH
    if manifest_path.exists():
        raise ManifestError(f"manifest already exists and is append-only: {manifest_path}")
    write_json(manifest_path, manifest)

    shasums_path = capture_root / SHASUMS_RELPATH
    lines = [f"{e.sha256}  {e.path}" for e in entries]
    shasums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return manifest


def load_manifest(capture_root: Path) -> dict:
    path = Path(capture_root) / MANIFEST_RELPATH
    if not path.exists():
        raise ManifestError(f"no manifest at {path}")
    return read_json(path)


def verify_manifest(capture_root: Path) -> dict:
    """Re-hash everything and report every discrepancy.

    Distinguishes the three failure shapes that matter: files that vanished,
    files whose bytes changed, and files that appeared after the manifest was
    written (the signature of post-hoc tampering or an interrupted rerun).
    """
    capture_root = Path(capture_root)
    manifest = load_manifest(capture_root)
    recorded = {entry["path"]: entry for entry in manifest.get("files", [])}

    on_disk: dict[str, Path] = {}
    for file_path in iter_capture_files(capture_root):
        rel = str(file_path.relative_to(capture_root))
        if is_excluded(rel):
            continue
        on_disk[rel] = file_path

    missing = sorted(set(recorded) - set(on_disk))
    added = sorted(set(on_disk) - set(recorded))
    mismatched: list[dict] = []
    for rel, entry in recorded.items():
        path = on_disk.get(rel)
        if path is None:
            continue
        actual_size = path.stat().st_size
        actual_hash = sha256_file(path)
        if actual_hash != entry.get("sha256") or actual_size != entry.get("size_bytes"):
            mismatched.append(
                {
                    "path": rel,
                    "expected_sha256": entry.get("sha256"),
                    "actual_sha256": actual_hash,
                    "expected_size": entry.get("size_bytes"),
                    "actual_size": actual_size,
                }
            )

    recomputed_entries = [
        ManifestEntry(
            path=entry["path"],
            size_bytes=entry["size_bytes"],
            sha256=entry["sha256"],
            role=entry.get("role", "other"),
            sensitivity=entry.get("sensitivity", "raw_sensitive"),
            created_at_utc=entry.get("created_at_utc", ""),
        )
        for entry in manifest.get("files", [])
    ]
    expected_digest = capture_directory_digest(recomputed_entries)
    recorded_digest = manifest.get("capture_directory_digest", "")

    symlink_escapes = assert_no_symlink_escape(capture_root)

    return {
        "manifest_path": MANIFEST_RELPATH,
        "file_count": len(recorded),
        "missing_files": missing,
        "added_files": added,
        "hash_mismatches": mismatched,
        "symlink_escapes": symlink_escapes,
        "digest_recorded": recorded_digest,
        "digest_recomputed": expected_digest,
        "digest_matches": recorded_digest == expected_digest,
        "ok": not missing and not added and not mismatched and not symlink_escapes and recorded_digest == expected_digest,
    }


def entry_for_role(manifest: dict, role: str) -> dict | None:
    for entry in manifest.get("files", []):
        if entry.get("role") == role:
            return entry
    return None
