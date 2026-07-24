"""Local longitudinal web-archival subsystem for the LLM API gateway monitor.

This package implements the *local full-capture layer*. The six-hour GitHub
Actions monitor remains the lightweight change detector; nothing here replaces
it, and nothing here writes raw archival material into the Git repository.

Layering:

    raw        -> WACZ/WARC + rendered browser output. Lives ONLY under
                  $ARCHIVE_ROOT on a verified external volume. Sensitive.
    derived    -> manifests, validation reports, sanitized network summaries.
                  Local, machine-generated from raw.
    public     -> sanitized metadata under data/archive_public/ in Git.

The canonical archival artifact is the WACZ. SingleFile HTML and standalone
screenshots are secondary representations and are never treated as a
replacement for the WACZ.
"""

__all__ = ["ARCHIVE_SUBSYSTEM_VERSION"]

ARCHIVE_SUBSYSTEM_VERSION = "0.1.0"
