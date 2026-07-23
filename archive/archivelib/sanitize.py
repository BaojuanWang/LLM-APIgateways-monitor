"""Sanitization and secret detection for anything that may leave the disk.

Two distinct jobs live here:

1. **Reduction** — turn rich browser observations into the narrow set of fields
   the project is willing to keep outside the WACZ (network summaries, browser
   state *names*, redacted URLs, normalized paths).
2. **Detection** — scan candidate public output for material that must never be
   published (credentials, cookies, absolute local paths, private keys).

Detection is a backstop, not the primary control. The primary control is that
reduction only ever *adds* an allowlisted field; it never copies a whole record.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# ---------------------------------------------------------------------------
# URL and path redaction
# ---------------------------------------------------------------------------

REDACTED_QUERY = "[REDACTED_QUERY]"
REDACTED_FRAGMENT = "[REDACTED_FRAGMENT]"


def redact_url(url: str, *, keep_query_keys: bool = False) -> str:
    """Strip userinfo and query values from a URL.

    Query strings on gateway sites routinely carry invite codes, referral ids,
    and session tokens, so the value side is dropped unconditionally. With
    ``keep_query_keys`` the *names* survive, which is often enough to tell a
    pricing page from a login redirect.
    """
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[UNPARSEABLE_URL]"

    netloc = parts.netloc
    if "@" in netloc:  # drop user:password@
        netloc = netloc.rsplit("@", 1)[1]

    query = ""
    if parts.query:
        if keep_query_keys:
            keys = []
            for pair in parts.query.split("&"):
                if not pair:
                    continue
                keys.append(pair.split("=", 1)[0])
            query = f"{REDACTED_QUERY}:{','.join(keys)}" if keys else REDACTED_QUERY
        else:
            query = REDACTED_QUERY

    fragment = REDACTED_FRAGMENT if parts.fragment else ""
    return urlunsplit((parts.scheme, netloc, parts.path, query, fragment))


def normalize_local_path(value: str, *, root: Path | None = None, label: str = "ARCHIVE_ROOT") -> str:
    """Replace machine-specific absolute paths with stable placeholders.

    Public metadata must not disclose the operator's username or disk layout.
    """
    if not value:
        return value
    text = str(value)
    if root is not None:
        text = text.replace(str(Path(root).resolve()), f"${label}")
        text = text.replace(str(root), f"${label}")
    home = str(Path.home())
    text = text.replace(home, "$HOME")
    text = re.sub(r"/Users/[^/\s\"']+", "/Users/$USER", text)
    text = re.sub(r"/home/[^/\s\"']+", "/home/$USER", text)
    text = re.sub(r"/Volumes/[^/\s\"']+", "/Volumes/$ARCHIVE_VOLUME", text)
    return text


# ---------------------------------------------------------------------------
# Network summary
# ---------------------------------------------------------------------------

NETWORK_SUMMARY_FIELDS = (
    "timestamp_utc",
    "url",
    "method",
    "resource_type",
    "status",
    "mime_type",
    "redirected_from",
    "redirected_to",
    "timing_ms",
    "response_bytes",
    "failure_category",
)

# Coarse buckets: enough to reason about blocking and breakage, not enough to
# reconstruct a request.
FAILURE_CATEGORIES = (
    "dns",
    "connection",
    "tls",
    "timeout",
    "aborted",
    "blocked",
    "http_error",
    "other",
)


def classify_failure(error_text: str | None) -> str | None:
    if not error_text:
        return None
    err = str(error_text).lower()
    if any(k in err for k in ("name_not_resolved", "dns", "nameresolution")):
        return "dns"
    if any(k in err for k in ("connection_refused", "connection_reset", "connection_closed", "econnrefused")):
        return "connection"
    if any(k in err for k in ("cert", "ssl", "tls", "handshake")):
        return "tls"
    if "timed" in err or "timeout" in err:
        return "timeout"
    if "abort" in err or "cancel" in err:
        return "aborted"
    if "blocked" in err or "denied" in err:
        return "blocked"
    return "other"


def sanitized_network_record(
    *,
    timestamp_utc: str,
    url: str,
    method: str = "",
    resource_type: str = "",
    status: int | None = None,
    mime_type: str = "",
    redirected_from: str = "",
    redirected_to: str = "",
    timing_ms: float | None = None,
    response_bytes: int | None = None,
    failure_category: str | None = None,
) -> dict:
    """Build one network-summary row containing only allowlisted fields.

    Constructed field-by-field on purpose: there is no code path that copies a
    Playwright request/response object wholesale, so headers and bodies cannot
    leak by omission.
    """
    return {
        "timestamp_utc": timestamp_utc,
        "url": redact_url(url, keep_query_keys=True),
        "method": (method or "").upper()[:12],
        "resource_type": (resource_type or "")[:32],
        "status": int(status) if isinstance(status, int) else None,
        "mime_type": (mime_type or "").split(";")[0][:96],
        "redirected_from": redact_url(redirected_from) if redirected_from else "",
        "redirected_to": redact_url(redirected_to) if redirected_to else "",
        # Playwright reports -1 when a phase never completed; that is "unknown",
        # not a duration, so it must not be recorded as one.
        "timing_ms": (
            round(float(timing_ms), 2)
            if isinstance(timing_ms, (int, float)) and not isinstance(timing_ms, bool) and timing_ms >= 0
            else None
        ),
        "response_bytes": int(response_bytes) if isinstance(response_bytes, int) else None,
        "failure_category": failure_category if failure_category in FAILURE_CATEGORIES else failure_category or None,
    }


def browser_state_names(*, cookies: list, local_storage_keys: list, session_storage_keys: list) -> dict:
    """Inventory of browser state *names* — never values.

    Knowing that a site sets ``session`` and ``cf_clearance`` is analytically
    useful; the values are credentials and stay in the WACZ.
    """
    cookie_entries = []
    for cookie in cookies or []:
        if isinstance(cookie, dict):
            cookie_entries.append(
                {
                    "name": str(cookie.get("name", ""))[:128],
                    "domain": str(cookie.get("domain", ""))[:253],
                    "path": str(cookie.get("path", ""))[:128],
                    "http_only": bool(cookie.get("httpOnly", False)),
                    "secure": bool(cookie.get("secure", False)),
                    "same_site": str(cookie.get("sameSite", ""))[:16],
                    "session": cookie.get("expires", -1) in (-1, None) or cookie.get("expires", -1) < 0,
                }
            )
        else:
            cookie_entries.append({"name": str(cookie)[:128]})
    return {
        "policy": "names and non-secret attributes only; values are never recorded here",
        "cookie_names": sorted(cookie_entries, key=lambda c: (c.get("domain", ""), c.get("name", ""))),
        "local_storage_keys": sorted({str(k)[:256] for k in (local_storage_keys or [])}),
        "session_storage_keys": sorted({str(k)[:256] for k in (session_storage_keys or [])}),
    }


# ---------------------------------------------------------------------------
# Secret detection
# ---------------------------------------------------------------------------


@dataclass
class SecretFinding:
    path: str
    line: int
    rule: str
    excerpt: str

    def as_dict(self) -> dict:
        return {"path": self.path, "line": self.line, "rule": self.rule, "excerpt": self.excerpt}


# Rules are intentionally broad; the public export is small and structured, so
# false positives are cheap to review and a miss is not.
SECRET_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("authorization_header", re.compile(r"(?i)\bauthorization\s*[:=]\s*\S")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{8,}")),
    ("set_cookie_header", re.compile(r"(?i)\bset-cookie\s*[:=]\s*\S")),
    ("cookie_header", re.compile(r"(?i)\bcookie\s*[:=]\s*\S")),
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("anthropic_style_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("api_key_assignment", re.compile(r"(?i)\b(api[_-]?key|apikey|access[_-]?token|secret[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}")),
    ("password_assignment", re.compile(r"(?i)\bpass(?:word|wd)\s*[:=]\s*['\"]?\S{4,}")),
    ("absolute_user_path", re.compile(r"/(?:Users|home)/(?!\$USER\b)[A-Za-z0-9._-]+/")),
    ("absolute_volume_path", re.compile(r"/Volumes/(?!\$ARCHIVE_VOLUME\b)[^\s\"',]+")),
)

# Extensions that must never appear in the public export at all.
FORBIDDEN_PUBLIC_EXTENSIONS = frozenset(
    {".wacz", ".warc", ".gz", ".cdxj", ".cdx", ".html", ".htm", ".png", ".jpg", ".jpeg", ".webp", ".pdf", ".har"}
)

TEXT_SCAN_MAX_BYTES = 8 * 1024 * 1024


def scan_text_for_secrets(text: str, path_label: str = "<text>") -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule_name, pattern in SECRET_RULES:
            match = pattern.search(line)
            if match:
                excerpt = match.group(0)
                if len(excerpt) > 24:
                    excerpt = excerpt[:12] + "…[TRUNCATED]"
                findings.append(SecretFinding(path=path_label, line=lineno, rule=rule_name, excerpt=excerpt))
    return findings


def scan_file_for_secrets(path: Path, *, base: Path | None = None) -> list[SecretFinding]:
    label = str(path.relative_to(base)) if base and path.is_relative_to(base) else str(path)
    try:
        if path.stat().st_size > TEXT_SCAN_MAX_BYTES:
            return [SecretFinding(path=label, line=0, rule="file_too_large_to_scan", excerpt="")]
        text = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return [SecretFinding(path=label, line=0, rule="binary_file_in_public_export", excerpt="")]
    except OSError as exc:
        return [SecretFinding(path=label, line=0, rule="unreadable_file", excerpt=str(exc)[:40])]
    return scan_text_for_secrets(text, label)


def scan_public_export(directory: Path) -> dict:
    """Full gate over ``data/archive_public/``.

    Returns a report rather than raising so callers can print every problem at
    once instead of fixing them one exception at a time.
    """
    directory = Path(directory)
    findings: list[SecretFinding] = []
    forbidden: list[str] = []
    scanned: list[str] = []

    if not directory.exists():
        return {"ok": True, "scanned_files": [], "findings": [], "forbidden_files": [], "note": "public export directory absent"}

    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames.sort()
        for name in sorted(filenames):
            entry = Path(dirpath) / name
            rel = str(entry.relative_to(directory))
            if entry.is_symlink():
                forbidden.append(f"{rel} (symlink)")
                continue
            suffix = entry.suffix.lower()
            if suffix in FORBIDDEN_PUBLIC_EXTENSIONS and name != "README.md":
                forbidden.append(f"{rel} (forbidden extension {suffix})")
                continue
            scanned.append(rel)
            findings.extend(scan_file_for_secrets(entry, base=directory))

    return {
        "ok": not findings and not forbidden,
        "scanned_files": scanned,
        "findings": [f.as_dict() for f in findings],
        "forbidden_files": forbidden,
    }
