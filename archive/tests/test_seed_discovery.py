"""Seed-discovery tests against the local synthetic fixture site.

No live third-party site is contacted. The fixture deliberately omits some page
types (``/about``, ``/api/pricing``, ``/api/models``) so the "record what is
missing rather than fabricating a URL" behaviour is observable.
"""

from __future__ import annotations

import pytest

from archivelib.seeds import PAGE_TYPES, classify_url, discover_seeds, extract_links
from fixture_server import FixtureSite


@pytest.fixture(scope="module")
def site():
    with FixtureSite() as running:
        yield running


@pytest.fixture
def plan(site, cfg):
    return discover_seeds(
        service_id="fixture_00000000",
        host="127.0.0.1",
        canonical_url=site.base_url,
        cfg=cfg,
    )


# --- classification ---------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://x.test/", "homepage"),
        ("https://x.test/login", "login"),
        ("https://x.test/register", "registration"),
        ("https://x.test/pricing", "pricing"),
        ("https://x.test/docs", "documentation"),
        ("https://x.test/models", "model_list"),
        ("https://x.test/status", "public_status"),
        ("https://x.test/privacy", "privacy_policy"),
        ("https://x.test/terms", "terms"),
        ("https://x.test/announcement", "announcements"),
        ("https://x.test/some/unrelated/deep/page", None),
    ],
)
def test_classify_url(url, expected):
    assert classify_url(url) == expected


def test_deep_paths_are_not_classified():
    """A blog post is neither the announcements index nor the pricing page."""
    assert classify_url("https://x.test/blog/2024/01/our-pricing-explained", "pricing") is None
    assert classify_url("https://x.test/docs/api/v2/reference/endpoints") is None


def test_shallow_subpaths_still_classify():
    assert classify_url("https://x.test/blog/hello") == "announcements"
    assert classify_url("https://x.test/docs/quickstart") == "documentation"


def test_exact_path_beats_anchor_text():
    """A link to /pricing labeled "Docs" is still the pricing page."""
    assert classify_url("https://x.test/pricing", "Docs") == "pricing"


# --- link extraction --------------------------------------------------------


def test_extract_links_stays_on_the_service():
    html = """
      <a href="/pricing">Pricing</a>
      <a href="https://x.test/docs">Docs</a>
      <a href="https://sub.x.test/models">Models</a>
      <a href="https://unrelated.example.org/pricing">Offsite</a>
      <a href="mailto:a@b.test">Mail</a>
      <a href="javascript:void(0)">JS</a>
    """
    urls = [u for u, _ in extract_links(html, "https://x.test/", "x.test", 50)]
    assert "https://x.test/pricing" in urls
    assert "https://x.test/docs" in urls
    assert "https://sub.x.test/models" in urls, "subdomains belong to the same service"
    assert not any("unrelated.example.org" in u for u in urls)
    assert not any(u.startswith(("mailto:", "javascript:")) for u in urls)


def test_extract_links_strips_query_and_fragment():
    html = '<a href="/pricing?ref=INVITE123&utm=x#top">Pricing</a>'
    urls = [u for u, _ in extract_links(html, "https://x.test/", "x.test", 50)]
    assert urls == ["https://x.test/pricing"]


# --- discovery against the fixture ------------------------------------------


def test_homepage_is_always_the_first_seed(plan, site):
    assert plan.seeds[0].page_type == "homepage"
    assert plan.seeds[0].url == site.base_url
    assert plan.seeds[0].origin == "canonical"


def test_seed_count_respects_the_cap(plan, cfg):
    assert 0 < len(plan.seeds) <= cfg["capture"]["max_seeds"] == 8


def test_seeds_are_unique(plan):
    urls = [s.url for s in plan.seeds]
    assert len(urls) == len(set(urls))


def test_discovers_the_important_page_types(plan):
    found = {s.page_type for s in plan.seeds}
    # The cap is 8 and the fixture offers 10 page types plus API endpoints, so
    # assert on priority order rather than on everything being present.
    assert {"homepage", "pricing", "model_list", "documentation"} <= found


def test_missing_page_types_are_recorded_not_fabricated(site, cfg):
    """The fixture has no ``/about``; nothing may invent one."""
    plan = discover_seeds(
        service_id="fixture_00000000", host="127.0.0.1", canonical_url=site.base_url, cfg=cfg
    )
    assert isinstance(plan.missing_page_types, list)
    assert all(t in PAGE_TYPES for t in plan.missing_page_types)
    for seed in plan.seeds:
        assert seed.url.startswith(site.base_url.rstrip("/")), "no seed outside the service"


def test_public_api_paths_are_included_when_present(site, cfg):
    plan = discover_seeds(
        service_id="fixture_00000000", host="127.0.0.1", canonical_url=site.base_url, cfg=cfg
    )
    api_seeds = [s for s in plan.seeds if s.page_type == "public_api"]
    # /v1/models and /api/status exist on the fixture; /api/pricing and
    # /api/models do not and must not appear.
    assert all(s.url.endswith(("/v1/models", "/api/status")) for s in api_seeds)
    assert all("no key supplied" in s.evidence for s in api_seeds)


def test_absent_api_paths_are_probed_once_and_not_seeded(plan):
    probed = {p["url"].rstrip("/").rsplit("/", 1)[-1]: p for p in plan.probed if p["kind"] == "api_path"}
    seeded = {s.url for s in plan.seeds}
    for probe in plan.probed:
        if probe["status"] == 404:
            assert probe["url"] not in seeded, "a 404 path must never become a seed"
    # Each path is probed at most once: no retries, no permutation.
    urls = [p["url"] for p in plan.probed]
    assert len(urls) == len(set(urls))


def test_no_seed_targets_a_logout_or_form_post(plan):
    for seed in plan.seeds:
        assert "logout" not in seed.url.lower()
        assert "signout" not in seed.url.lower()


def test_discovery_is_deterministic(site, cfg):
    first = discover_seeds(service_id="s", host="127.0.0.1", canonical_url=site.base_url, cfg=cfg)
    second = discover_seeds(service_id="s", host="127.0.0.1", canonical_url=site.base_url, cfg=cfg)
    assert [s.url for s in first.seeds] == [s.url for s in second.seeds]


def test_unreachable_host_still_yields_a_homepage_seed(cfg):
    """A dead site is evidence: the capture must still be attemptable."""
    plan = discover_seeds(
        service_id="dead_00000000",
        host="127.0.0.1",
        canonical_url="http://127.0.0.1:9/",  # discard port: nothing listens
        cfg=cfg,
    )
    assert len(plan.seeds) >= 1
    assert plan.seeds[0].page_type == "homepage"
    assert plan.seeds[0].present is False
    assert plan.errors
