"""Operational lock files.

Two archive runs against the same corpus would interleave capture directories
and racy queue writes. Locks live under ``$ARCHIVE_ROOT/operational/locks/`` so
they disappear naturally when the external volume is unmounted — a stale lock
can never outlive the disk it protects.
"""

from __future__ import annotations

import errno
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .envmeta import machine_id, utc_now_iso
from .errors import LockError

DEFAULT_STALE_SECONDS = 6 * 60 * 60


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno == errno.EPERM  # exists but owned by another user
    return True


def _read_lock(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_stale(path: Path, stale_seconds: int = DEFAULT_STALE_SECONDS) -> bool:
    """A lock is stale only if its owner is provably gone or it is very old.

    Deliberately conservative: on a different machine we cannot check the PID,
    so we fall back to age alone.
    """
    info = _read_lock(path)
    holder_machine = info.get("machine_id")
    pid = int(info.get("pid", 0) or 0)
    if holder_machine == machine_id() and pid and not _pid_alive(pid):
        return True
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age > stale_seconds


@contextmanager
def file_lock(lock_path: Path, *, purpose: str = "", stale_seconds: int = DEFAULT_STALE_SECONDS, break_stale: bool = True):
    """Acquire an exclusive lock via ``O_CREAT|O_EXCL``, or raise ``LockError``."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(
        {
            "pid": os.getpid(),
            "machine_id": machine_id(),
            "acquired_at_utc": utc_now_iso(),
            "purpose": purpose,
        },
        indent=2,
    )

    acquired = False
    try:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if break_stale and is_stale(lock_path, stale_seconds):
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            else:
                info = _read_lock(lock_path)
                raise LockError(
                    f"lock held: {lock_path} (pid={info.get('pid')}, "
                    f"since={info.get('acquired_at_utc')}, purpose={info.get('purpose')!r})"
                )
        with os.fdopen(fd, "w") as handle:
            handle.write(payload + "\n")
        acquired = True
        yield lock_path
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except OSError:
                pass
