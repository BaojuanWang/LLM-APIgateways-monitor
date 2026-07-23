"""Typed errors for the archive subsystem.

Every failure mode that could otherwise cause a silent fallback (writing raw
capture data somewhere unsafe, overwriting an existing capture, escaping the
corpus root) raises a distinct exception so callers fail closed instead of
degrading.
"""


class ArchiveError(Exception):
    """Base class for every archive-subsystem failure."""


class ArchiveRootError(ArchiveError):
    """$ARCHIVE_ROOT is missing, malformed, or not usable for this mode."""


class ExternalVolumeError(ArchiveError):
    """No unique, writable, external volume could be verified."""


class PathEscapeError(ArchiveError):
    """A path resolved outside the boundary it was required to stay within."""


class OverwriteError(ArchiveError):
    """A write would have clobbered existing append-only capture material."""


class PreflightError(ArchiveError):
    """A required tool, image, or environment fact could not be established."""


class CaptureError(ArchiveError):
    """A capture step failed in a way that prevents producing a capture dir."""


class ManifestError(ArchiveError):
    """A manifest could not be generated or is internally inconsistent."""


class CaptureValidationError(ArchiveError):
    """A capture failed validation."""


class LockError(ArchiveError):
    """An operational lock is held by another process."""


class SanitizationError(ArchiveError):
    """Content destined for the public export failed a sanitization gate."""
