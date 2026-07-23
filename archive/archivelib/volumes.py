"""macOS volume introspection via ``diskutil``.

The archive subsystem refuses to write real capture material anywhere except a
volume that ``diskutil`` positively confirms is *external* and *writable*. We
never infer "external" from the path alone: ``/Volumes/Macintosh HD`` is a
symlink to ``/`` on modern macOS, so a path check by itself would happily aim a
multi-gigabyte crawl at the boot disk.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ExternalVolumeError

VOLUMES_DIR = Path("/Volumes")
DISKUTIL_TIMEOUT = 20


@dataclass
class VolumeInfo:
    """The subset of ``diskutil info`` we make decisions on."""

    mount_point: str
    volume_name: str = ""
    device_identifier: str = ""
    internal: bool | None = None
    writable: bool | None = None
    ejectable: bool | None = None
    removable: bool | None = None
    protocol: str = ""
    filesystem: str = ""
    raw_keys: dict = field(default_factory=dict)

    @property
    def is_external(self) -> bool:
        # `Internal` must be an explicit False. Unknown (None) is not external:
        # absence of evidence is not evidence of an external disk.
        return self.internal is False

    @property
    def is_writable(self) -> bool:
        return self.writable is True

    @property
    def is_root_volume(self) -> bool:
        return self.mount_point == "/"

    def summary(self) -> dict:
        return {
            "mount_point": self.mount_point,
            "volume_name": self.volume_name,
            "device_identifier": self.device_identifier,
            "internal": self.internal,
            "writable": self.writable,
            "ejectable": self.ejectable,
            "removable": self.removable,
            "protocol": self.protocol,
            "filesystem": self.filesystem,
        }


def _run_diskutil(target: str) -> dict:
    try:
        proc = subprocess.run(
            ["diskutil", "info", "-plist", target],
            capture_output=True,
            timeout=DISKUTIL_TIMEOUT,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - non-macOS hosts
        raise ExternalVolumeError("diskutil not available; cannot verify volume") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExternalVolumeError(f"diskutil timed out inspecting {target!r}") from exc
    if proc.returncode != 0:
        raise ExternalVolumeError(
            f"diskutil could not inspect {target!r}: {proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    try:
        return plistlib.loads(proc.stdout)
    except Exception as exc:
        raise ExternalVolumeError(f"unparseable diskutil output for {target!r}") from exc


def _as_bool(value) -> bool | None:
    return value if isinstance(value, bool) else None


def inspect_volume(target: str | Path) -> VolumeInfo:
    """Return diskutil facts for the volume backing ``target``."""
    data = _run_diskutil(str(target))
    return VolumeInfo(
        mount_point=str(data.get("MountPoint", "") or ""),
        volume_name=str(data.get("VolumeName", "") or ""),
        device_identifier=str(data.get("DeviceIdentifier", "") or ""),
        internal=_as_bool(data.get("Internal")),
        # diskutil exposes writability under two different keys depending on
        # whether the target is a volume or a whole disk.
        writable=_as_bool(data.get("WritableVolume", data.get("Writable"))),
        ejectable=_as_bool(data.get("Ejectable")),
        removable=_as_bool(data.get("RemovableMedia")),
        protocol=str(data.get("BusProtocol", "") or ""),
        filesystem=str(data.get("FilesystemName", "") or ""),
        raw_keys={
            k: data.get(k)
            for k in (
                "Internal",
                "WritableVolume",
                "Writable",
                "Ejectable",
                "RemovableMedia",
                "BusProtocol",
                "MountPoint",
                "VolumeName",
                "DeviceIdentifier",
            )
            if k in data
        },
    )


def mount_point_for(path: Path) -> Path:
    """Deepest existing ancestor of ``path`` that is a mount point.

    The corpus directory usually does not exist yet on a freshly attached disk,
    so we walk up to the first component that does.
    """
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    while not os.path.ismount(probe) and probe != probe.parent:
        probe = probe.parent
    return probe


def list_candidate_volumes() -> list[VolumeInfo]:
    """Every entry under /Volumes that is a real mount, with diskutil facts.

    Symlinked entries (notably ``Macintosh HD`` -> ``/``) are skipped outright:
    they are not separate volumes.
    """
    candidates: list[VolumeInfo] = []
    if not VOLUMES_DIR.is_dir():
        return candidates
    for entry in sorted(VOLUMES_DIR.iterdir()):
        if entry.is_symlink():
            continue
        if not entry.is_dir():
            continue
        if not os.path.ismount(entry):
            continue
        try:
            candidates.append(inspect_volume(entry))
        except ExternalVolumeError:
            continue
    return candidates


def external_writable_volumes() -> list[VolumeInfo]:
    return [v for v in list_candidate_volumes() if v.is_external and v.is_writable and not v.is_root_volume]


def select_unique_external_volume() -> VolumeInfo:
    """Pick the single external writable volume, or refuse.

    Refusing on ambiguity is deliberate: guessing between two attached disks
    could scatter a longitudinal corpus across media, and the corpus is only
    meaningful if it is whole.
    """
    matches = external_writable_volumes()
    if not matches:
        raise ExternalVolumeError(
            "no writable external volume is mounted under /Volumes; "
            "refusing to select a storage location for real captures"
        )
    if len(matches) > 1:
        names = ", ".join(f"{v.mount_point} ({v.volume_name})" for v in matches)
        raise ExternalVolumeError(
            f"{len(matches)} writable external volumes are mounted ({names}); "
            "refusing to guess — set ARCHIVE_ROOT explicitly"
        )
    return matches[0]


def probe_writable(directory: Path) -> bool:
    """Confirm writability by actually writing, not by reading a flag."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    probe = directory / f".archive-write-probe-{os.getpid()}"
    try:
        probe.write_text("probe\n", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False
    finally:
        # Best effort: never leave a probe file behind in the corpus.
        try:
            probe.unlink()
        except OSError:
            pass


def free_bytes(path: Path) -> int | None:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        stats = os.statvfs(probe)
    except OSError:
        return None
    return stats.f_bavail * stats.f_frsize
