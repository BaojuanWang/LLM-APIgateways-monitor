"""Capture queue planning.

The six-hour GitHub Actions monitor stays the cheap change detector. This module
turns its output into a small, bounded, deterministic list of services worth a
full local capture — never the whole inventory.

Trigger reasons, highest priority first:

``tombstone_evidence``   evidence the service may be ending; capture before it goes
``status_transition``    live <-> not-live boundary crossed
``reappearance``         came back after a gap; the recovered state is new evidence
``first_capture``        never archived
``final_url_change``     the domain now lands somewhere else
``homepage_hash_change`` content changed since the last capture
``title_change``         weaker content signal
``monthly_interval``     nothing changed, but the corpus needs a periodic anchor
``retry_failure``        the previous capture failed and retry is enabled

Ordering is fully deterministic — ``(priority, service_id)`` — so a dry run and
the real run queue the same services in the same order.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from .canonical import sha256_json
from .envmeta import parse_utc, utc_now_iso
from .identity import (
    LIVE_STATUSES,
    MonitorObservation,
    ServiceIdentity,
    group_by_service,
)
from .tombstone import evaluate_service

PUBLIC_CAPTURES_CSV = "data/archive_public/captures.csv"

REASON_PRIORITY = {
    "tombstone_evidence": 10,
    "status_transition": 20,
    "reappearance": 30,
    "first_capture": 40,
    "final_url_change": 50,
    "homepage_hash_change": 60,
    "title_change": 70,
    "retry_failure": 80,
    "monthly_interval": 90,
    "manual": 5,
}


@dataclass
class CaptureHistoryEntry:
    service_id: str
    capture_id: str
    started_utc: str
    status: str
    validation_status: str
    wacz_sha256: str
    homepage_html_hash: str = ""
    final_url: str = ""
    page_title: str = ""

    @property
    def succeeded(self) -> bool:
        return self.status == "completed" and self.validation_status in ("valid", "valid_with_warnings")


def load_capture_history(repo: Path) -> dict[str, list[CaptureHistoryEntry]]:
    """Read the sanitized public capture index.

    Planning reads the *public* index rather than the corpus so that
    ``--dry-run`` works with the external disk unplugged — the repository must
    never depend on the disk merely to reason about what to do next.
    """
    path = Path(repo) / PUBLIC_CAPTURES_CSV
    history: dict[str, list[CaptureHistoryEntry]] = {}
    if not path.exists():
        return history
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            sid = (row.get("service_id") or "").strip()
            if not sid:
                continue
            history.setdefault(sid, []).append(
                CaptureHistoryEntry(
                    service_id=sid,
                    capture_id=(row.get("capture_id") or "").strip(),
                    started_utc=(row.get("capture_started_utc") or "").strip(),
                    status=(row.get("status") or "").strip(),
                    validation_status=(row.get("validation_status") or "").strip(),
                    wacz_sha256=(row.get("wacz_sha256") or "").strip(),
                    homepage_html_hash=(row.get("source_homepage_html_hash") or "").strip(),
                    final_url=(row.get("source_final_url") or "").strip(),
                    page_title=(row.get("source_page_title") or "").strip(),
                )
            )
    for entries in history.values():
        entries.sort(key=lambda e: e.started_utc)
    return history


@dataclass
class QueueEntry:
    service_id: str
    host: str
    canonical_url: str
    reason: str
    priority: int
    detail: str = ""
    prior_monitor_state: dict = field(default_factory=dict)
    last_capture_id: str = ""
    last_capture_utc: str = ""

    def as_dict(self) -> dict:
        return {
            "service_id": self.service_id,
            "host": self.host,
            "canonical_url": self.canonical_url,
            "reason": self.reason,
            "priority": self.priority,
            "detail": self.detail,
            "prior_monitor_state": self.prior_monitor_state,
            "last_capture_id": self.last_capture_id,
            "last_capture_utc": self.last_capture_utc,
        }


def _latest_state(observations: list[MonitorObservation]) -> dict:
    latest = observations[-1]
    return {
        "timestamp": latest.timestamp,
        "online_status": latest.online_status,
        "http_status": latest.http_status,
        "final_url": latest.final_url,
        "page_title": latest.page_title,
        "html_hash": latest.html_hash,
        "error": latest.error[:200],
    }


def _reappeared(observations: list[MonitorObservation]) -> bool:
    """Live now, but not live in the immediately preceding observation."""
    if len(observations) < 2:
        return False
    return (
        observations[-1].online_status in LIVE_STATUSES
        and observations[-2].online_status not in LIVE_STATUSES
    )


def _status_transitioned(observations: list[MonitorObservation]) -> bool:
    if len(observations) < 2:
        return False
    now_live = observations[-1].online_status in LIVE_STATUSES
    was_live = observations[-2].online_status in LIVE_STATUSES
    return now_live != was_live


def plan_queue(
    *,
    inventory: dict[str, ServiceIdentity],
    observations: list[MonitorObservation],
    history: dict[str, list[CaptureHistoryEntry]],
    cfg: dict,
    now_utc: str | None = None,
    only_service_id: str | None = None,
    only_domain: str | None = None,
    forced_reason: str | None = None,
    max_sites: int | None = None,
    monthly_days: int | None = None,
    retry_failures: bool | None = None,
) -> dict:
    """Produce a deterministic, bounded capture queue."""
    qcfg = cfg.get("queue", {})
    monthly_days = int(qcfg.get("monthly_days", 30) if monthly_days is None else monthly_days)
    cooldown_hours = float(qcfg.get("cooldown_hours", 24))
    max_sites = int(qcfg.get("max_sites", 10) if max_sites is None else max_sites)
    retry_failures = bool(qcfg.get("retry_failures", False) if retry_failures is None else retry_failures)

    now = parse_utc(now_utc or utc_now_iso())
    grouped = group_by_service(observations)

    candidates: list[QueueEntry] = []
    skipped: list[dict] = []

    target_sid = only_service_id
    if only_domain and not target_sid:
        from .identity import service_id_for_host

        target_sid = service_id_for_host(only_domain)

    for sid, identity in sorted(inventory.items()):
        if target_sid and sid != target_sid:
            continue

        obs = grouped.get(sid, [])
        prior_state = _latest_state(obs) if obs else {}
        entries = history.get(sid, [])
        successful = [e for e in entries if e.succeeded]
        last_entry = entries[-1] if entries else None
        last_success = successful[-1] if successful else None

        # Cooldown applies to every reason except an explicit manual request:
        # a human asking for a capture has already made the judgment call.
        if last_entry and not forced_reason:
            last_dt = parse_utc(last_entry.started_utc)
            if last_dt and now and (now - last_dt) < timedelta(hours=cooldown_hours):
                skipped.append(
                    {
                        "service_id": sid,
                        "reason": "cooldown",
                        "detail": f"captured {last_entry.started_utc}, cooldown {cooldown_hours}h",
                    }
                )
                continue

        reason: str | None = None
        detail = ""

        if forced_reason:
            reason, detail = forced_reason, "explicitly requested"
        elif obs:
            tomb = evaluate_service(obs, cfg=cfg)
            if tomb.should_emit:
                reason = "tombstone_evidence"
                detail = f"{tomb.new_state} (confidence={tomb.confidence}, {tomb.consecutive_observations} obs / {tomb.span_hours:.0f}h)"
            elif _reappeared(obs):
                reason, detail = "reappearance", f"back online after {obs[-2].online_status}"
            elif _status_transitioned(obs):
                reason, detail = "status_transition", f"{obs[-2].online_status} -> {obs[-1].online_status}"

        if reason is None and not successful:
            reason, detail = "first_capture", "no successful capture on record"

        if reason is None and last_success and obs:
            latest = obs[-1]
            if last_success.final_url and latest.final_url and last_success.final_url != latest.final_url:
                reason, detail = "final_url_change", "final URL differs from last capture"
            elif last_success.homepage_html_hash and latest.html_hash and last_success.homepage_html_hash != latest.html_hash:
                reason, detail = "homepage_hash_change", "homepage html_hash differs from last capture"
            elif last_success.page_title and latest.page_title and last_success.page_title != latest.page_title:
                reason, detail = "title_change", "page title differs from last capture"

        if reason is None and retry_failures and last_entry and not last_entry.succeeded:
            reason, detail = "retry_failure", f"previous capture {last_entry.capture_id} status={last_entry.status}"

        if reason is None and last_success:
            last_dt = parse_utc(last_success.started_utc)
            if last_dt and now and (now - last_dt) >= timedelta(days=monthly_days):
                reason, detail = "monthly_interval", f"last successful capture {last_success.started_utc}"

        if reason is None:
            continue

        candidates.append(
            QueueEntry(
                service_id=sid,
                host=identity.host,
                canonical_url=identity.canonical_url,
                reason=reason,
                priority=REASON_PRIORITY.get(reason, 99),
                detail=detail,
                prior_monitor_state=prior_state,
                last_capture_id=last_success.capture_id if last_success else "",
                last_capture_utc=last_success.started_utc if last_success else "",
            )
        )

    candidates.sort(key=lambda e: (e.priority, e.service_id))
    selected = candidates[:max_sites]
    deferred = candidates[max_sites:]

    queue = {
        "schema": "archive_queue",
        "generated_at_utc": now_utc or utc_now_iso(),
        "parameters": {
            "max_sites": max_sites,
            "monthly_days": monthly_days,
            "cooldown_hours": cooldown_hours,
            "retry_failures": retry_failures,
            "concurrency": int(qcfg.get("concurrency", 1)),
            "only_service_id": only_service_id,
            "only_domain": only_domain,
            "forced_reason": forced_reason,
        },
        "counts": {
            "inventory": len(inventory),
            "with_observations": len(grouped),
            "candidates": len(candidates),
            "selected": len(selected),
            "deferred": len(deferred),
            "skipped_cooldown": len(skipped),
        },
        "entries": [e.as_dict() for e in selected],
        "deferred": [{"service_id": e.service_id, "reason": e.reason, "priority": e.priority} for e in deferred[:100]],
        "skipped": skipped[:100],
    }
    queue["queue_hash"] = sha256_json(queue["entries"])[:16]
    return queue
