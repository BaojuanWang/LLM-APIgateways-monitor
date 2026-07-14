"""Shared domain-normalization helpers (stdlib only).

Two levels of normalization are provided:

* ``normalize_host`` — lower-cased hostname with scheme / path / port / userinfo
  stripped. Keeps the sub-domain (``api.toknex.ai`` stays ``api.toknex.ai``).
* ``registrable_domain`` — the eTLD+1 / "one site" key. ``api.toknex.ai``,
  ``www.toknex.ai`` and ``toknex.ai`` all collapse to ``toknex.ai``.

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
