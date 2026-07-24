"""Capture outcome / artifact policy.

Answers a question the raw "is there a WACZ?" check cannot: *what artifact does
this particular capture need before it can be called valid?* The WACZ is the
canonical artifact and a reachable page capture is invalid without it — but a
capture of a host that does not resolve, refuses the connection, or fails TLS can
never contain a WACZ, and forcing one would make every dead-site record invalid.

The rule is deliberately **not** "no WACZ ⇒ tombstone/valid". A WACZ-less capture
is valid only on *positive* evidence: the homepage produced no HTTP response, the
recorded failure is a definitive network-layer failure, and the capture's own
record (capture.json, DNS/TLS/HTTP evidence, timestamps, SHA256 manifest) is
complete. Anything reachable-but-empty, or ambiguous (a connection or read
timeout — the host may be up and merely slow), stays retryable/invalid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .canonical import read_json

# Definitive network-layer failures: no HTTP exchange is possible, so a WACZ
# cannot exist. These correspond to the reasons recorded by
# seeds.network_failure_reason.
DEFINITIVE_UNREACHABLE = frozenset(
    {"dns_failure", "connection_refused", "network_unreachable", "tls_failure"}
)

# Ambiguous outcomes: the host may be up but slow, firewalled, or transiently
# unavailable. A retry could succeed, so these are never valid without a WACZ.
INDETERMINATE_NETWORK = frozenset({"connection_timeout", "read_timeout_no_response", "connection_error"})

# site_condition values that imply an HTTP response was actually served.
HTTP_RESPONSE_CONDITIONS = frozenset(
    {"ok", "redirected_offsite", "blocked_or_challenge", "parked_or_for_sale", "service_stopped"}
)

# Capture outcomes.
OUTCOME_ARCHIVED = "archived"                    # WACZ present -> the standard valid capture
OUTCOME_UNREACHABLE = "documented_unreachable"   # no WACZ, confirmed unreachable, evidence complete
OUTCOME_RETRYABLE = "retryable_no_wacz"          # no WACZ, reachable or indeterminate -> retry
OUTCOME_INCOMPLETE = "incomplete"                # interrupted / quarantined

QUARANTINE_MARKER = "quarantine.json"


@dataclass
class Outcome:
    outcome: str
    wacz_required: bool
    reachability: str            # reachable | confirmed_unreachable | indeterminate | unknown
    network_failure: str | None = None
    evidence_complete: bool | None = None
    missing_evidence: list = field(default_factory=list)
    reasons: list = field(default_factory=list)

    @property
    def is_valid_without_wacz(self) -> bool:
        return self.outcome == OUTCOME_UNREACHABLE

    def as_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "wacz_required": self.wacz_required,
            "reachability": self.reachability,
            "network_failure": self.network_failure,
            "evidence_complete": self.evidence_complete,
            "missing_evidence": self.missing_evidence,
            "reasons": self.reasons,
        }


def _wacz_present(capture_root: Path) -> bool:
    collections = capture_root / "raw" / "browsertrix" / "collections"
    if not collections.is_dir():
        return False
    for wacz in collections.glob("*/*.wacz"):
        if wacz.is_file() and wacz.stat().st_size > 0:
            return True
    return False


def _http_response_observed(cap: dict) -> bool:
    """True if the capture's own record shows any HTTP response was received."""
    for seed in cap.get("seeds", []) or []:
        if seed.get("http_status") is not None:
            return True
    rendered = cap.get("rendered", {}) or {}
    for page in rendered.get("pages", []) or []:
        if page.get("ok") and page.get("http_status") is not None:
            return True
    if cap.get("site_condition") in HTTP_RESPONSE_CONDITIONS:
        return True
    return False


