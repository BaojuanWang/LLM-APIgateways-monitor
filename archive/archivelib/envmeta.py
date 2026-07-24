"""Environment and provenance metadata recorded with every capture.

Deliberate omissions: no local username, no raw hostname, no absolute repo path.
A capture must be attributable to a *configuration*, not to a person's laptop.
The machine is identified by a truncated hash of its hostname, which is stable
across runs and useless for identifying anyone.
"""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .canonical import sha256_text

SUBPROCESS_TIMEOUT = 30


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def local_timezone_name() -> str:
    try:
        return datetime.now().astimezone().tzname() or ""
    except Exception:  # pragma: no cover - platform dependent
        return ""


def local_utc_offset_seconds() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds()) if offset else 0


def machine_id() -> str:
    """Stable pseudonymous machine identifier.

    A hash, not the hostname: macOS hostnames very often contain the owner's
    name, and this value is allowed to appear in local metadata.
    """
    try:
        raw = socket.gethostname()
    except Exception:  # pragma: no cover
        raw = "unknown-host"
    return sha256_text(f"llm-archive-machine::{raw}")[:16]


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=SUBPROCESS_TIMEOUT, check=False)
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]} timed out"
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace").strip(),
        proc.stderr.decode("utf-8", "replace").strip(),
    )


def docker_version() -> dict:
    code, out, err = _run(["docker", "version", "--format", "{{.Server.Version}}"])
    if code != 0:
        client_code, client_out, _ = _run(["docker", "--version"])
        return {
            "available": False,
            "server_version": None,
            "client_version": client_out if client_code == 0 else None,
            "error": err or "docker daemon unreachable",
        }
    return {"available": True, "server_version": out, "client_version": None, "error": None}


def playwright_versions() -> dict:
    info: dict = {"playwright_python": None, "browser": None, "browser_channel": "chromium", "available": False}
    try:
        from importlib.metadata import version as pkg_version

        info["playwright_python"] = pkg_version("playwright")
    except Exception:
        pass
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            info["browser"] = browser.version
            info["available"] = True
            browser.close()
    except Exception as exc:
        info["error"] = str(exc)[:200]
    return info


def git_commit(repo: Path) -> dict:
    code, out, _ = _run(["git", "-C", str(repo), "rev-parse", "HEAD"])
    sha = out if code == 0 else None
    dirty_code, dirty_out, _ = _run(["git", "-C", str(repo), "status", "--porcelain"])
    return {
        "commit_sha": sha,
        "worktree_dirty": bool(dirty_out) if dirty_code == 0 else None,
    }


def free_bytes(path: Path) -> int | None:
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return None
    return usage.free


def base_environment(repo: Path, archive_root: Path | None) -> dict:
    """Static facts about the machine and toolchain."""
    return {
        "collected_at_utc": utc_now_iso(),
        "machine_id": machine_id(),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "arch": platform.architecture()[0],
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_basename": Path(sys.executable).name,
        },
        "local_timezone": {
            "name": local_timezone_name(),
            "utc_offset_seconds": local_utc_offset_seconds(),
        },
        "docker": docker_version(),
        "git": git_commit(repo),
        "free_bytes_archive_root": free_bytes(archive_root) if archive_root else None,
        "monotonic_start": time.monotonic(),
    }


# Site-condition classification used in capture.json and the public index.
SITE_CONDITIONS = (
    "ok",
    "redirected_offsite",
    "blocked_or_challenge",
    "parked_or_for_sale",
    "service_stopped",
    "unavailable",
    "unknown",
)

_PARKED_MARKERS = ("domain for sale", "buy this domain", "域名出售", "this domain is for sale", "域名待售")
_CHALLENGE_MARKERS = (
    "checking your browser",
    "cf-browser-verification",
    "cf_chl_",
    "just a moment",
    "attention required! | cloudflare",
    "please enable javascript and cookies",
    "ddos protection by",
    "人机验证",
)
_STOPPED_MARKERS = ("服务已停止", "已停止维护", "service has been discontinued", "service is closed", "本站已关闭")


def classify_site_condition(
    *,
    http_status: int | None,
    final_url: str,
    original_host: str,
    page_text_sample: str = "",
    error: str = "",
) -> str:
    """Coarse condition label from what the browser actually observed.

    Ordering matters: an explicit "service stopped" notice on a 200 page is more
    informative than the 200 itself, so content markers are checked before
    status codes.
    """
    sample = (page_text_sample or "").lower()
    if any(marker in sample for marker in _STOPPED_MARKERS):
        return "service_stopped"
    if any(marker in sample for marker in _PARKED_MARKERS):
        return "parked_or_for_sale"
    if any(marker in sample for marker in _CHALLENGE_MARKERS):
        return "blocked_or_challenge"
    if error and not http_status:
        return "unavailable"
    if http_status in (403, 429, 503) and any(m in sample for m in ("cloudflare", "captcha", "verify")):
        return "blocked_or_challenge"
    if http_status in (521, 522, 523, 525, 526):
        return "blocked_or_challenge"
    if http_status is not None and http_status >= 500:
        return "unavailable"
    if final_url and original_host:
        try:
            from .identity import normalize_host

            final_host = normalize_host(final_url)
            if final_host != original_host and not final_host.endswith("." + original_host):
                return "redirected_offsite"
        except Exception:
            pass
    if http_status is not None and 200 <= http_status < 400:
        return "ok"
    if http_status is not None:
        return "unavailable"
    return "unknown"
