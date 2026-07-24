"""Non-destructive capture-eligibility layer.

The authoritative inventories and ``monitor_results.csv`` are never edited to
remove a site. Instead, a reviewed, versioned register at
``data/archive_config/capture_exclusions.csv`` records eligibility decisions:

* ``excluded``     — a confirmed false positive (an upstream provider, an
                     unrelated platform, a blog/doc host, payment
                     infrastructure). The planner removes these from the capture
                     queue.
* ``questionable`` — an uncertain case that needs a human decision. It is
                     documented and flagged in the plan but **not** removed;
                     it remains selectable.

Eligibility is a study-scope judgment about the *entity*. A discovery endpoint
fingerprint (running one-api, exposing ``/v1/models``) is a discovery signal,
not proof of eligibility — an upstream provider exposes ``/v1/models`` too — so
nothing here treats a fingerprint as grounds for inclusion.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .identity import normalize_host, service_id_for_host

EXCLUSIONS_REL = "data/archive_config/capture_exclusions.csv"
EXCLUSION_FIELDS = ("domain", "status", "reason", "evidence", "reviewed_at", "review_version")

STATUS_EXCLUDED = "excluded"
STATUS_QUESTIONABLE = "questionable"
VALID_STATUSES = frozenset({STATUS_EXCLUDED, STATUS_QUESTIONABLE})


class ExclusionsError(Exception):
    """The exclusions register is missing required columns or is malformed."""


@dataclass
class ExclusionEntry:
    domain: str
    status: str
    reason: str
    evidence: str
    reviewed_at: str
    review_version: str
    service_id: str

    def as_dict(self) -> dict:
        return {
            "domain": self.domain,
            "service_id": self.service_id,
            "status": self.status,
            "reason": self.reason,
            "evidence": self.evidence,
            "reviewed_at": self.reviewed_at,
            "review_version": self.review_version,
        }


@dataclass
class ExclusionSet:
    entries: list[ExclusionEntry]
    source_path: str

    @property
    def excluded(self) -> list[ExclusionEntry]:
        return [e for e in self.entries if e.status == STATUS_EXCLUDED]

    @property
    def questionable(self) -> list[ExclusionEntry]:
        return [e for e in self.entries if e.status == STATUS_QUESTIONABLE]

    def excluded_service_ids(self) -> set[str]:
        return {e.service_id for e in self.excluded}

    def questionable_service_ids(self) -> set[str]:
        return {e.service_id for e in self.questionable}

    def by_service_id(self) -> dict[str, ExclusionEntry]:
        # Last write wins if a domain appears twice; excluded outranks questionable.
        out: dict[str, ExclusionEntry] = {}
        for e in self.entries:
            prior = out.get(e.service_id)
            if prior is None or (prior.status != STATUS_EXCLUDED and e.status == STATUS_EXCLUDED):
                out[e.service_id] = e
        return out

    def summary(self) -> dict:
        return {
            "source": self.source_path,
            "total": len(self.entries),
            "excluded": len(self.excluded),
            "questionable": len(self.questionable),
        }


def default_exclusions_path(repo: Path) -> Path:
    return Path(repo) / EXCLUSIONS_REL


def load_exclusions(path: Path | str) -> ExclusionSet:
    """Load and validate the exclusions register.

    Rows with an unknown status, an empty domain, or a domain that cannot be
    normalized are skipped rather than silently trusted; a missing required
    column is a hard error so a truncated file cannot quietly disable exclusions.
    """
    path = Path(path)
    if not path.exists():
        raise ExclusionsError(f"exclusions file not found: {path}")
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in EXCLUSION_FIELDS if c not in (reader.fieldnames or [])]
        if missing:
            raise ExclusionsError(f"{path} is missing required columns: {missing}")
        entries: list[ExclusionEntry] = []
        for row in reader:
            domain = (row.get("domain") or "").strip()
            status = (row.get("status") or "").strip().lower()
            if not domain or domain.startswith("#"):
                continue
            if status not in VALID_STATUSES:
                continue
            try:
                host = normalize_host(domain)
            except Exception:
                continue
            entries.append(
                ExclusionEntry(
                    domain=host,
                    status=status,
                    reason=(row.get("reason") or "").strip(),
                    evidence=(row.get("evidence") or "").strip(),
                    reviewed_at=(row.get("reviewed_at") or "").strip(),
                    review_version=(row.get("review_version") or "").strip(),
                    service_id=service_id_for_host(host),
                )
            )
    return ExclusionSet(entries=entries, source_path=str(path))


def load_exclusions_or_default(
    repo: Path, explicit: Path | str | None, *, enabled: bool = True
) -> ExclusionSet | None:
    """Resolve which register to use.

    ``explicit`` path if given; otherwise the canonical
    ``data/archive_config/capture_exclusions.csv`` when it exists. Returns None
    when disabled or when no register is present.
    """
    if not enabled:
        return None
    if explicit is not None:
        return load_exclusions(explicit)
    default = default_exclusions_path(repo)
    if default.exists():
        return load_exclusions(default)
    return None
