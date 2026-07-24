"""Bounded seed discovery on unreachable hosts (Fix 1).

No live third-party site is contacted. Network-layer failures are injected with a
``FakeSession`` (raising the exact ``requests`` exceptions), HTTP status codes are
injected as fake responses, the realistic success path uses the local
``FixtureSite``, and timing is measured against a local blackhole socket that
accepts connections but never answers.
"""

from __future__ import annotations

import socket
import threading
import time
import types

import pytest
import requests
from requests import exceptions as rex

from archivelib.seeds import discover_seeds, network_failure_reason
from fixture_server import FixtureSite


# --- fakes ------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code, text="", content_type="text/html; charset=utf-8"):
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": content_type}
        self.url = ""


class FakeSession:
    """Minimal stand-in for requests.Session with scripted results.

    The first ``get`` returns/raises ``homepage``; every subsequent ``get``
    (i.e. each known-path/API probe) returns/raises ``probe``.
    """

    def __init__(self, homepage, probe=None):
        self.headers = {}
        self.auth = "sentinel"  # discover_seeds must reset this to None
        self.cookies = types.SimpleNamespace(clear=lambda: None)
        self._homepage = homepage
        self._probe = probe if probe is not None else _FakeResp(404)
        self.calls = []

    def get(self, url, timeout=None, allow_redirects=True, verify=True):
        self.calls.append((url, timeout))
        result = self._homepage if len(self.calls) == 1 else self._probe
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self):
        pass


class Blackhole:
    """127.0.0.1 socket that accepts connections and never responds.

    Drives requests into a read timeout (connection established, no HTTP
    response) — the exact failure mode of a host that is up at the TCP layer but
    dead at the application layer.
    """

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        self._held: list[socket.socket] = []
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self):
        self.sock.settimeout(0.25)
        while not self._stop:
            try:
                conn, _ = self.sock.accept()
                self._held.append(conn)  # hold open; never write a response
            except socket.timeout:
                continue
            except OSError:
                break

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}/"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop = True
        for conn in self._held:
            try:
                conn.close()
            except OSError:
                pass
        self.sock.close()


def _discover(cfg, session=None, url="https://host.test/", host="host.test"):
    return discover_seeds(service_id="svc_00000000", host=host, canonical_url=url, cfg=cfg, session=session)


# --- classifier unit --------------------------------------------------------


@pytest.mark.parametrize(
    "exc,expected",
    [
        (rex.ConnectionError("Name or service not known"), "dns_failure"),
        (rex.ConnectionError("[Errno 8] nodename nor servname provided"), "dns_failure"),
        (rex.ConnectTimeout(), "connection_timeout"),
        (rex.ReadTimeout(), "read_timeout_no_response"),
        (rex.SSLError("handshake failure"), "tls_failure"),
        (rex.ConnectionError("Connection refused"), "connection_refused"),
        (rex.ConnectionError("Network is unreachable"), "network_unreachable"),
        (rex.ConnectionError("connection reset by peer"), "connection_error"),
        (rex.Timeout(), "timeout"),
    ],
)
def test_network_failure_reason_classifies(exc, expected):
    assert network_failure_reason(exc) == expected


@pytest.mark.parametrize("exc", [rex.TooManyRedirects(), rex.InvalidURL(), rex.MissingSchema(), ValueError("x")])
def test_non_network_errors_are_not_failures(exc):
    assert network_failure_reason(exc) is None


# --- homepage network failure -> homepage-only, no probing ------------------


@pytest.mark.parametrize(
    "exc,reason",
    [
        (rex.ConnectionError("Name or service not known"), "dns_failure"),
        (rex.ConnectTimeout(), "connection_timeout"),
        (rex.ConnectionError("Connection refused"), "connection_refused"),
        (rex.SSLError("bad handshake"), "tls_failure"),
        (rex.ConnectionError("Network is unreachable"), "network_unreachable"),
        (rex.ReadTimeout(), "read_timeout_no_response"),
    ],
)
def test_homepage_network_failure_keeps_homepage_only(cfg, exc, reason):
    fake = FakeSession(homepage=exc)
    plan = _discover(cfg, session=fake)

    assert len(fake.calls) == 1, "must not probe any known path after a network-layer failure"
    assert plan.probing_skipped is True
    assert plan.probing_skipped_reason == reason
    assert plan.homepage_reachable is False
    assert len(plan.seeds) == 1
    assert plan.seeds[0].page_type == "homepage"
    assert plan.seeds[0].present is False
    assert any("skipped known-path" in e for e in plan.errors)


