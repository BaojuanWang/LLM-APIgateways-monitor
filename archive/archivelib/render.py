"""Rendered-page outputs: DOM, screenshots, network summary, state inventory.

These are **secondary representations**. The WACZ is the canonical artifact; a
screenshot is a picture of one moment in one browser, and SingleFile output is a
convenience copy. Nothing here is allowed to stand in for the WACZ, and a
failure here never invalidates a successful crawl.

Every context is created fresh and unauthenticated: no ``storage_state``, no
persistent profile, no injected cookies or headers.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .envmeta import classify_site_condition, utc_now_iso
from .sanitize import browser_state_names, classify_failure, sanitized_network_record


@dataclass
class RenderedPageResult:
    url: str
    page_type: str
    ok: bool = False
    final_url: str = ""
    http_status: int | None = None
    title: str = ""
    site_condition: str = "unknown"
    dom_path: str = ""
    viewport_screenshot: str = ""
    fullpage_screenshot: str = ""
    singlefile_path: str = ""
    singlefile_error: str = ""
    error: str = ""
    duration_seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "url": self.url,
            "page_type": self.page_type,
            "ok": self.ok,
            "final_url": self.final_url,
            "http_status": self.http_status,
            "title": self.title[:200],
            "site_condition": self.site_condition,
            "artifacts": {
                "final_dom": self.dom_path,
                "viewport_screenshot": self.viewport_screenshot,
                "fullpage_screenshot": self.fullpage_screenshot,
                "singlefile": self.singlefile_path,
            },
            "singlefile_error": self.singlefile_error,
            "error": self.error,
            "duration_seconds": round(self.duration_seconds, 2),
        }


@dataclass
class RenderBundle:
    pages: list[RenderedPageResult] = field(default_factory=list)
    network_records: int = 0
    state_names_path: str = ""
    network_summary_path: str = ""
    available: bool = True
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "available": self.available,
            "error": self.error,
            "pages": [p.as_dict() for p in self.pages],
            "network_records": self.network_records,
            "network_summary": self.network_summary_path,
            "browser_state_names": self.state_names_path,
        }


def _slug(page_type: str, index: int) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in page_type).strip("-") or "page"
    return f"{index:02d}-{safe}"


def render_pages(
    *,
    rendered_dir: Path,
    seeds: list,
    host: str,
    cfg: dict,
) -> RenderBundle:
    """Render up to ``rendered.max_pages`` seeds and write the artifacts.

    Returns a bundle even on total failure: an unrenderable site is a finding,
    not a crash.
    """
    bundle = RenderBundle()
    rcfg = cfg.get("rendered", {})
    if not rcfg.get("enabled", True):
        bundle.available = False
        bundle.error = "rendered outputs disabled by configuration"
        return bundle

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        bundle.available = False
        bundle.error = f"playwright unavailable: {exc}"
        return bundle

    rendered_dir = Path(rendered_dir)
    shots_dir = rendered_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    max_pages = int(rcfg.get("max_pages", 4))
    nav_timeout = int(rcfg.get("navigation_timeout_seconds", 45)) * 1000
    settle = float(rcfg.get("settle_seconds", 3))
    targets = seeds[:max_pages]

    network_path = rendered_dir / "network_summary.jsonl"
    network_lines: list[str] = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            # Fresh, unauthenticated, profile-free context.
            context = browser.new_context(
                viewport={
                    "width": int(rcfg.get("viewport_width", 1440)),
                    "height": int(rcfg.get("viewport_height", 900)),
                },
                device_scale_factor=int(rcfg.get("device_scale_factor", 1)),
                ignore_https_errors=True,
                storage_state=None,
                java_script_enabled=True,
            )

            def on_response(response):
                try:
                    request = response.request
                    timing = None
                    try:
                        timing = request.timing.get("responseEnd") if request.timing else None
                    except Exception:
                        timing = None
                    size = None
                    try:
                        size = int(response.headers.get("content-length", "")) or None
                    except (TypeError, ValueError):
                        size = None
                    record = sanitized_network_record(
                        timestamp_utc=utc_now_iso(),
                        url=response.url,
                        method=request.method,
                        resource_type=request.resource_type,
                        status=response.status,
                        # Only the header NAME's value for content-type is kept;
                        # no other header is read anywhere in this function.
                        mime_type=response.headers.get("content-type", ""),
                        redirected_from=request.redirected_from.url if request.redirected_from else "",
                        redirected_to=request.redirected_to.url if request.redirected_to else "",
                        timing_ms=timing,
                        response_bytes=size,
                    )
                    network_lines.append(json.dumps(record, ensure_ascii=False))
                except Exception:
                    pass

            def on_request_failed(request):
                try:
                    record = sanitized_network_record(
                        timestamp_utc=utc_now_iso(),
                        url=request.url,
                        method=request.method,
                        resource_type=request.resource_type,
                        status=None,
                        failure_category=classify_failure(request.failure),
                    )
                    network_lines.append(json.dumps(record, ensure_ascii=False))
                except Exception:
                    pass

            context.on("response", on_response)
            context.on("requestfailed", on_request_failed)

            for index, seed in enumerate(targets, start=1):
                url = seed.url if hasattr(seed, "url") else str(seed)
                page_type = seed.page_type if hasattr(seed, "page_type") else "unknown"
                result = RenderedPageResult(url=url, page_type=page_type)
                started = time.monotonic()
                page = context.new_page()
                try:
                    response = page.goto(url, timeout=nav_timeout, wait_until="load")
                    result.http_status = response.status if response else None
                    try:
                        page.wait_for_timeout(int(settle * 1000))
                    except Exception:
                        pass
                    result.final_url = page.url
                    result.title = page.title() or ""
                    dom = page.content()
                    stem = _slug(page_type, index)

                    dom_name = "final_dom.html" if index == 1 else f"final_dom_{stem}.html"
                    (rendered_dir / dom_name).write_text(dom, encoding="utf-8")
                    result.dom_path = dom_name

                    vp_name = "viewport.png" if index == 1 else f"viewport_{stem}.png"
                    page.screenshot(path=str(shots_dir / vp_name), full_page=False)
                    result.viewport_screenshot = f"screenshots/{vp_name}"

                    if rcfg.get("full_page_screenshot", True):
                        fp_name = "fullpage.png" if index == 1 else f"fullpage_{stem}.png"
                        page.screenshot(path=str(shots_dir / fp_name), full_page=True)
                        result.fullpage_screenshot = f"screenshots/{fp_name}"

                    try:
                        text_sample = page.inner_text("body")[:4000]
                    except Exception:
                        text_sample = dom[:4000]
                    result.site_condition = classify_site_condition(
                        http_status=result.http_status,
                        final_url=result.final_url,
                        original_host=host,
                        page_text_sample=text_sample,
                    )
                    result.ok = True
                except Exception as exc:
                    result.error = f"{type(exc).__name__}: {str(exc)[:300]}"
                    result.site_condition = classify_site_condition(
                        http_status=result.http_status,
                        final_url=result.final_url or url,
                        original_host=host,
                        error=result.error,
                    )
                finally:
                    result.duration_seconds = time.monotonic() - started
                    try:
                        page.close()
                    except Exception:
                        pass
                bundle.pages.append(result)

            # Browser state NAMES only — values stay in the WACZ.
            try:
                cookies = context.cookies()
            except Exception:
                cookies = []
            local_keys: list[str] = []
            session_keys: list[str] = []
            try:
                probe = context.new_page()
                probe.goto(targets[0].url if targets else f"https://{host}/", timeout=nav_timeout, wait_until="domcontentloaded")
                local_keys = probe.evaluate("() => Object.keys(window.localStorage || {})") or []
                session_keys = probe.evaluate("() => Object.keys(window.sessionStorage || {})") or []
                probe.close()
            except Exception:
                pass

            state = browser_state_names(
                cookies=cookies, local_storage_keys=local_keys, session_storage_keys=session_keys
            )
            state_path = rendered_dir / "browser_state_names.json"
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            bundle.state_names_path = "browser_state_names.json"

            context.close()
            browser.close()
    except Exception as exc:
        bundle.available = False
        bundle.error = f"{type(exc).__name__}: {str(exc)[:300]}"

    network_path.write_text("\n".join(network_lines) + ("\n" if network_lines else ""), encoding="utf-8")
    bundle.network_summary_path = "network_summary.jsonl"
    bundle.network_records = len(network_lines)
    return bundle


# ---------------------------------------------------------------------------
# SingleFile (secondary convenience copy)
# ---------------------------------------------------------------------------


def singlefile_available(cfg: dict) -> tuple[bool, str]:
    sf = cfg.get("singlefile", {})
    if not sf.get("enabled", True):
        return False, "disabled by configuration"
    if sf.get("docker_image"):
        if not sf.get("docker_digest"):
            return False, "docker_image set without a pinned digest"
        return shutil.which("docker") is not None, "docker not on PATH" if not shutil.which("docker") else ""
    if shutil.which("npx") is None:
        return False, "npx not on PATH"
    return True, ""


def run_singlefile(*, url: str, output_path: Path, cfg: dict) -> tuple[bool, str]:
    """Produce a SingleFile HTML copy of ``url``.

    Pinned by exact npm version (or an image digest). Failure is recorded and
    tolerated: SingleFile is never a substitute for the WACZ.
    """
    sf = cfg.get("singlefile", {})
    ok, reason = singlefile_available(cfg)
    if not ok:
        return False, reason

    timeout = int(sf.get("timeout_seconds", 120))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if sf.get("docker_image"):
        image_ref = f"{sf['docker_image']}@{sf['docker_digest']}"
        cmd = [
            "docker", "run", "--rm", "--init",
            "-v", f"{output_path.parent.resolve()}:/out",
            image_ref, url, f"/out/{output_path.name}",
        ]
    else:
        package = f"{sf.get('package', 'single-file-cli')}@{sf.get('version', '2.0.83')}"
        cmd = [
            "npx", "--yes", package, url, str(output_path),
            "--browser-headless=true",
            "--browser-load-max-time", str(timeout * 1000),
        ]

    env = dict(os.environ)
    # Never let an ambient token reach a third-party fetch.
    for var in ("NPM_TOKEN", "NODE_AUTH_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        env.pop(var, None)

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 60, check=False, env=env)
    except subprocess.TimeoutExpired:
        return False, "singlefile timed out"
    except FileNotFoundError:
        return False, f"{cmd[0]} not found"

    if proc.returncode != 0:
        return False, proc.stderr.decode("utf-8", "replace").strip()[:300] or f"exit {proc.returncode}"
    if not output_path.exists() or output_path.stat().st_size == 0:
        return False, "singlefile produced no output"
    return True, ""
