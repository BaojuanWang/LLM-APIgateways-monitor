"""Docker image pinning and the Browsertrix Crawler invocation.

Every container this subsystem runs is addressed by **digest**, not by tag. A
tag is a mutable pointer; a capture that records only ``:1.12.4`` cannot prove
which bytes produced it. Preflight resolves tag -> digest once and the digest is
what actually gets run and recorded.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .errors import PreflightError

PULL_TIMEOUT = 900
INSPECT_TIMEOUT = 60


@dataclass
class ImagePin:
    image: str
    tag: str
    digest: str = ""
    image_id: str = ""
    resolved: bool = False
    error: str = ""

    @property
    def reference(self) -> str:
        """The reference to actually run: digest when known, else tag."""
        if self.digest:
            return f"{self.image}@{self.digest}"
        return f"{self.image}:{self.tag}"

    def summary(self) -> dict:
        return {
            "image": self.image,
            "tag": self.tag,
            "digest": self.digest or None,
            "image_id": self.image_id or None,
            "reference": self.reference,
            "resolved": self.resolved,
            "error": self.error or None,
        }


def _run(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return 127, "", "docker not found"
    except subprocess.TimeoutExpired:
        return 124, "", "docker command timed out"
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


def resolve_image_digest(image: str, tag: str, *, pull: bool = True) -> ImagePin:
    """Resolve ``image:tag`` to an immutable digest, pulling if needed."""
    pin = ImagePin(image=image, tag=tag)
    if str(tag).strip().lower() == "latest":
        pin.error = "refusing to use the floating 'latest' tag"
        return pin

    ref = f"{image}:{tag}"
    code, _, _ = _run(["docker", "image", "inspect", ref], INSPECT_TIMEOUT)
    if code != 0 and pull:
        pull_code, _, pull_err = _run(["docker", "pull", ref], PULL_TIMEOUT)
        if pull_code != 0:
            pin.error = f"docker pull {ref} failed: {pull_err.strip()[:300]}"
            return pin

    code, out, err = _run(["docker", "image", "inspect", ref, "--format", "{{json .}}"], INSPECT_TIMEOUT)
    if code != 0:
        pin.error = f"docker image inspect {ref} failed: {err.strip()[:300]}"
        return pin
    try:
        info = json.loads(out)
    except json.JSONDecodeError as exc:
        pin.error = f"unparseable docker inspect output: {exc}"
        return pin

    pin.image_id = str(info.get("Id", "") or "")
    repo_digests = info.get("RepoDigests") or []
    for entry in repo_digests:
        if entry.startswith(f"{image}@"):
            pin.digest = entry.split("@", 1)[1]
            break
    if not pin.digest and repo_digests:
        pin.digest = str(repo_digests[0]).split("@", 1)[-1]
    if not pin.digest:
        # Locally-built images have no repo digest. Record the image id so the
        # capture is still pinned to specific bytes, and say so plainly.
        pin.error = "image has no repository digest (locally built?); recorded image id instead"
        pin.resolved = bool(pin.image_id)
        return pin
    pin.resolved = True
    return pin


# ---------------------------------------------------------------------------
# Browsertrix
# ---------------------------------------------------------------------------


@dataclass
class BrowsertrixResult:
    exit_code: int
    command: list[str] = field(default_factory=list)
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    collection_dir: Path | None = None
    wacz_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.wacz_path is not None and self.wacz_path.exists()

    def to_exit_json(self, *, redact: callable | None = None) -> dict:
        def scrub(text: str) -> str:
            return redact(text) if redact else text

        return {
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "duration_seconds": round(self.duration_seconds, 2),
            "command": [scrub(part) for part in self.command],
            "stdout_tail": scrub(self.stdout_tail),
            "stderr_tail": scrub(self.stderr_tail),
            "wacz_present": bool(self.wacz_path and self.wacz_path.exists()),
        }


def build_browsertrix_config(
    *,
    collection: str,
    seeds: list[str],
    cfg: dict,
) -> dict:
    """Browsertrix YAML config as a plain dict.

    Scope is per-page (or page-SPA) by design — an unrestricted host crawl of a
    third-party gateway is neither necessary for this research nor defensible.
    """
    capture = cfg.get("capture", {})
    bt = cfg.get("browsertrix", {})
    scope_type = capture.get("scope_type", "page")

    config: dict = {
        "collection": collection,
        "seeds": [{"url": url, "scopeType": scope_type} for url in seeds],
        "workers": int(capture.get("workers", 1)),
        "pageLimit": int(capture.get("page_limit", 8)),
        "timeLimit": int(capture.get("time_limit_seconds", 600)),
        "pageLoadTimeout": int(capture.get("page_load_timeout_seconds", 60)),
        "behaviorTimeout": int(capture.get("behavior_timeout_seconds", 30)),
        "generateWACZ": bool(bt.get("generate_wacz", True)),
        "generateCDX": bool(bt.get("generate_cdx", True)),
        "text": list(bt.get("text_extraction", ["to-pages", "to-warc"])),
        "screenshot": ",".join(bt.get("screenshot_modes", ["view", "fullPage"])),
        "behaviors": ",".join(bt.get("behaviors", ["autoscroll"])),
        "blockAds": bool(bt.get("block_ads", False)),
        "failOnFailedSeed": bool(bt.get("fail_on_failed_seed", False)),
        "logging": ",".join(bt.get("log_options", ["stats", "debug"])),
        # Never resume into a previous crawl's state: each capture is its own
        # independent observation.
        "saveState": "never",
        "headless": True,
    }
    suffix = capture.get("user_agent_suffix")
    if suffix:
        config["userAgentSuffix"] = suffix
    return config


def run_browsertrix(
    *,
    pin: ImagePin,
    crawls_dir: Path,
    config_path: Path,
    collection: str,
    timeout_seconds: int,
    extra_docker_args: list[str] | None = None,
) -> BrowsertrixResult:
    """Run one crawl into ``crawls_dir`` (mounted as /crawls in the container).

    The container gets exactly two mounts: the capture's own browsertrix output
    directory, and the generated config read-only. No host profile, no
    credential mount, no network aliasing.
    """
    import time

    crawls_dir = Path(crawls_dir)
    crawls_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "docker",
        "run",
        "--rm",
        "--init",
        "-v",
        f"{crawls_dir.resolve()}:/crawls",
        "-v",
        f"{config_path.resolve()}:/app/crawl-config.yaml:ro",
    ]
    if extra_docker_args:
        cmd.extend(extra_docker_args)
    cmd.extend([pin.reference, "crawl", "--config", "/app/crawl-config.yaml"])

    started = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout_seconds, check=False)
        code = proc.returncode
        stdout = proc.stdout.decode("utf-8", "replace")
        stderr = proc.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        code = 124
        stdout = (exc.stdout or b"").decode("utf-8", "replace")
        stderr = (exc.stderr or b"").decode("utf-8", "replace")
    except FileNotFoundError:
        return BrowsertrixResult(exit_code=127, command=cmd, stderr_tail="docker not found")
    duration = time.monotonic() - started

    collection_dir = crawls_dir / "collections" / collection
    wacz = collection_dir / f"{collection}.wacz"
    return BrowsertrixResult(
        exit_code=code,
        command=cmd,
        stdout_tail=stdout[-8000:],
        stderr_tail=stderr[-8000:],
        duration_seconds=duration,
        timed_out=timed_out,
        collection_dir=collection_dir if collection_dir.exists() else None,
        wacz_path=wacz if wacz.exists() else None,
    )


def check_docker_available() -> None:
    code, _, err = _run(["docker", "info", "--format", "{{.ServerVersion}}"], INSPECT_TIMEOUT)
    if code != 0:
        raise PreflightError(f"Docker daemon is not reachable: {err.strip()[:200]}")


def shell_preview(cmd: list[str]) -> str:
    """Human-readable command line for logs (never executed)."""
    return " ".join(shlex.quote(part) for part in cmd)


def docker_uid_args() -> list[str]:
    """Run as the invoking user on Linux; Docker Desktop maps ownership on macOS."""
    if os.uname().sysname == "Darwin":
        return []
    return ["-u", f"{os.getuid()}:{os.getgid()}"]
