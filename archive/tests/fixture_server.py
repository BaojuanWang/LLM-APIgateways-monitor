"""Local HTTP server for the synthetic fixture site.

Tests must never depend on a live third-party website: a third party can change,
rate-limit, block, or disappear, and a test suite that fails for those reasons
is measuring the internet rather than this code. Everything the archive
subsystem needs to exercise — clean URLs, JSON endpoints, a session cookie, a
404 for a page type that genuinely does not exist — is served from here.

Bound to 127.0.0.1 on an ephemeral port. Usable as a context manager or
standalone::

    with FixtureSite() as site:
        print(site.base_url)

    python3 archive/tests/fixture_server.py --port 8099
"""

from __future__ import annotations

import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent / "fixtures" / "site"

# Clean URL -> file on disk. Anything not listed returns 404, which is what
# makes "missing page types are recorded, not fabricated" testable.
ROUTES: dict[str, tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/login": ("login.html", "text/html; charset=utf-8"),
    "/register": ("register.html", "text/html; charset=utf-8"),
    "/pricing": ("pricing.html", "text/html; charset=utf-8"),
    "/docs": ("docs.html", "text/html; charset=utf-8"),
    "/models": ("models.html", "text/html; charset=utf-8"),
    "/status": ("status.html", "text/html; charset=utf-8"),
    "/privacy": ("privacy.html", "text/html; charset=utf-8"),
    "/terms": ("terms.html", "text/html; charset=utf-8"),
    "/announcement": ("announcement.html", "text/html; charset=utf-8"),
    "/v1/models": ("v1/models.json", "application/json"),
    "/api/status": ("api/status.json", "application/json"),
}

# Deliberately absent so seed discovery has something to report as missing:
#   /api/pricing, /api/models, /about


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "ArchiveFixture/1.0"
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, site_dir: Path = SITE_DIR, **kwargs):
        self._site_dir = site_dir
        super().__init__(*args, **kwargs)

    def log_message(self, *args):  # silence per-request stderr noise
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # A session cookie so the browser-state-name inventory has something to
        # find. The NAME is what the archive records; this value never leaves
        # the WACZ.
        self.send_header("Set-Cookie", "fixture_session=synthetic; Path=/; SameSite=Lax")
        self.send_header("X-Fixture-Server", "synthetic")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        route = ROUTES.get(path) or ROUTES.get(path.rstrip("/") or "/")
        if route is None:
            body = b"<!doctype html><html><body><h1>404 Not Found</h1></body></html>"
            self._send(404, body, "text/html; charset=utf-8")
            return
        filename, content_type = route
        target = self._site_dir / filename
        if not target.is_file():
            self._send(500, b"fixture file missing", "text/plain; charset=utf-8")
            return
        self._send(200, target.read_bytes(), content_type)

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_POST(self):  # noqa: N802
        # The archiver must never submit a form. If this ever fires, a test
        # should fail loudly rather than quietly succeed.
        self._send(405, b"form submission is not permitted in the fixture", "text/plain; charset=utf-8")


class FixtureSite:
    """Threaded fixture server bound to 127.0.0.1 on an ephemeral port."""

    def __init__(self, site_dir: Path = SITE_DIR, port: int = 0) -> None:
        self.site_dir = Path(site_dir)
        handler = partial(FixtureHandler, site_dir=self.site_dir)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.port = self.httpd.server_address[1]
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.port}"

    def start(self) -> "FixtureSite":
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread:
            self._thread.join(timeout=5)

    def __enter__(self) -> "FixtureSite":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Serve the synthetic archive fixture site.")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument(
        "--bind-all",
        action="store_true",
        help="bind 0.0.0.0 so a Docker container can reach it (smoke test only)",
    )
    args = parser.parse_args()

    handler = partial(FixtureHandler, site_dir=SITE_DIR)
    address = ("0.0.0.0", args.port) if args.bind_all else ("127.0.0.1", args.port)
    server = ThreadingHTTPServer(address, handler)
    print(f"fixture site on http://{server.server_address[0]}:{server.server_address[1]}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
