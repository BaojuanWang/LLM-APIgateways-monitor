"""Preflight, configuration, and tool-pinning tests.

Covers the invariants that keep a capture reproducible and attributable:
pinned images (never ``latest``), a config hash that actually changes when the
config changes, service ids that do not collide, and environment metadata that
does not carry the operator's identity.
"""

from __future__ import annotations

import pytest

from archivelib.canonical import canonical_json, sha256_json
from archivelib.config import ConfigError, config_hash, load_config, validate_config
from archivelib.docker_tools import ImagePin, build_browsertrix_config, resolve_image_digest
from archivelib.envmeta import classify_site_condition, machine_id, utc_now_iso
from archivelib.identity import normalize_host, service_id_for_host
from archivelib.volumes import external_writable_volumes, list_candidate_volumes


# --- configuration ----------------------------------------------------------


def test_default_config_is_valid(cfg):
    validate_config(cfg)
    assert cfg["capture"]["max_seeds"] == 8
    assert cfg["capture"]["workers"] == 1
    assert cfg["browsertrix"]["tag"] == "1.12.4"
    assert cfg["singlefile"]["version"] == "2.0.83"


def test_latest_tag_is_rejected(cfg):
    cfg = dict(cfg)
    cfg["browsertrix"] = {**cfg["browsertrix"], "tag": "latest"}
    with pytest.raises(ConfigError, match="latest"):
        validate_config(cfg)


def test_wacz_generation_cannot_be_disabled(cfg):
    cfg = dict(cfg)
    cfg["browsertrix"] = {**cfg["browsertrix"], "generate_wacz": False}
    with pytest.raises(ConfigError, match="canonical"):
        validate_config(cfg)


def test_singlefile_docker_image_requires_digest(cfg):
    cfg = dict(cfg)
    cfg["singlefile"] = {**cfg["singlefile"], "docker_image": "some/image", "docker_digest": ""}
    with pytest.raises(ConfigError, match="digest"):
        validate_config(cfg)


@pytest.mark.parametrize("flag", ["allow_form_submission", "allow_authenticated_areas", "load_browser_profile"])
def test_unsafe_flags_cannot_be_enabled(cfg, flag):
    cfg = dict(cfg)
    cfg["safety"] = {**cfg["safety"], flag: True}
    with pytest.raises(ConfigError, match=flag):
        validate_config(cfg)


def test_seed_cap_is_bounded(cfg):
    cfg = dict(cfg)
    cfg["capture"] = {**cfg["capture"], "max_seeds": 500}
    with pytest.raises(ConfigError, match="max_seeds"):
        validate_config(cfg)


def test_config_hash_is_stable_and_sensitive(cfg, repo_root_path):
    assert config_hash(cfg) == config_hash(load_config(repo_root_path))
    changed = {**cfg, "capture": {**cfg["capture"], "max_seeds": 4}}
    assert config_hash(changed) != config_hash(cfg)


def test_config_hash_ignores_non_substantive_metadata(cfg):
    """``_meta`` records where the config came from; it must not change the hash."""
    tweaked = {**cfg, "_meta": {"config_file": "somewhere/else.toml"}}
    assert config_hash(tweaked) == config_hash(cfg)


# --- canonical hashing ------------------------------------------------------


def test_canonical_json_is_key_order_independent():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
    assert sha256_json({"b": 1, "a": 2}) == sha256_json({"a": 2, "b": 1})


# --- identity ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://Example.COM/path?q=1", "example.com"),
        ("http://user:pw@example.com:8443/x", "example.com"),
        ("example.com.", "example.com"),
        ("API.Example.com", "api.example.com"),
    ],
)
def test_normalize_host(raw, expected):
    assert normalize_host(raw) == expected


def test_service_id_is_stable():
    assert service_id_for_host("api.example.com") == service_id_for_host("https://API.example.com/x")


