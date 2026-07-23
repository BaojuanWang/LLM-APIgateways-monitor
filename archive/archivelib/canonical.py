"""Canonical serialization and hashing primitives.

Every digest in this subsystem is computed over a *canonical* representation so
that the same bytes always yield the same digest on any machine: JSON with
sorted keys, no insignificant whitespace, ASCII escaping, and UTF-8 encoding.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CHUNK_SIZE = 1024 * 1024


def canonical_json(obj: Any) -> str:
    """Serialize ``obj`` deterministically.

    ``ensure_ascii=True`` keeps the output byte-identical regardless of the
    filesystem or terminal encoding in use, which matters because these strings
    are hashed.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def canonical_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_json(obj: Any) -> str:
    """SHA256 of the canonical JSON form of ``obj``."""
    return sha256_bytes(canonical_bytes(obj))


def sha256_file(path: Path | str) -> str:
    """Streaming SHA256 so multi-GB WACZ files never land in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def short_hash(obj: Any, length: int = 12) -> str:
    """Short, collision-resistant tag derived from canonical JSON."""
    if length < 8 or length > 64:
        raise ValueError("short_hash length must be between 8 and 64")
    return sha256_json(obj)[:length]


def write_json(path: Path, obj: Any, *, indent: int = 2) -> None:
    """Write human-readable JSON with a trailing newline.

    Readability wins here because these files are read by researchers; the
    canonical form is only used for hashing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, indent=indent, sort_keys=True, ensure_ascii=False, default=str)
        handle.write("\n")


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)