def _evidence_complete(capture_root: Path, cap: dict) -> tuple[bool, list[str]]:
    """A WACZ-less unreachable capture must still carry a complete record."""
    missing: list[str] = []
    if not cap.get("started_utc"):
        missing.append("started_utc")
    if not cap.get("ended_utc"):
        missing.append("ended_utc")
    if not cap.get("effective_config_hash"):
        missing.append("effective_config_hash")
    # DNS/TLS/HTTP evidence: the sanitized network summary documenting the attempt.
    if not (capture_root / "raw" / "rendered" / "network_summary.jsonl").exists():
        missing.append("network_summary.jsonl")
    # Browsertrix's own exit record (proves the crawler ran and produced no WACZ).
    if not (capture_root / "validation" / "browsertrix_exit.json").exists():
        missing.append("browsertrix_exit.json")
    if not (capture_root / "config" / "environment.json").exists():
        missing.append("environment.json")
    if not (capture_root / "manifests" / "sha256_manifest.json").exists():
        missing.append("sha256_manifest.json")
    return (not missing, missing)


def classify_outcome(capture_root: Path) -> Outcome:
    """Classify a capture directory into an outcome and its artifact requirement."""
    capture_root = Path(capture_root)
    cap_path = capture_root / "capture.json"
    manifest_path = capture_root / "manifests" / "sha256_manifest.json"

    # An explicit quarantine marker is authoritative.
    if (capture_root / QUARANTINE_MARKER).exists():
        return Outcome(
            outcome=OUTCOME_INCOMPLETE,
            wacz_required=False,
            reachability="unknown",
            reasons=["quarantine marker present"],
        )

    # Interrupted: the directory was created but never sealed. The primary
    # signal is a missing capture.json — the capture never wrote its own record,
    # so there is nothing to validate as pass/fail and it is quarantined. (A dir
    # that HAS capture.json but is missing its manifest is an anomaly, not a
    # clean interruption: it falls through to normal validation, where the
    # manifest check fails it as invalid rather than silently excusing it.)
    if not cap_path.exists():
        missing = ["capture.json"]
        if not manifest_path.exists():
            missing.append("sha256_manifest.json")
        return Outcome(
            outcome=OUTCOME_INCOMPLETE,
            wacz_required=False,
            reachability="unknown",
            missing_evidence=missing,
            reasons=[f"interrupted: missing {', '.join(missing)}; capture never sealed"],
        )

    cap = read_json(cap_path)

    if _wacz_present(capture_root):
        return Outcome(
            outcome=OUTCOME_ARCHIVED,
            wacz_required=True,
            reachability="reachable",
            reasons=["WACZ present"],
        )

    # No WACZ from here on.
    if _http_response_observed(cap):
        return Outcome(
            outcome=OUTCOME_RETRYABLE,
            wacz_required=True,
            reachability="reachable",
            reasons=["an HTTP response was observed but no WACZ was produced; retry"],
        )

    seed_discovery = cap.get("seed_discovery", {}) or {}
    reason = seed_discovery.get("probing_skipped_reason")
    homepage_reachable = seed_discovery.get("homepage_reachable")

    if reason in DEFINITIVE_UNREACHABLE and homepage_reachable is False:
        complete, missing = _evidence_complete(capture_root, cap)
        if complete:
            return Outcome(
                outcome=OUTCOME_UNREACHABLE,
                wacz_required=False,
                reachability="confirmed_unreachable",
                network_failure=reason,
                evidence_complete=True,
                reasons=[f"no HTTP response; definitive network failure ({reason}); record complete"],
            )
        return Outcome(
            outcome=OUTCOME_RETRYABLE,
            wacz_required=True,
            reachability="confirmed_unreachable",
            network_failure=reason,
            evidence_complete=False,
            missing_evidence=missing,
            reasons=[f"unreachable ({reason}) but record incomplete: missing {', '.join(missing)}"],
        )

    # No HTTP response and no definitive network-layer failure -> indeterminate.
    return Outcome(
        outcome=OUTCOME_RETRYABLE,
        wacz_required=True,
        reachability="indeterminate",
        network_failure=reason,
        reasons=[
            f"no HTTP response and no definitive network failure (reason={reason!r}); "
            "cannot distinguish 'gone' from 'slow/transient' — retryable"
        ],
    )
