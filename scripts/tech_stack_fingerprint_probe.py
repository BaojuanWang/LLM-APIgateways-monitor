#!/usr/bin/env python3
"""Probe LLM API relay sites for application/infrastructure fingerprints.

The classifier is intentionally evidence-first. It separates application-layer
relay implementations (new-api, one-api, sub2api, auth2api, etc.) from
infrastructure-only signals such as Cloudflare and Nginx.
"""

from __future__ import annotations

import argparse
import csv
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


APP_PATTERNS = [
    ("new-api", "one-api-family", "header", re.compile(r"^x-new-api-version$", re.I), "high"),
    ("one-api", "one-api-family", "header", re.compile(r"^x-(oneapi|one-api)-", re.I), "high"),
    ("new-api", "one-api-family", "body", re.compile(r"\bnew[-_ ]?api\b|QuantumNous", re.I), "high"),
    ("one-api", "one-api-family", "body", re.compile(r"\bone[-_ ]?api\b|songquanpeng", re.I), "high"),
    ("veloera", "one-api-family", "body", re.compile(r"\bveloera\b", re.I), "high"),
    ("one-hub", "one-api-family", "body", re.compile(r"\bone[-_ ]?hub\b|\bdone[-_ ]?hub\b", re.I), "high"),
    ("voapi", "one-api-family", "body", re.compile(r"\bvoapi\b", re.I), "high"),
    ("shell-api", "one-api-family", "body", re.compile(r"\bshell[-_ ]?api\b", re.I), "medium"),
    ("super-api", "one-api-family", "body", re.compile(r"\bsuper[-_ ]?api\b", re.I), "medium"),
    ("neo-api", "one-api-family", "body", re.compile(r"\bneo[-_ ]?api\b", re.I), "medium"),
    ("sub2api", "subscription-to-api", "body", re.compile(r"\bsub2api\b|Subscription to API Conversion Platform", re.I), "high"),
    (
        "sub2api",
        "subscription-to-api",
        "body",
        re.compile(r"subscription\s+to\s+api|订阅.{0,24}(转|转换).{0,24}api|api.{0,24}(转|转换).{0,24}订阅|订阅.{0,24}api\s*key", re.I),
        "medium",
    ),
    ("auth2api", "oauth-to-api", "body", re.compile(r"\bauth2api\b|OAuth\s+to\s+API|Claude/Codex OAuth", re.I), "high"),
    ("cliproxyapi", "cli-proxy-api", "body", re.compile(r"\bcliproxyapi\b|\bcli[-_ ]?proxy[-_ ]?api\b", re.I), "high"),
    ("all-api-hub", "aggregator", "body", re.compile(r"\ball[-_ ]?api[-_ ]?hub\b", re.I), "high"),
    ("metapi", "aggregator", "body", re.compile(r"\bmetapi\b|meta[-_ ]?api", re.I), "high"),
    ("xxx2api", "conversion-layer", "body", re.compile(r"\b[a-z0-9_-]+2api\b", re.I), "medium"),
]


DOMAIN_PATTERNS = [
    ("new-api", "one-api-family", re.compile(r"newapi|new-api", re.I), "medium"),
    ("sub2api", "subscription-to-api", re.compile(r"sub2api|sub-2-api", re.I), "medium"),
    ("auth2api", "oauth-to-api", re.compile(r"auth2api|auth-2-api", re.I), "medium"),
    ("cliproxyapi", "cli-proxy-api", re.compile(r"cliproxyapi|cli-proxy-api", re.I), "medium"),
]


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


