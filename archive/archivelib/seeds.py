"""Bounded, same-service seed discovery.

Two sources feed the seed list:

1. Links found on the service's own homepage.
2. A short, explicit list of conventional paths (``/pricing``, ``/docs``, …).

That second list is *not* directory brute-forcing: each path is requested at
most once, misses are recorded as ``present: false`` and never permuted or
retried, and the list never grows at runtime. Missing page types are reported as
missing rather than invented — a fabricated ``/pricing`` URL would be worse than
no pricing page, because it would look like evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests
import urllib3

from .envmeta import utc_now_iso
from .identity import normalize_host
from .sanitize import redact_url

# Page types the project cares about, in capture priority order. Homepage is
# always seed #1; the rest fill remaining slots in this order.
PAGE_TYPES = (
    "homepage",
    "pricing",
    "model_list",
    "documentation",
    "login",
    "registration",
    "public_status",
    "terms",
    "privacy_policy",
    "announcements",
)

# Path/anchor-text signals per page type. Matching is deliberately conservative:
# a wrong label is a data-quality bug that propagates into the corpus.
_TYPE_SIGNALS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "login": (("/login", "/signin", "/sign-in", "/auth/login", "/user/login"), ("login", "sign in", "登录", "登入")),
    "registration": (("/register", "/signup", "/sign-up", "/user/register"), ("register", "sign up", "注册")),
    "pricing": (("/pricing", "/price", "/prices", "/plan", "/plans", "/billing", "/topup", "/recharge"), ("pricing", "price", "plans", "价格", "定价", "充值", "套餐")),
    "documentation": (("/docs", "/doc", "/documentation", "/api-docs", "/developer", "/guide", "/help"), ("docs", "documentation", "api doc", "文档", "开发文档", "帮助")),
    "model_list": (("/models", "/model", "/pricing/models", "/v1/models", "/api/models"), ("models", "model list", "模型", "模型列表")),
    "public_status": (("/status", "/uptime", "/health", "/api/status"), ("status", "uptime", "状态", "监控")),
    "privacy_policy": (("/privacy", "/privacy-policy", "/legal/privacy"), ("privacy", "隐私", "隐私政策")),
    "terms": (("/terms", "/tos", "/terms-of-service", "/legal/terms", "/agreement"), ("terms", "tos", "条款", "服务协议", "用户协议")),
    "announcements": (("/announcement", "/announcements", "/notice", "/news", "/blog", "/changelog", "/updates"), ("announcement", "news", "changelog", "公告", "通知", "更新")),
}

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Many services in this inventory have expired, self-signed, or mismatched
# certificates. That is itself an observation worth recording, and refusing to
# look would bias the corpus toward well-maintained sites — so verification is
# off for discovery and the resulting warning is silenced rather than printed
# once per request. Nothing is ever *sent* to these hosts, so the usual risk of
# disabled verification does not apply.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Reserve at most this many of the seed slots for API endpoints, so page types
# are never crowded out by machine endpoints.
MAX_API_SEEDS = 2


class _LinkParser(HTMLParser):
    """Minimal anchor extractor: href plus visible text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._current_href = href
            self._text_parts = []

    def handle_data(self, data):
        if self._current_href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._current_href is not None:
            text = re.sub(r"\s+", " ", "".join(self._text_parts)).strip()[:120]
            self.links.append((self._current_href, text))
            self._current_href = None
            self._text_parts = []


@dataclass
class SeedCandidate:
    url: str
    page_type: str
    origin: str  # "homepage" | "known_path" | "api_path" | "canonical"
    evidence: str = ""
    http_status: int | None = None
    present: bool = True

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "page_type": self.page_type,
            "origin": self.origin,
            "evidence": self.evidence,
            "http_status": self.http_status,
            "present": self.present,
        }