def test_credentials_are_cleared_even_on_fake_session(cfg):
    fake = FakeSession(homepage=rex.ConnectTimeout())
    _discover(cfg, session=fake)
    assert fake.auth is None


# --- homepage returns an HTTP response -> probing continues -----------------


@pytest.mark.parametrize("status", [404, 502, 503, 520])
def test_http_error_status_still_probes(cfg, status):
    """404/502/503/520 are HTTP responses, not network failures."""
    fake = FakeSession(homepage=_FakeResp(status, text="<html>err</html>"), probe=_FakeResp(404))
    plan = _discover(cfg, session=fake)

    assert plan.probing_skipped is False
    assert plan.homepage_reachable is True
    assert plan.seeds[0].http_status == status
    assert len(fake.calls) > 1, "known paths must still be probed"


def test_redirect_status_still_probes(cfg):
    fake = FakeSession(homepage=_FakeResp(301, text=""), probe=_FakeResp(404))
    plan = _discover(cfg, session=fake)
    assert plan.probing_skipped is False
    assert plan.homepage_reachable is True
    assert len(fake.calls) > 1


def test_too_many_redirects_still_probes(cfg):
    """A redirect loop means the server answered; keep probing."""
    fake = FakeSession(homepage=rex.TooManyRedirects(), probe=_FakeResp(404))
    plan = _discover(cfg, session=fake)
    assert plan.probing_skipped is False
    assert len(fake.calls) > 1


def test_successful_homepage_probes_and_finds_seeds(cfg):
    with FixtureSite() as site:
        plan = discover_seeds(
            service_id="svc_00000000", host="127.0.0.1", canonical_url=site.base_url, cfg=cfg
        )
    assert plan.probing_skipped is False
    assert plan.homepage_reachable is True
    assert plan.seeds[0].http_status == 200
    assert len(plan.seeds) > 1


# --- configurable timeout ---------------------------------------------------


def test_request_timeout_defaults_to_10(cfg):
    assert cfg["seeds"]["request_timeout_seconds"] == 10
    fake = FakeSession(homepage=_FakeResp(200, text="<html></html>"))
    plan = _discover(cfg, session=fake)
    assert plan.request_timeout_seconds == 10
    assert fake.calls[0][1] == 10  # timeout passed to session.get


def test_request_timeout_is_configurable(cfg):
    cfg2 = {**cfg, "seeds": {**cfg["seeds"], "request_timeout_seconds": 3}}
    fake = FakeSession(homepage=_FakeResp(200, text="<html></html>"))
    plan = _discover(cfg2, session=fake)
    assert plan.request_timeout_seconds == 3
    assert fake.calls[0][1] == 3


def test_legacy_timeout_key_is_fallback(cfg):
    seeds = {k: v for k, v in cfg["seeds"].items() if k != "request_timeout_seconds"}
    seeds["link_discovery_timeout_seconds"] = 7
    cfg2 = {**cfg, "seeds": seeds}
    fake = FakeSession(homepage=_FakeResp(200, text="<html></html>"))
    plan = _discover(cfg2, session=fake)
    assert plan.request_timeout_seconds == 7


# --- timing bound (synthetic unreachable host) ------------------------------


def test_unreachable_host_discovery_is_bounded(cfg):
    """Against a blackhole, discovery costs ~one timeout, not one-per-path.

    With the old behaviour this would be ~13 sequential probes each waiting the
    full timeout; the fix short-circuits after the homepage read timeout.
    """
    cfg2 = {**cfg, "seeds": {**cfg["seeds"], "request_timeout_seconds": 1}}
    with Blackhole() as bh:
        start = time.monotonic()
        plan = discover_seeds(
            service_id="svc_00000000", host="127.0.0.1", canonical_url=bh.base_url, cfg=cfg2
        )
        elapsed = time.monotonic() - start

    assert plan.probing_skipped is True
    assert plan.probing_skipped_reason == "read_timeout_no_response"
    assert len(plan.seeds) == 1
    # One homepage attempt (~1s). Old behaviour would be ~13-14× that.
    assert elapsed < 6, f"bounded discovery took {elapsed:.1f}s; expected ~1× the 1s timeout"