def classify(domain: str, fetches: Iterable[FetchResult]) -> dict[str, str]:
    app_hits: list[tuple[str, str, str, str]] = []
    infra_hits: list[str] = []
    probed_paths: list[str] = []
    statuses: list[str] = []
    final_urls: list[str] = []
    errors: list[str] = []

    for stack, family, pattern, strength in DOMAIN_PATTERNS:
        if pattern.search(domain):
            app_hits.append((stack, family, strength, f"domain:{domain}"))

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
            for stack, family, source, pattern, strength in APP_PATTERNS:
                if source == "header" and pattern.search(key):
                    app_hits.append((stack, family, strength, f"header:{key}={value[:80]}"))

            for infra, source, key_pattern, value_pattern in INFRA_PATTERNS:
                if source != "header":
                    continue
                if not key_pattern.search(key):
                    continue
                if value_pattern is None or value_pattern.search(value):
                    infra_hits.append(f"{infra}:header:{key}={value[:80]}")

        body = result.body or ""
        title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
        body_sample = " ".join([title, body[:200_000]])
        for stack, family, source, pattern, strength in APP_PATTERNS:
            if source == "body" and pattern.search(body_sample):
                match = pattern.search(body_sample)
                evidence = match.group(0) if match else pattern.pattern
                app_hits.append((stack, family, strength, f"body:{evidence[:100]}"))

        for infra, source, pattern, _ in INFRA_PATTERNS:
            if source == "body" and pattern.search(body_sample):
                match = pattern.search(body_sample)
                evidence = match.group(0) if match else pattern.pattern
                infra_hits.append(f"{infra}:body:{evidence[:80]}")

    dedup_app: dict[str, tuple[str, str, list[str]]] = {}
    for stack, family, strength, evidence in app_hits:
        current = dedup_app.setdefault(stack, (family, strength, []))
        family0, strength0, evidences = current
        if strength0 != "high" and strength == "high":
            strength0 = "high"
        elif strength0 == "low" and strength == "medium":
            strength0 = "medium"
        evidences.append(evidence)
        dedup_app[stack] = (family0, strength0, evidences)

    app_stacks = sorted(dedup_app)
    families = sorted({dedup_app[stack][0] for stack in app_stacks})
    strengths = [dedup_app[stack][1] for stack in app_stacks]
    if "high" in strengths:
        confidence = "high"
    elif "medium" in strengths:
        confidence = "medium"
    elif infra_hits:
        confidence = "low"
    else:
        confidence = "unknown"

    evidence_items: list[str] = []
    for stack in app_stacks:
        evidence_items.extend(dedup_app[stack][2][:3])
    evidence_items.extend(sorted(set(infra_hits))[:5])

    return {
        "domain": domain,
        "app_stack_guess": "|".join(app_stacks) or "unknown",
        "app_family": "|".join(families) or "unknown",
        "confidence": confidence,
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
    for path in paths:
        fetches.append(fetch_url(urljoin(base_url.rstrip("/") + "/", path.lstrip("/")), timeout, context))
    row = classify(domain, fetches)
    row["checked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    row["platform_name"] = site.get("platform_name", "")
    row["source"] = site.get("source", "")
    row["input_url"] = input_value
    row["normalized_url"] = base_url
    return row


def self_test() -> None:
    cases = [
        (
            "https://example.test",
            [FetchResult("https://example.test/", headers={"x-new-api-version": "v1.0.0-rc.18"}, body="<title>New API</title>")],
            "new-api",
            "high",
        ),
        (
            "https://sub2api.local",
            [FetchResult("https://sub2api.local/", headers={"server": "nginx"}, body="<title>Sub2API - Subscription to API Conversion Platform</title>")],
            "sub2api",
            "high",
        ),
        (
            "https://blocked.test",
            [FetchResult("https://blocked.test/", headers={"server": "cloudflare", "cf-ray": "abc"}, body="<title>Just a moment...</title>")],
            "unknown",
            "low",
        ),
    ]
    for domain, fetches, expected_stack, expected_confidence in cases:
        row = classify(domain_from_url(domain), fetches)
        assert expected_stack in row["app_stack_guess"], row
        assert row["confidence"] == expected_confidence, row
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
        "infrastructure_signals",
        "http_statuses",
        "final_urls",
        "evidence",
        "probed_paths",
        "errors",
    ]

    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, input_value in enumerate(inputs, 1):
            row = probe_site(input_value, paths, args.timeout, args.insecure)
            writer.writerow(row)
            print(f"[{index}/{len(inputs)}] {row['domain']} -> {row['app_stack_guess']} ({row['confidence']})")
            if args.sleep:
                time.sleep(args.sleep)

    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