@dataclass
class SeedPlan:
    service_id: str
    host: str
    canonical_url: str
    seeds: list[SeedCandidate] = field(default_factory=list)
    missing_page_types: list[str] = field(default_factory=list)
    probed: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    discovered_at_utc: str = ""

    @property
    def seed_urls(self) -> list[str]:
        return [s.url for s in self.seeds]

    def as_dict(self) -> dict:
        return {
            "service_id": self.service_id,
            "host": self.host,
            "canonical_url": self.canonical_url,
            "discovered_at_utc": self.discovered_at_utc,
            "seed_count": len(self.seeds),
            "seeds": [s.as_dict() for s in self.seeds],
            "missing_page_types": sorted(self.missing_page_types),
            "probe_results": self.probed,
            "errors": self.errors,
        }


def _same_service(url: str, host: str) -> bool:
    """True when ``url`` belongs to this host or a subdomain of it.

    Host-level identity is preserved: we do not treat an unrelated eTLD+1
    sibling as the same service.
    """
    try:
        candidate = normalize_host(url)
    except Exception:
        return False
    return candidate == host or candidate.endswith("." + host)


def classify_url(url: str, anchor_text: str = "") -> str | None:
    """Label a URL with a page type, strongest evidence first.

    Three passes in descending confidence: exact path, shallow prefix, anchor
    text. Depth limits matter — ``/blog`` is the announcements index, but
    ``/blog/2024/01/our-pricing-explained`` is one post and is neither the
    announcements index nor the pricing page. Seeds should be the index pages,
    and a mislabeled seed becomes a data-quality bug in the corpus.
    """
    path = (urlsplit(url).path or "/").lower().rstrip("/") or "/"
    text = (anchor_text or "").lower()
    if path == "/":
        return "homepage"
    depth = path.count("/")

    for page_type, (paths, _words) in _TYPE_SIGNALS.items():
        if path in paths:
            return page_type

    for page_type, (paths, _words) in _TYPE_SIGNALS.items():
        for candidate in paths:
            if path.startswith(candidate + "/") or path.startswith(candidate + "."):
                if depth <= candidate.count("/") + 1:
                    return page_type

    if depth <= 2:
        for page_type, (_paths, words) in _TYPE_SIGNALS.items():
            if any(word and word in text for word in words):
                return page_type
    return None


def extract_links(html: str, base_url: str, host: str, limit: int) -> list[tuple[str, str]]:
    parser = _LinkParser()
    try:
        parser.feed(html)
    except Exception:
        return []
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for href, text in parser.links:
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            continue
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https"):
            continue
        if not _same_service(absolute, host):
            continue
        # Normalize away query and fragment: seeds are pages, not parameterized
        # views, and query strings on these sites often carry referral ids.
        clean = f"{parts.scheme}://{parts.netloc}{parts.path or '/'}"
        if clean in seen:
            continue
        seen.add(clean)
        out.append((clean, text))
        if len(out) >= limit:
            break
    return out


def _probe(session: requests.Session, url: str, timeout: int) -> tuple[int | None, str]:
    """One GET, no retries, no credentials, no auth headers."""
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True, verify=False)
        return resp.status_code, ""
    except requests.RequestException as exc:
        return None, type(exc).__name__


