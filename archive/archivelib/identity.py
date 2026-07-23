"""Service identity and inventory loading.

The project identifies services at the **host** level (``api.example.com`` is a
different service from ``example.com``). This module preserves that: it never
folds hosts into an eTLD+1 group. A ``service_id`` is a stable, filesystem-safe,
collision-resistant encoding of a single observed host.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from .canonical import sha256_file, sha256_text

# Repository-relative inventory sources, in precedence order. `source` mirrors
# the label pipeline.py assigns so the archive and the monitor agree.
INVENTORY_SOURCES = (
    ("data/hvoy_latest.csv", "hvoy"),
    ("data/manual_sites.csv", "manual"),
    ("data/master_sites.csv", "discovery"),
)

MONITOR_RESULTS = "results/monitor_results.csv"

_SAFE_CHARS = re.compile(r"[^a-z0-9]+")
_HOST_MAX = 48
_HOST_HASH_LEN = 8


class InventoryError(Exception):
    """Inventory could not be loaded or a host could not be normalized."""


def normalize_host(value: str) -> str:
    """Reduce a URL or bare host to a canonical lowercase hostname.

    Strips scheme, credentials, port, path, and a trailing dot; IDNs are encoded
    to punycode so the same site always yields the same id.
    """
    if not value:
        raise InventoryError("empty host")
    host = str(value).strip()
    host = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", host)
    host = host.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in host:  # strip userinfo
        host = host.rsplit("@", 1)[1]
    if host.startswith("["):  # IPv6 literal
        host = host.split("]", 1)[0] + "]"
    else:
        host = host.split(":", 1)[0]
    host = host.strip().rstrip(".").lower()
    if not host:
        raise InventoryError(f"could not normalize host from {value!r}")
    try:
        host.encode("ascii")
    except UnicodeEncodeError:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise InventoryError(f"cannot IDNA-encode host {value!r}") from exc
    return host


def service_id_for_host(host: str) -> str:
    """Stable directory-safe id for one host.

    The trailing hash is not decoration: ``a-b.com`` and ``a.b.com`` both
    sanitize to ``a-b-com``, so without it two distinct services would share a
    corpus directory.
    """
    canonical = normalize_host(host)
    slug = _SAFE_CHARS.sub("-", canonical).strip("-")
    if len(slug) > _HOST_MAX:
        slug = slug[:_HOST_MAX].rstrip("-")
    if not slug:
        slug = "host"
    return f"{slug}_{sha256_text(canonical)[:_HOST_HASH_LEN]}"


@dataclass
class ServiceIdentity:
    """One service as the monitor knows it, plus archive-side identity."""

    service_id: str
    host: str
    canonical_url: str
    platform_name: str = ""
    source: str = ""
    aliases: list[str] = field(default_factory=list)
    inventory_file: str = ""
    inventory_file_sha256: str = ""
    inventory_row: dict = field(default_factory=dict)
    inventory_row_sha256: str = ""
    first_seen_utc: str | None = None
    last_seen_utc: str | None = None

    def to_site_json(self) -> dict:
        return {
            "schema": "site.schema.json",
            "service_id": self.service_id,
            "host": self.host,
            "canonical_url": self.canonical_url,
            "platform_name": self.platform_name,
            "source": self.source,
            "aliases": sorted(set(self.aliases)),
            "identity_policy": "host-level; no eTLD+1 merging",
            "inventory": {
                "file": self.inventory_file,
                "file_sha256": self.inventory_file_sha256,
                "row": self.inventory_row,
                "row_sha256": self.inventory_row_sha256,
            },
            "first_seen_utc": self.first_seen_utc,
            "last_seen_utc": self.last_seen_utc,
        }


def _row_sha256(row: dict) -> str:
    """Hash of the literal inventory row, field order preserved."""
    parts = [f"{k}={row.get(k, '')}" for k in row]
    return sha256_text("\x1f".join(parts))


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def load_inventory(repo: Path) -> dict[str, ServiceIdentity]:
    """Load the monitor's authoritative inventories, keyed by ``service_id``.

    Read-only: this never writes to ``data/``. Earlier sources win, matching
    ``scripts/pipeline.py``'s precedence, so archive identity cannot disagree
    with monitor identity.
    """
    services: dict[str, ServiceIdentity] = {}
    for rel, source_label in INVENTORY_SOURCES:
        path = repo / rel
        if not path.exists():
            continue
        file_hash = sha256_file(path)
        for row in _read_csv(path):
            raw_domain = row.get("domain", "")
            if not raw_domain:
                continue
            try:
                host = normalize_host(raw_domain)
            except InventoryError:
                continue
            sid = service_id_for_host(host)
            if sid in services:
                continue
            aliases = []
            site_domain = row.get("siteDomain", "")
            if site_domain:
                try:
                    alias = normalize_host(site_domain)
                    if alias != host:
                        aliases.append(alias)
                except InventoryError:
                    pass
            services[sid] = ServiceIdentity(
                service_id=sid,
                host=host,
                canonical_url=f"https://{host}/",
                platform_name=(row.get("platform_name") or row.get("siteName") or "").strip(),
                source=(row.get("source") or source_label).strip() or source_label,
                aliases=aliases,
                inventory_file=rel,
                inventory_file_sha256=file_hash,
                inventory_row=row,
                inventory_row_sha256=_row_sha256(row),
            )
    return services


@dataclass
class MonitorObservation:
    """One row of ``results/monitor_results.csv``."""

    timestamp: str
    host: str
    platform_name: str
    source: str
    online_status: str
    http_status: str
    final_url: str
    page_title: str
    html_hash: str
    redirect_chain: str
    error: str

    @property
    def service_id(self) -> str:
        return service_id_for_host(self.host)


# Statuses the monitor emits that indicate the service answered as a service.
LIVE_STATUSES = frozenset({"ONLINE", "ONLINE_LOGIN_REQUIRED", "REDIRECTED"})

# Statuses that are candidate evidence of a service ending. Transient by
# themselves — tombstone.py requires repetition before drawing a conclusion.
TERMINAL_CANDIDATE_STATUSES = frozenset(
    {"DNS_FAIL", "SERVICE_STOPPED", "PARKED_OR_FOR_SALE", "HTTP_ERROR", "TIMEOUT", "HTTP_404"}
)

# Statuses that mean "we could not see the site", not "the site is gone".
INCONCLUSIVE_STATUSES = frozenset({"CLOUDFLARE_OR_BLOCKED", "TIMEOUT"})


def load_monitor_history(repo: Path, *, limit_rows: int | None = None) -> list[MonitorObservation]:
    """Read monitor results in file order (oldest first).

    Read-only. ``limit_rows`` keeps only the most recent N rows for planning
    runs that do not need the full multi-year history.
    """
    path = repo / MONITOR_RESULTS
    rows = _read_csv(path)
    if limit_rows is not None and len(rows) > limit_rows:
        rows = rows[-limit_rows:]
    observations: list[MonitorObservation] = []
    for row in rows:
        raw_domain = row.get("domain", "")
        if not raw_domain:
            continue
        try:
            host = normalize_host(raw_domain)
        except InventoryError:
            continue
        observations.append(
            MonitorObservation(
                timestamp=row.get("timestamp", ""),
                host=host,
                platform_name=row.get("platform_name", ""),
                source=row.get("source", ""),
                online_status=row.get("online_status", ""),
                http_status=row.get("http_status", ""),
                final_url=row.get("final_url", ""),
                page_title=row.get("page_title", ""),
                html_hash=row.get("html_hash", ""),
                redirect_chain=row.get("redirect_chain", ""),
                error=row.get("error", ""),
            )
        )
    return observations


def group_by_service(observations: list[MonitorObservation]) -> dict[str, list[MonitorObservation]]:
    """Group observations by service, preserving chronological order."""
    grouped: dict[str, list[MonitorObservation]] = {}
    for obs in observations:
        grouped.setdefault(obs.service_id, []).append(obs)
    return grouped


def monitor_source_fingerprint(repo: Path) -> dict:
    """Provenance for whichever monitor file drove a decision."""
    path = repo / MONITOR_RESULTS
    if not path.exists():
        return {"file": MONITOR_RESULTS, "exists": False, "sha256": None, "size_bytes": None}
    return {
        "file": MONITOR_RESULTS,
        "exists": True,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }
