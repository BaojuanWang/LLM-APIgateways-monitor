"""Tombstones: recorded evidence that a service appears to have ended.

Design stance: a tombstone is **evidence with a confidence level**, not a death
certificate. The monitor sees the web from one vantage point every six hours; a
timeout can mean the service is gone, or that a CDN dropped one request, or that
this machine's network was briefly unhappy. So:

* one transient failure never produces a tombstone;
* thresholds (consecutive observations *and* elapsed span) gate emission;
* confidence is recorded explicitly and stays ``provisional`` until a longer
  span of consistent evidence accumulates;
* ``CLOUDFLARE_OR_BLOCKED`` is treated as "we cannot see", never as "it is
  gone", because a challenge page proves the origin is answering.

Tombstones are immutable once written: reappearance produces a *new* record
rather than editing or deleting the old one, because the fact that the service
looked dead on a given date remains true.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .canonical import write_json
from .envmeta import parse_utc, utc_now_iso
from .errors import OverwriteError
from .identity import (
    INCONCLUSIVE_STATUSES,
    LIVE_STATUSES,
    TERMINAL_CANDIDATE_STATUSES,
    MonitorObservation,
)

# Monitor status -> tombstone state vocabulary.
STATE_MAP = {
    "DNS_FAIL": "dns_failure_persistent",
    "SERVICE_STOPPED": "service_stopped",
    "PARKED_OR_FOR_SALE": "parked_or_for_sale",
    "HTTP_ERROR": "http_failure_persistent",
    "TIMEOUT": "unreachable_persistent",
    "HTTP_404": "http_failure_persistent",
}

CONFIDENCE_LEVELS = ("insufficient", "provisional", "probable", "high")


@dataclass
class TombstoneEvidence:
    """Result of examining one service's observation history."""

    service_id: str
    host: str
    should_emit: bool
    prior_state: str = ""
    new_state: str = ""
    confidence: str = "insufficient"
    consecutive_observations: int = 0
    span_hours: float = 0.0
    first_terminal_utc: str = ""
    last_terminal_utc: str = ""
    last_live_utc: str = ""
    inconclusive_count: int = 0
    redirect_target_host: str = ""
    notes: list[str] = field(default_factory=list)
    evidence_rows: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "service_id": self.service_id,
            "host": self.host,
            "should_emit": self.should_emit,
            "prior_state": self.prior_state,
            "new_state": self.new_state,
            "confidence": self.confidence,
            "consecutive_observations": self.consecutive_observations,
            "span_hours": round(self.span_hours, 2),
            "first_terminal_utc": self.first_terminal_utc,
            "last_terminal_utc": self.last_terminal_utc,
            "last_live_utc": self.last_live_utc,
            "inconclusive_count": self.inconclusive_count,
            "redirect_target_host": self.redirect_target_host,
            "notes": self.notes,
        }


def _is_live_as_itself(obs: MonitorObservation) -> bool:
    """True when the service answered *as itself*.

    A 200 or 301 that lands on unrelated parking is a successful request but not
    a living service, so status alone is not sufficient.
    """
    return obs.online_status in LIVE_STATUSES and not _redirect_offsite_host(obs)


def _redirect_offsite_host(obs: MonitorObservation) -> str:
    """Host a redirect landed on, when it is unrelated to the original."""
    from .identity import InventoryError, normalize_host

    if not obs.final_url:
        return ""
    try:
        final_host = normalize_host(obs.final_url)
    except InventoryError:
        return ""
    if final_host == obs.host or final_host.endswith("." + obs.host) or obs.host.endswith("." + final_host):
        return ""
    return final_host


def evaluate_service(
    observations: list[MonitorObservation],
    *,
    cfg: dict,
) -> TombstoneEvidence:
    """Decide whether this service's history supports a tombstone."""
    tcfg = cfg.get("tombstone", {})
    min_consecutive = int(tcfg.get("min_consecutive_observations", 3))
    min_span = float(tcfg.get("min_span_hours", 48))
    high_consecutive = int(tcfg.get("high_confidence_consecutive", 6))
    high_span = float(tcfg.get("high_confidence_span_hours", 168))

    if not observations:
        return TombstoneEvidence(service_id="", host="", should_emit=False, notes=["no observations"])

    latest = observations[-1]
    evidence = TombstoneEvidence(
        service_id=latest.service_id,
        host=latest.host,
        should_emit=False,
    )

    # Walk backwards over the trailing run of observations in which the service
    # was not present *as itself*. An HTTP 200 that lands on unrelated parking
    # is not the service being alive, so a successful status alone is not
    # enough to end the run.
    trailing: list[MonitorObservation] = []
    for obs in reversed(observations):
        if _is_live_as_itself(obs):
            evidence.last_live_utc = obs.timestamp
            break
        trailing.append(obs)
    trailing.reverse()

    if not trailing:
        evidence.prior_state = latest.online_status
        evidence.new_state = "live"
        evidence.notes.append("most recent observation is live; no tombstone")
        return evidence

    # An offsite redirect is its own terminal signal even though the request
    # succeeded: the domain no longer serves this service.
    redirect_host = _redirect_offsite_host(latest)

    terminal = [
        o for o in trailing
        if o.online_status in TERMINAL_CANDIDATE_STATUSES or _redirect_offsite_host(o)
    ]
    inconclusive = [o for o in trailing if o.online_status in INCONCLUSIVE_STATUSES]
    evidence.inconclusive_count = len(inconclusive)

    if redirect_host:
        evidence.redirect_target_host = redirect_host
        evidence.new_state = "redirects_offsite"
    elif terminal and all(_redirect_offsite_host(o) for o in terminal):
        evidence.redirect_target_host = _redirect_offsite_host(terminal[-1])
        evidence.new_state = "redirects_offsite"
    elif terminal:
        # Use the most frequent terminal status in the trailing run so a single
        # odd status inside a stable failure pattern does not relabel it.
        counts: dict[str, int] = {}
        for obs in terminal:
            counts[obs.online_status] = counts.get(obs.online_status, 0) + 1
        dominant = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
        evidence.new_state = STATE_MAP.get(dominant, "unavailable_persistent")
    else:
        evidence.new_state = "unknown_not_live"
        evidence.notes.append(
            "trailing observations are inconclusive (challenge/blocked); "
            "cannot distinguish 'gone' from 'cannot see'"
        )

    # Prior state = the last live observation's status, else the first known.
    prior_live = next((o for o in reversed(observations) if _is_live_as_itself(o)), None)
    evidence.prior_state = prior_live.online_status if prior_live else observations[0].online_status

    run = terminal if terminal else trailing
    evidence.consecutive_observations = len(run)
    first_ts = parse_utc(run[0].timestamp)
    last_ts = parse_utc(run[-1].timestamp)
    if first_ts and last_ts:
        evidence.span_hours = (last_ts - first_ts).total_seconds() / 3600.0
    evidence.first_terminal_utc = run[0].timestamp
    evidence.last_terminal_utc = run[-1].timestamp
    evidence.evidence_rows = [
        {
            "timestamp": o.timestamp,
            "online_status": o.online_status,
            "http_status": o.http_status,
            "final_url": o.final_url,
            "error": o.error[:200],
        }
        for o in run[-12:]
    ]

    # --- confidence ----------------------------------------------------
    if evidence.new_state == "unknown_not_live":
        evidence.confidence = "insufficient"
        evidence.should_emit = False
        evidence.notes.append("blocked/challenge responses are not evidence of termination")
        return evidence

    if evidence.consecutive_observations < min_consecutive or evidence.span_hours < min_span:
        evidence.confidence = "insufficient"
        evidence.should_emit = False
        evidence.notes.append(
            f"needs >= {min_consecutive} consecutive observations spanning >= {min_span}h; "
            f"have {evidence.consecutive_observations} over {evidence.span_hours:.1f}h"
        )
        return evidence

    if evidence.consecutive_observations >= high_consecutive and evidence.span_hours >= high_span:
        evidence.confidence = "high"
    elif evidence.consecutive_observations >= min_consecutive * 2:
        evidence.confidence = "probable"
    else:
        evidence.confidence = "provisional"

    # An explicit operator notice or a for-sale page is direct testimony;
    # a pile of timeouts is only circumstantial.
    if evidence.new_state in ("service_stopped", "parked_or_for_sale", "redirects_offsite"):
        if evidence.confidence == "provisional":
            evidence.confidence = "probable"
        evidence.notes.append("state is directly observable on the page, not inferred from failure")
    if inconclusive:
        evidence.notes.append(
            f"{len(inconclusive)} inconclusive observation(s) in the trailing run reduce certainty"
        )

    evidence.should_emit = True
    return evidence


def build_tombstone(
    *,
    evidence: TombstoneEvidence,
    monitor_source: dict,
    last_successful_capture_id: str | None,
    last_successful_wacz_sha256: str | None,
    final_capture_attempted: bool,
    final_capture_result: str,
    extra_notes: list[str] | None = None,
) -> dict:
    return {
        "schema": "tombstone.schema.json",
        "service_id": evidence.service_id,
        "host": evidence.host,
        "recorded_at_utc": utc_now_iso(),
        "prior_state": evidence.prior_state,
        "new_state": evidence.new_state,
        "confidence": evidence.confidence,
        "is_provisional": evidence.confidence in ("provisional", "insufficient"),
        "evidence": {
            "source": monitor_source,
            "consecutive_observations": evidence.consecutive_observations,
            "span_hours": round(evidence.span_hours, 2),
            "first_terminal_observation_utc": evidence.first_terminal_utc,
            "last_terminal_observation_utc": evidence.last_terminal_utc,
            "last_live_observation_utc": evidence.last_live_utc,
            "inconclusive_observation_count": evidence.inconclusive_count,
            "redirect_target_host": evidence.redirect_target_host,
            "observations": evidence.evidence_rows,
        },
        "last_successful_capture_id": last_successful_capture_id,
        "last_successful_wacz_sha256": last_successful_wacz_sha256,
        "final_capture_attempted": final_capture_attempted,
        "final_capture_result": final_capture_result,
        "notes": (evidence.notes or []) + (extra_notes or []),
        "uncertainty": (
            "This record documents observed state from a single vantage point. It is not a "
            "claim that the service is permanently and globally unavailable. Reappearance "
            "produces a new record; this one is never edited or deleted."
        ),
    }


def write_tombstone(tombstones_dir: Path, tombstone: dict) -> Path:
    """Write an immutable tombstone, failing closed on collision."""
    tombstones_dir = Path(tombstones_dir)
    tombstones_dir.mkdir(parents=True, exist_ok=True)
    stamp = tombstone["recorded_at_utc"].replace(":", "").replace("-", "")
    target = tombstones_dir / f"{stamp}.json"
    if target.exists():
        raise OverwriteError(f"tombstone already exists and is immutable: {target}")
    write_json(target, tombstone)
    return target