def test_service_id_preserves_host_level_identity():
    """Subdomains are distinct services; no eTLD+1 folding."""
    assert service_id_for_host("api.example.com") != service_id_for_host("example.com")


def test_service_id_does_not_collide_on_sanitization():
    """``a-b.com`` and ``a.b.com`` both slugify to ``a-b-com``.

    Without the hash suffix these two distinct services would share a corpus
    directory and silently interleave their captures.
    """
    left = service_id_for_host("a-b.example.test")
    right = service_id_for_host("a.b.example.test")
    assert left.startswith("a-b-example-test_")
    assert right.startswith("a-b-example-test_")
    assert left != right


# --- docker pinning ---------------------------------------------------------


def test_image_pin_prefers_digest_reference():
    pin = ImagePin(image="webrecorder/browsertrix-crawler", tag="1.12.4", digest="sha256:" + "a" * 64)
    assert pin.reference == "webrecorder/browsertrix-crawler@sha256:" + "a" * 64


def test_image_pin_falls_back_to_tag_without_digest():
    pin = ImagePin(image="img", tag="1.2.3")
    assert pin.reference == "img:1.2.3"


def test_resolve_image_digest_refuses_latest():
    pin = resolve_image_digest("webrecorder/browsertrix-crawler", "latest", pull=False)
    assert not pin.resolved
    assert "latest" in pin.error


def test_browsertrix_config_is_scoped_and_bounded(cfg):
    config = build_browsertrix_config(collection="c1", seeds=["https://x.test/", "https://x.test/pricing"], cfg=cfg)
    assert config["workers"] == 1
    assert config["generateWACZ"] is True
    assert config["saveState"] == "never"
    assert all(seed["scopeType"] in ("page", "page-spa") for seed in config["seeds"])
    assert "host" not in [seed["scopeType"] for seed in config["seeds"]]
    # No credential-bearing knobs may appear in a generated config.
    assert "profile" not in config
    assert not any(k.lower() in ("auth", "headers", "cookie") for k in config)


# --- environment ------------------------------------------------------------


def test_machine_id_is_pseudonymous():
    """Recorded machine identity must not be a hostname or username."""
    import getpass
    import socket

    mid = machine_id()
    assert len(mid) == 16
    assert mid == machine_id()
    assert socket.gethostname().lower() not in mid.lower()
    assert getpass.getuser().lower() not in mid.lower()


def test_utc_now_is_zulu_formatted():
    stamp = utc_now_iso()
    assert stamp.endswith("Z") and len(stamp) == 20


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(http_status=200, final_url="https://x.test/", original_host="x.test"), "ok"),
        (
            dict(http_status=200, final_url="https://x.test/", original_host="x.test", page_text_sample="This domain is for sale"),
            "parked_or_for_sale",
        ),
        (
            dict(http_status=403, final_url="https://x.test/", original_host="x.test", page_text_sample="Checking your browser"),
            "blocked_or_challenge",
        ),
        (dict(http_status=200, final_url="https://other.test/", original_host="x.test"), "redirected_offsite"),
        (dict(http_status=None, final_url="", original_host="x.test", error="dns failure"), "unavailable"),
        (dict(http_status=503, final_url="https://x.test/", original_host="x.test"), "unavailable"),
    ],
)
def test_site_condition_classification(kwargs, expected):
    assert classify_site_condition(**kwargs) == expected


def test_subdomain_redirect_is_not_offsite():
    assert (
        classify_site_condition(http_status=200, final_url="https://www.x.test/", original_host="x.test") == "ok"
    )


# --- volume enumeration -----------------------------------------------------


def test_volume_enumeration_never_returns_the_boot_disk():
    """`/Volumes/Macintosh HD` is a symlink to `/` and must be filtered out."""
    for volume in list_candidate_volumes():
        assert volume.mount_point != "/"
    for volume in external_writable_volumes():
        assert volume.is_external and volume.is_writable and not volume.is_root_volume