def discover_seeds(
    *,
    service_id: str,
    host: str,
    canonical_url: str,
    cfg: dict,
    session: requests.Session | None = None,
    probe_known_paths: bool = True,
) -> SeedPlan:
    """Build a bounded seed plan for one service.

    Never sends an API key, never submits a form, never follows a logout link.
    """
    seed_cfg = cfg.get("seeds", {})
    max_seeds = int(cfg.get("capture", {}).get("max_seeds", 8))
    timeout = int(seed_cfg.get("link_discovery_timeout_seconds", 30))
    max_links = int(seed_cfg.get("max_link_candidates", 200))

    plan = SeedPlan(
        service_id=service_id,
        host=host,
        canonical_url=canonical_url,
        discovered_at_utc=utc_now_iso(),
    )

    owns_session = session is None
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": DEFAULT_UA})
    # Explicitly refuse any ambient credentials.
    session.auth = None
    session.cookies.clear()

    try:
        # Homepage is always the canonical first seed, present or not: its
        # failure is itself the observation we want recorded.
        plan.seeds.append(
            SeedCandidate(url=canonical_url, page_type="homepage", origin="canonical", evidence="canonical start URL")
        )

        html = ""
        try:
            resp = session.get(canonical_url, timeout=timeout, allow_redirects=True, verify=False)
            plan.seeds[0].http_status = resp.status_code
            content_type = resp.headers.get("Content-Type", "")
            if "html" in content_type.lower():
                html = resp.text[:2_000_000]
        except requests.RequestException as exc:
            plan.errors.append(f"homepage fetch failed: {type(exc).__name__}")
            plan.seeds[0].present = False

        by_type: dict[str, SeedCandidate] = {"homepage": plan.seeds[0]}

        # --- source 1: links on the homepage ---------------------------
        for url, text in extract_links(html, canonical_url, host, max_links):
            page_type = classify_url(url, text)
            if not page_type or page_type == "homepage" or page_type in by_type:
                continue
            by_type[page_type] = SeedCandidate(
                url=url,
                page_type=page_type,
                origin="homepage",
                evidence=f"homepage link (anchor: {text[:60]!r})" if text else "homepage link",
            )

        # --- source 2: the short explicit known-path list ---------------
        if probe_known_paths:
            for path in seed_cfg.get("known_paths", []):
                page_type = classify_url(urljoin(canonical_url, path))
                if not page_type or page_type in by_type:
                    continue
                url = urljoin(canonical_url, path)
                status, err = _probe(session, url, timeout)
                plan.probed.append(
                    {"url": redact_url(url), "status": status, "error": err, "kind": "known_path"}
                )
                if status is not None and status < 400:
                    by_type[page_type] = SeedCandidate(
                        url=url,
                        page_type=page_type,
                        origin="known_path",
                        evidence=f"known path probe returned {status}",
                        http_status=status,
                    )

        # --- source 3: public unauthenticated API paths -----------------
        api_seeds: list[SeedCandidate] = []
        if seed_cfg.get("include_api_paths", True) and probe_known_paths:
            for path in seed_cfg.get("api_paths", []):
                if len(api_seeds) >= MAX_API_SEEDS:
                    break
                url = urljoin(canonical_url, path)
                if any(s.url == url for s in by_type.values()):
                    continue
                status, err = _probe(session, url, timeout)
                plan.probed.append(
                    {"url": redact_url(url), "status": status, "error": err, "kind": "api_path"}
                )
                if status is not None and status < 400:
                    api_seeds.append(
                        SeedCandidate(
                            url=url,
                            page_type="public_api",
                            origin="api_path",
                            evidence=f"public unauthenticated endpoint returned {status} (no key supplied)",
                            http_status=status,
                        )
                    )

        # --- assemble under the cap -------------------------------------
        ordered: list[SeedCandidate] = [by_type["homepage"]]
        for page_type in PAGE_TYPES:
            if page_type == "homepage":
                continue
            if page_type in by_type and len(ordered) < max_seeds - min(len(api_seeds), MAX_API_SEEDS):
                ordered.append(by_type[page_type])
        for api_seed in api_seeds:
            if len(ordered) < max_seeds:
                ordered.append(api_seed)

        plan.seeds = ordered
        plan.missing_page_types = [t for t in PAGE_TYPES if t not in by_type]
        return plan
    finally:
        if owns_session:
            session.close()


def discovery_evidence_record(
    *,
    service_id: str,
    identity,
    plan: SeedPlan,
    reason: str,
    prior_monitor_state: dict | None,
    source_fingerprint: dict,
) -> dict:
    """One JSONL line documenting why this capture happened and how it was scoped."""
    return {
        "recorded_at_utc": utc_now_iso(),
        "service_id": service_id,
        "host": identity.host,
        "source_dataset": identity.inventory_file,
        "source_dataset_sha256": identity.inventory_file_sha256,
        "source_identifier": identity.inventory_row.get("domain", ""),
        "source_query_or_category": (
            identity.inventory_row.get("discovery_methods")
            or identity.inventory_row.get("origin")
            or identity.inventory_row.get("source")
            or ""
        ),
        "inventory_row_sha256": identity.inventory_row_sha256,
        "prior_monitor_state": prior_monitor_state,
        "monitor_source": source_fingerprint,
        "capture_reason": reason,
        "seed_discovery": plan.as_dict(),
    }
