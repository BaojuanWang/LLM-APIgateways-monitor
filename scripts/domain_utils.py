"""Shared domain-normalization helpers (stdlib only).

Two levels of normalization are provided:

* ``normalize_host`` — lower-cased hostname with scheme / path / port / userinfo
  stripped. Keeps the sub-domain (``api.toknex.ai`` stays ``api.toknex.ai``).
* ``registrable_domain`` — the eTLD+1 / "one site" key. ``api.toknex.ai``,
  ``www.toknex.ai`` and ``toknex.ai`` all collapse to ``toknex.ai``.
* ``is_valid_host`` — rejects placeholders, malformed labels, and bare IPs
  before a value enters the network-monitoring pipeline.

We deliberately avoid a public-suffix-list dependency; instead an embedded set
of common multi-label suffixes handles the ccTLDs that actually appear in this
dataset. Unknown multi-label suffixes fall back to the last two labels, which is
correct for the vast majority of gTLDs (.com/.ai/.io/.xyz/...).
"""

from __future__ import annotations

import re

# Two-label public suffixes seen in relay datasets (registrable = last 3 labels).
MULTI_LABEL_SUFFIXES = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "me.uk",
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn",
    "com.hk", "org.hk", "net.hk", "idv.hk",
    "com.tw", "org.tw", "net.tw",
    "com.sg", "com.my", "com.ph", "com.vn",
    "com.au", "net.au", "org.au", "com.br", "com.mx", "com.tr",
    "co.jp", "co.kr", "co.in", "co.id", "co.th", "co.nz", "co.za",
}

_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
_HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.I)
_PLACEHOLDER_HOSTS = {
    "hvoy_removed", "removed", "unknown", "none", "null", "n/a", "na",
}


def normalize_host(value: str) -> str:
    """Return the bare lower-cased hostname (sub-domain preserved)."""
    if not value:
        return ""
    v = str(value).strip().lower()
    v = _SCHEME_RE.sub("", v)          # drop scheme
    v = v.split("/", 1)[0]             # drop path
    v = v.split("?", 1)[0]             # drop query
    v = v.split("#", 1)[0]             # drop fragment
    v = v.split("@")[-1]               # drop userinfo
    v = v.split(":", 1)[0]             # drop port
    v = v.strip().strip(".")
    return v


def is_valid_host(value: str) -> bool:
    """Return True for a plausible DNS hostname suitable for network probing."""
    host = normalize_host(value)
    if not host or host in _PLACEHOLDER_HOSTS or len(host) > 253:
        return False
    if "." not in host or host.replace(".", "").isdigit():
        return False

    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return False

    labels = ascii_host.split(".")
    if len(labels[-1]) < 2:
        return False
    return all(_HOST_LABEL_RE.fullmatch(label) for label in labels)


def registrable_domain(value: str) -> str:
    """Return the eTLD+1 key used to collapse a site's hostnames into one row."""
    host = normalize_host(value)
    if not host or host.replace(".", "").isdigit():   # empty or bare IP
        return host
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    last_two = ".".join(labels[-2:])
    if last_two in MULTI_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return last_two
