"""Effective-configuration assembly and hashing.

Config precedence, lowest to highest: built-in defaults, the TOML file, then
explicit CLI overrides. The merged result is hashed and stored with every
capture so a capture can be reproduced — or shown to be irreproducible —
years later.
"""

from __future__ import annotations

import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

from .canonical import sha256_json

DEFAULT_CONFIG: dict[str, Any] = {
    "storage": {
        # External-volume storage is the default and the recommendation. Setting
        # this to true authorizes keeping the corpus on the Mac's own disk; the
        # path must still clear every check in localstore.validate_local_root.
        # The --allow-local-storage CLI flag does the same thing per-invocation.
        "allow_local_storage": False,
    },
    "capture": {
        # Bounded by policy, not by taste: an unbounded crawl of a third-party
        # service is both rude and unusable as evidence.
        "max_seeds": 8,
        "page_limit": 8,
        "time_limit_seconds": 600,
        "workers": 1,
        "scope_type": "page",
        "page_load_timeout_seconds": 60,
        "behavior_timeout_seconds": 30,
        "user_agent_suffix": "LLM-APIgateways-archive/0.1 (research; contact via repository)",
    },
    "browsertrix": {
        "image": "webrecorder/browsertrix-crawler",
        "tag": "1.12.4",
        "digest": "",  # resolved during preflight; recorded per capture
        "generate_wacz": True,
        "generate_cdx": True,
        "text_extraction": ["to-pages", "to-warc"],
        "screenshot_modes": ["view", "fullPage"],
        "behaviors": ["autoscroll"],
        "block_ads": False,
        "fail_on_failed_seed": False,
        "log_options": ["stats", "debug"],
    },
    "singlefile": {
        "enabled": True,
        "version": "2.0.83",
        "package": "single-file-cli",
        "docker_image": "",  # optional alternative; must be digest-pinned
        "docker_digest": "",
        "timeout_seconds": 120,
    },
    "rendered": {
        "enabled": True,
        "viewport_width": 1440,
        "viewport_height": 900,
        "device_scale_factor": 1,
        "navigation_timeout_seconds": 45,
        "settle_seconds": 3,
        "max_pages": 4,
        "full_page_screenshot": True,
    },
    "seeds": {
        # Known paths are probed, never brute-forced: this is a small explicit
        # list of conventional locations, not directory enumeration.
        "known_paths": [
            "/login",
            "/register",
            "/pricing",
            "/docs",
            "/about",
            "/models",
            "/status",
            "/privacy",
            "/terms",
            "/announcement",
        ],
        "api_paths": ["/api/status", "/api/pricing", "/v1/models", "/api/models"],
        "include_api_paths": True,
        "max_link_candidates": 200,
        # Per-request timeout for every seed-discovery HTTP call (homepage and
        # each known-path/API probe). Conservative default: a dying host that
        # accepts a connection but never answers costs at most this long per
        # request, and — since the homepage is tried first — a network-layer
        # failure there skips all further probing entirely.
        "request_timeout_seconds": 10,
        # Retained for backward compatibility; used only as a fallback when
        # request_timeout_seconds is absent.
        "link_discovery_timeout_seconds": 30,
    },
    "queue": {
        "monthly_days": 30,
        "cooldown_hours": 24,
        "max_sites": 10,
        "concurrency": 1,
        "retry_failures": False,
        "retry_backoff_hours": 12,
    },
    "tombstone": {
        # A single timeout is noise. Require repetition and elapsed time before
        # any confident claim that a service ended.
        "min_consecutive_observations": 3,
        "min_span_hours": 48,
        "high_confidence_consecutive": 6,
        "high_confidence_span_hours": 168,
    },
    "safety": {
        "allow_form_submission": False,
        "allow_authenticated_areas": False,
        "load_browser_profile": False,
        "max_capture_bytes": 2 * 1024 * 1024 * 1024,
        "min_free_bytes": 5 * 1024 * 1024 * 1024,
    },
}

# Config file locations searched in order when --config is not given.
CONFIG_CANDIDATES = ("archive/config/archive.toml", "archive/config/archive.example.toml")


class ConfigError(Exception):
    """Configuration file is missing, unreadable, or structurally wrong."""


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def find_config(repo: Path, explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        path = Path(explicit)
        if not path.exists():
            raise ConfigError(f"config file not found: {path}")
        return path
    for rel in CONFIG_CANDIDATES:
        candidate = repo / rel
        if candidate.exists():
            return candidate
    return None


def load_config(repo: Path, explicit: Path | None = None, overrides: dict | None = None) -> dict:
    """Return the effective config: defaults <- file <- overrides."""
    effective = deepcopy(DEFAULT_CONFIG)
    path = find_config(repo, explicit)
    if path is not None:
        try:
            with open(path, "rb") as handle:
                file_cfg = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"invalid TOML in {path}: {exc}") from exc
        effective = _deep_merge(effective, file_cfg)
    if overrides:
        effective = _deep_merge(effective, overrides)
    effective["_meta"] = {
        "config_file": str(path.relative_to(repo)) if path and path.is_relative_to(repo) else (str(path) if path else None),
        "defaults_version": "0.1.0",
    }
    validate_config(effective)
    return effective


def validate_config(cfg: dict) -> None:
    """Reject configurations that would produce unsafe or useless captures."""
    capture = cfg.get("capture", {})
    if int(capture.get("max_seeds", 0)) < 1:
        raise ConfigError("capture.max_seeds must be >= 1")
    if int(capture.get("max_seeds", 0)) > 25:
        raise ConfigError("capture.max_seeds above 25 is not permitted for third-party services")
    if int(capture.get("workers", 1)) < 1:
        raise ConfigError("capture.workers must be >= 1")
    if capture.get("scope_type") not in {"page", "page-spa", "prefix"}:
        raise ConfigError("capture.scope_type must be one of: page, page-spa, prefix")

    bt = cfg.get("browsertrix", {})
    if not bt.get("tag"):
        raise ConfigError("browsertrix.tag must be pinned")
    if str(bt.get("tag")).strip().lower() == "latest":
        raise ConfigError("browsertrix.tag must not be 'latest'; pin an exact release")
    if not bt.get("generate_wacz", True):
        raise ConfigError("browsertrix.generate_wacz must stay true; WACZ is the canonical artifact")

    sf = cfg.get("singlefile", {})
    if sf.get("enabled") and not (sf.get("version") or sf.get("docker_digest")):
        raise ConfigError("singlefile.enabled requires a pinned version or an image digest")
    if sf.get("docker_image") and not sf.get("docker_digest"):
        raise ConfigError("singlefile.docker_image requires singlefile.docker_digest (no floating tags)")

    safety = cfg.get("safety", {})
    for flag in ("allow_form_submission", "allow_authenticated_areas", "load_browser_profile"):
        if safety.get(flag):
            raise ConfigError(f"safety.{flag} must remain false in this subsystem")

    queue = cfg.get("queue", {})
    if int(queue.get("concurrency", 1)) < 1:
        raise ConfigError("queue.concurrency must be >= 1")

    storage = cfg.get("storage", {})
    if not isinstance(storage.get("allow_local_storage", False), bool):
        raise ConfigError("storage.allow_local_storage must be a boolean")


def hashable_config(cfg: dict) -> dict:
    """Config with non-substantive metadata removed, for hashing."""
    trimmed = deepcopy(cfg)
    trimmed.pop("_meta", None)
    return trimmed


def config_hash(cfg: dict) -> str:
    """SHA256 over the canonical form of the substantive configuration."""
    return sha256_json(hashable_config(cfg))
