#!/usr/bin/env python3
"""Probe LLM API relay sites for application/infrastructure fingerprints.

The classifier is intentionally evidence-first. It separates application-layer
relay implementations (new-api, one-api, sub2api, auth2api, etc.) from
infrastructure-only signals such as Cloudflare and Nginx.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_PATHS = [
    "/",
    "/login",
    "/api/status",
    "/api/pricing",
    "/v1/models",
    "/api/models",
]

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
HVOY_CSV = DATA_DIR / "hvoy_latest.csv"
MANUAL_CSV = DATA_DIR / "manual_sites.csv"


# ── Signal tiers ──────────────────────────────────────────────────────────
# The classifier is layered by discriminative power (see
# docs/METHODS_literature_grounding_2026-07-08.md §2):
#   Tier 1 (fork)   — signals unique to ONE implementation  -> confidence "high"
#   Tier 2 (family) — signals shared across a whole family   -> confidence "family"
#   Tier 3 (domain) — the site's own name only               -> confidence "low"
# A family-level signal must NEVER be promoted to a specific fork. This is the
# formalization of the "new-api|one-api not split" rule and removes the three
# reproduced misclassifications (xxx2api catch-all, new-api|one-api double
# label, SPA-as-unknown).

# Tier 1 — fork-definitive header signals.
FORK_HEADER_PATTERNS = [
    ("new-api", "one-api-family", re.compile(r"^x-new-api-version$", re.I)),
    ("one-api", "one-api-family", re.compile(r"^x-(oneapi|one-api)-", re.I)),
]

# Tier 1 — fork-definitive body signals. These are distinctive project names /
# author handles, NOT generic branding. "new api" (spaced) is deliberately
# excluded — only the hyphen/underscore/joined forms are specific enough.
FORK_BODY_PATTERNS = [
    ("new-api", "one-api-family", re.compile(r"QuantumNous|Calcium-Ion/new-api", re.I)),
    ("one-api", "one-api-family", re.compile(r"songquanpeng", re.I)),
    ("veloera", "one-api-family", re.compile(r"\bveloera\b", re.I)),
    ("one-hub", "one-api-family", re.compile(r"\bone[-_]hub\b", re.I)),
    ("done-hub", "one-api-family", re.compile(r"\bdone[-_]hub\b", re.I)),
    ("voapi", "one-api-family", re.compile(r"\bvoapi\b", re.I)),
    ("shell-api", "one-api-family", re.compile(r"\bshell[-_]api\b", re.I)),
    ("super-api", "one-api-family", re.compile(r"\bsuper[-_]api\b", re.I)),
    ("neo-api", "one-api-family", re.compile(r"\bneo[-_]api\b", re.I)),
    ("sub2api", "subscription-to-api", re.compile(r"\bsub2api\b|Subscription to API Conversion Platform", re.I)),
    ("auth2api", "oauth-to-api", re.compile(r"\bauth2api\b", re.I)),
    ("cliproxyapi", "cli-proxy-api", re.compile(r"\bcliproxyapi\b|\bcli[-_]proxy[-_]api\b", re.I)),
    ("all-api-hub", "aggregator", re.compile(r"\ball[-_]api[-_]hub\b", re.I)),
    ("metapi", "aggregator", re.compile(r"\bmetapi\b", re.I)),
]

# Tier 2 — family-level body signals. A hit here proves the FAMILY only; it must
# not resolve to a specific fork. Generic residual branding ("one-api" left in a
# new-api page) lands here, so a fork string alone can no longer double-label.
FAMILY_BODY_PATTERNS = [
    ("one-api-family", re.compile(r"\b(new[-_]?api|one[-_]?api)\b", re.I)),
    ("subscription-to-api", re.compile(r"subscription\s+to\s+api|订阅.{0,24}(转|转换).{0,24}api|api.{0,24}(转|转换).{0,24}订阅|订阅.{0,24}api\s*key", re.I)),
    ("oauth-to-api", re.compile(r"OAuth\s+to\s+API|Claude/Codex OAuth", re.I)),
]

# Tier 3 — domain-name hints only. Weak: an operator can name a domain anything.
DOMAIN_PATTERNS = [
    ("new-api", "one-api-family", re.compile(r"newapi|new-api", re.I)),
    ("sub2api", "subscription-to-api", re.compile(r"sub2api|sub-2-api", re.I)),
    ("auth2api", "oauth-to-api", re.compile(r"auth2api|auth-2-api", re.I)),
    ("cliproxyapi", "cli-proxy-api", re.compile(r"cliproxyapi|cli-proxy-api", re.I)),
]

# SPA empty-shell markers: if a reachable page has one of these and no app
# signal, the real fingerprint is inside an unfetched JS bundle -> bucket as
# "spa_shell", not "unidentified".
SPA_SHELL_RE = re.compile(r'<div[^>]+id=["\'](root|app|__next)["\']', re.I)


INFRA_PATTERNS = [
    ("cloudflare", "header", re.compile(r"^(cf-ray|cf-cache-status|server)$", re.I), re.compile(r"cloudflare", re.I)),
    ("nginx", "header", re.compile(r"^server$", re.I), re.compile(r"nginx", re.I)),
    ("cloudflare_challenge", "body", re.compile(r"Just a moment|cf-browser-verification|cf-chl", re.I), None),
]


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status: str = ""
    headers: dict[str, str] | None = None
    body: str = ""
    error: str = ""


def normalize_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    return "https://" + value.strip("/")


def domain_from_url(value: str) -> str:
    parsed = urlparse(normalize_url(value))
    return parsed.netloc.lower().strip("/")


def row_domain(row: dict[str, str]) -> str:
    candidate = (
        row.get("url")
        or row.get("site_urls")
        or row.get("domain")
        or row.get("siteDomain")
        or row.get("input_url")
        or ""
    )
    if "|" in candidate:
        candidate = candidate.split("|", 1)[0]
    return domain_from_url(candidate)


def read_inputs(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            values: list[dict[str, str]] = []
            for row in reader:
                domain = row_domain(row)
                if domain:
                    values.append(
                        {
                            "domain": domain,
                            "platform_name": row.get("platform_name") or row.get("siteName") or row.get("site") or "",
                            "source": row.get("source") or path.stem,
                            "input_url": row.get("site_urls") or row.get("url") or row.get("domain") or row.get("siteDomain") or domain,
                        }
                    )
            return values
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        domain = domain_from_url(line)
        values.append({"domain": domain, "platform_name": "", "source": path.stem, "input_url": line.strip()})
    return values


def load_default_platforms() -> list[dict[str, str]]:
    platforms: dict[str, dict[str, str]] = {}

    if HVOY_CSV.exists():
        for row in read_inputs(HVOY_CSV):
            domain = row["domain"]
            row["source"] = "hvoy"
            platforms[domain] = row
    else:
        print(f"warning: missing {HVOY_CSV}", file=sys.stderr)

    if MANUAL_CSV.exists():
        for row in read_inputs(MANUAL_CSV):
            domain = row["domain"]
            manual_source = row.get("source") or "manual"
            if domain in platforms:
                platforms[domain]["source"] = platforms[domain].get("source", "") + "+" + manual_source
                if row.get("platform_name") and not platforms[domain].get("platform_name"):
                    platforms[domain]["platform_name"] = row["platform_name"]
            else:
                row["source"] = manual_source
                platforms[domain] = row
    else:
        print(f"warning: missing {MANUAL_CSV}", file=sys.stderr)

    return sorted(platforms.values(), key=lambda item: item["domain"])


def fetch_url(url: str, timeout: float, context: ssl.SSLContext) -> FetchResult:
    request = Request(
        url,
        headers={
            "User-Agent": "LLM-APIgateways-monitor tech-stack probe/0.1",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read(512_000)
            content_type = response.headers.get("content-type", "")
            encoding = response.headers.get_content_charset() or "utf-8"
            body = raw.decode(encoding, errors="replace")
            if "html" in content_type.lower():
                body = unescape(body)
            return FetchResult(
                url=url,
                final_url=response.geturl(),
                status=str(response.status),
                headers={key.lower(): value for key, value in response.headers.items()},
                body=body,
            )
    except HTTPError as exc:
        raw = exc.read(256_000)
        body = raw.decode("utf-8", errors="replace")
        return FetchResult(
            url=url,
            final_url=exc.geturl() or url,
            status=str(exc.code),
            headers={key.lower(): value for key, value in exc.headers.items()},
            body=body,
            error=f"HTTPError:{exc.code}",
        )
    except (URLError, TimeoutError, socket.timeout, ssl.SSLError) as exc:
        return FetchResult(url=url, error=type(exc).__name__ + ":" + str(exc))
    except Exception as exc:
        return FetchResult(url=url, error=type(exc).__name__ + ":" + str(exc))


def _parse_status_json(body: str) -> tuple[bool, str]:
    """Detect the one-api-family /api/status JSON envelope and pull its version.

    one-api and its forks answer /api/status with a JSON object carrying a
    ``system_name`` field (usually alongside ``version``). The generic OpenAI
    ``/v1/models`` list has no such field, so keying on ``system_name`` avoids
    treating every relay's model list as a family signal.

    Returns (is_oneapi_status, version).
    """
    stripped = (body or "").lstrip()
    if not stripped.startswith("{"):
        return False, ""
    try:
        data = json.loads(stripped[:100_000])
    except (ValueError, TypeError):
        return False, ""
    if not isinstance(data, dict):
        return False, ""
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    if not isinstance(payload, dict):
        return False, ""
    if "system_name" not in payload and "systemName" not in payload:
        return False, ""
    version = payload.get("version") or payload.get("Version") or ""
    return True, str(version)[:40]


def classify(domain: str, fetches: Iterable[FetchResult]) -> dict[str, str]:
    fork_hits: dict[str, list[str]] = {}      # tier 1: stack -> evidence
    fork_family: dict[str, str] = {}          # stack -> family
    family_hits: dict[str, list[str]] = {}    # tier 2: family -> evidence
    domain_hits: dict[str, str] = {}          # tier 3: stack -> family
    infra_hits: list[str] = []
    probed_paths: list[str] = []
    statuses: list[str] = []
    final_urls: list[str] = []
    errors: list[str] = []
    versions: list[str] = []
    spa_shell = False

    def add_fork(stack: str, family: str, evidence: str) -> None:
        fork_hits.setdefault(stack, []).append(evidence)
        fork_family[stack] = family

    def add_family(family: str, evidence: str) -> None:
        family_hits.setdefault(family, []).append(evidence)

    # Tier 3 — domain-name hints (recorded, never promoted above "low").
    for stack, family, pattern in DOMAIN_PATTERNS:
        if pattern.search(domain):
            domain_hits[stack] = family

    for result in fetches:
        probed_paths.append(urlparse(result.url).path or "/")
        if result.status:
            statuses.append(result.status)
        if result.final_url:
            final_urls.append(result.final_url)
        if result.error:
            errors.append(f"{result.url}:{result.error}")

        headers = result.headers or {}
        for key, value in headers.items():
            for stack, family, pattern in FORK_HEADER_PATTERNS:
                if pattern.search(key):
                    add_fork(stack, family, f"header:{key}={value[:80]}")
                    if key.lower() == "x-new-api-version" and value.strip():
                        versions.append(value.strip()[:40])
            for infra, source, key_pattern, value_pattern in INFRA_PATTERNS:
                if source != "header":
                    continue
                if not key_pattern.search(key):
                    continue
                if value_pattern is None or value_pattern.search(value):
                    infra_hits.append(f"{infra}:header:{key}={value[:80]}")

        body = result.body or ""

        # Tier 2 — one-api-family /api/status JSON envelope (+ version).
        is_status, version = _parse_status_json(body)
        if is_status:
            add_family("one-api-family", "json:/api/status system_name")
            if version:
                versions.append(version)

        title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
        body_sample = " ".join([title, body[:200_000]])

        for stack, family, pattern in FORK_BODY_PATTERNS:
            match = pattern.search(body_sample)
            if match:
                add_fork(stack, family, f"body:{match.group(0)[:100]}")

        for family, pattern in FAMILY_BODY_PATTERNS:
            match = pattern.search(body_sample)
            if match:
                add_family(family, f"body:{match.group(0)[:100]}")

        for infra, source, pattern, _ in INFRA_PATTERNS:
            if source == "body" and pattern.search(body_sample):
                match = pattern.search(body_sample)
                evidence = match.group(0) if match else pattern.pattern
                infra_hits.append(f"{infra}:body:{evidence[:80]}")

        if SPA_SHELL_RE.search(body):
            spa_shell = True

    forks = sorted(fork_hits)
    families = sorted({fork_family[s] for s in forks} | set(family_hits))
    version = next((v for v in versions if v), "")

    blocked = any(hit.startswith("cloudflare_challenge") for hit in infra_hits)
    reachable = bool(statuses)

    # ── label + confidence + status bucket ────────────────────────────────
    # A fork label is emitted ONLY when a tier-1 signal fired. Tier-2 stops at
    # the family; tier-3 (domain) stays "low". The three unknown sub-buckets
    # (unreachable / blocked / spa_shell / unidentified) are kept distinct so
    # "not identified" no longer collapses live-but-hidden sites into dead ones.
    if forks:
        app_stack, confidence, status_class = "|".join(forks), "high", "identified"
    elif family_hits:
        app_stack, confidence, status_class = "|".join(sorted(family_hits)), "family", "family_only"
    elif domain_hits:
        app_stack, confidence = "|".join(sorted(domain_hits)), "low"
        status_class = "blocked" if blocked else "domain_hint"
    else:
        app_stack, confidence = "unknown", "none"
        if not reachable:
            status_class = "unreachable"
        elif blocked:
            status_class = "blocked"
        elif spa_shell:
            status_class = "spa_shell"
        else:
            status_class = "unidentified"

    evidence_items: list[str] = []
    for stack in forks:
        evidence_items.extend(fork_hits[stack][:2])
    for family in sorted(family_hits):
        evidence_items.extend(family_hits[family][:2])
    if not forks and not family_hits:
        evidence_items.extend(f"domain:{s}" for s in sorted(domain_hits))
    evidence_items.extend(sorted(set(infra_hits))[:5])

    return {
        "domain": domain,
        "app_stack_guess": app_stack,
        "app_family": "|".join(families) or "unknown",
        "confidence": confidence,
        "status_class": status_class,
        "version": version,
        "infrastructure_signals": "|".join(sorted(set(hit.split(":", 1)[0] for hit in infra_hits))),
        "http_statuses": "|".join(statuses),
        "final_urls": "|".join(dict.fromkeys(final_urls)),
        "evidence": " ; ".join(evidence_items),
        "probed_paths": "|".join(dict.fromkeys(probed_paths)),
        "errors": " ; ".join(errors[:3]),
    }


def probe_site(site: dict[str, str], paths: list[str], timeout: float, insecure: bool) -> dict[str, str]:
    input_value = site.get("input_url") or site["domain"]
    base_url = normalize_url(input_value)
    domain = site["domain"] or domain_from_url(base_url)
    context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
    fetches: list[FetchResult] = []
    for i, path in enumerate(paths):
        result = fetch_url(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), timeout, context)
        fetches.append(result)
        # If the homepage itself is unreachable, don't grind the remaining
        # paths — a dead/blackhole site then costs one timeout, not six.
        if i == 0 and result.error and not result.status:
            break
    row = classify(domain, fetches)
    row["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row["platform_name"] = site.get("platform_name", "")
    row["source"] = site.get("source", "")
    row["input_url"] = input_value
    row["normalized_url"] = base_url
    return row


def self_test() -> None:
    # Each case asserts (exact app_stack_guess, confidence, status_class) plus an
    # optional predicate. The first four lock down the three reproduced bugs.
    cases = [
        # 1. new-api fork header + residual "one-api" branding -> single fork
        #    label (NOT "new-api|one-api"), family resolved, version extracted.
        (
            "https://relay.test",
            [FetchResult("https://relay.test/", status="200",
                         headers={"x-new-api-version": "v0.8.1"},
                         body="<title>New API</title> powered by one-api core")],
            "new-api", "high", "identified",
            lambda r: r["app_family"] == "one-api-family" and r["version"] == "v0.8.1",
        ),
        # 2. real sub2api site -> "sub2api" only, no spurious xxx2api co-label.
        (
            "https://sub.test",
            [FetchResult("https://sub.test/", status="200", headers={"server": "nginx"},
                         body="<title>Sub2API - Subscription to API Conversion Platform</title>")],
            "sub2api", "high", "identified",
            lambda r: "xxx2api" not in r["app_stack_guess"],
        ),
        # 3. benign "any2api" marketing text -> NOT labeled xxx2api; unidentified.
        (
            "https://random-relay.test",
            [FetchResult("https://random-relay.test/", status="200", headers={},
                         body="<title>Fast Relay</title> we support any2api conversion")],
            "unknown", "none", "unidentified",
            lambda r: "2api" not in r["app_stack_guess"],
        ),
        # 4. family-only signal (hyphenated one-api, no fork/header) -> stops at
        #    family; must not guess new-api vs one-api.
        (
            "https://fam.test",
            [FetchResult("https://fam.test/", status="200", headers={},
                         body="<title>Relay</title> built on one-api")],
            "one-api-family", "family", "family_only", None,
        ),
        # 5. React SPA empty shell -> spa_shell bucket, not unidentified/unknown.
        (
            "https://spa.test",
            [FetchResult("https://spa.test/", status="200", headers={"server": "nginx"},
                         body='<div id="root"></div><script src="/assets/index-a1b2.js"></script>')],
            "unknown", "none", "spa_shell", None,
        ),
        # 6. Cloudflare challenge -> blocked bucket (alive-but-hidden, not dead).
        (
            "https://blk.test",
            [FetchResult("https://blk.test/", status="403",
                         headers={"server": "cloudflare", "cf-ray": "abc"},
                         body="<title>Just a moment...</title>")],
            "unknown", "none", "blocked", None,
        ),
        # 7. /api/status JSON envelope -> family + version, no HTML branding.
        (
            "https://json.test",
            [FetchResult("https://json.test/api/status", status="200", headers={},
                         body='{"success":true,"data":{"system_name":"My Relay","version":"v0.6.7"}}')],
            "one-api-family", "family", "family_only",
            lambda r: r["version"] == "v0.6.7",
        ),
        # 8. completely unreachable -> unreachable bucket.
        (
            "https://dead.test",
            [FetchResult("https://dead.test/", error="URLError:timed out")],
            "unknown", "none", "unreachable", None,
        ),
    ]
    for domain, fetches, exp_stack, exp_conf, exp_status, pred in cases:
        row = classify(domain_from_url(domain), fetches)
        assert row["app_stack_guess"] == exp_stack, (domain, "stack", row)
        assert row["confidence"] == exp_conf, (domain, "conf", row)
        assert row["status_class"] == exp_status, (domain, "status", row)
        if pred is not None:
            assert pred(row), (domain, "pred", row)
    print("self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="CSV or newline-delimited URL/domain file. Defaults to data/hvoy_latest.csv + data/manual_sites.csv")
    parser.add_argument("--out", default="results/tech_stack_fingerprints.csv")
    parser.add_argument("--paths", default=",".join(DEFAULT_PATHS), help="Comma-separated paths to probe")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--sleep", type=float, default=0.2, help="Delay between sites")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    inputs = read_inputs(Path(args.input)) if args.input else load_default_platforms()
    if args.limit > 0:
        inputs = inputs[: args.limit]
    paths = [path.strip() for path in args.paths.split(",") if path.strip()]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "checked_at",
        "domain",
        "platform_name",
        "source",
        "input_url",
        "normalized_url",
        "app_stack_guess",
        "app_family",
        "confidence",
        "status_class",
        "version",
        "infrastructure_signals",
        "http_statuses",
        "final_urls",
        "evidence",
        "probed_paths",
        "errors",
    ]

    # resume: skip domains already in the output file, append to it.
    done = set()
    if out_path.exists():
        with out_path.open(encoding="utf-8-sig", newline="") as fh:
            done = {r.get("domain", "") for r in csv.DictReader(fh)}
    mode = "a" if done else "w"
    with out_path.open(mode, encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not done:
            writer.writeheader()
        for index, input_value in enumerate(inputs, 1):
            dom = input_value.get("domain", "") if isinstance(input_value, dict) else str(input_value)
            if dom in done:
                continue
            row = probe_site(input_value, paths, args.timeout, args.insecure)
            writer.writerow(row)
            handle.flush()
            print(f"[{index}/{len(inputs)}] {row['domain']} -> {row['app_stack_guess']} ({row['confidence']})")
            if args.sleep:
                time.sleep(args.sleep)

    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
