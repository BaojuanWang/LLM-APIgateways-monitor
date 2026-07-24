"""Monitor-sentinel handling and the non-destructive exclusions layer."""

from __future__ import annotations

import csv

import pytest

from archivelib.config import DEFAULT_CONFIG
from archivelib.exclusions import (
    EXCLUSION_FIELDS,
    ExclusionsError,
    load_exclusions,
    load_exclusions_or_default,
)
from archivelib.identity import (
    MONITOR_SENTINELS,
    MonitorObservation,
    ServiceIdentity,
    group_by_service,
    is_monitor_sentinel,
    load_monitor_history,
    service_id_for_host,
)
from archivelib.queueplan import plan_queue

MONITOR_HEADER = (
    "timestamp,domain,platform_name,source,online_status,http_status,"
    "final_url,page_title,html_hash,redirect_chain,error"
)


def _write_monitor(repo, rows):
    (repo / "results").mkdir(parents=True, exist_ok=True)
    with open(repo / "results" / "monitor_results.csv", "w", encoding="utf-8", newline="") as fh:
        fh.write(MONITOR_HEADER + "\n")
        for r in rows:
            fh.write(r + "\n")


def _write_exclusions(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(EXCLUSION_FIELDS))
        w.writeheader()
        for r in rows:
            w.writerow(r)


# --- monitor sentinel -------------------------------------------------------


def test_hvoy_removed_is_a_documented_sentinel():
    assert "hvoy_removed" in MONITOR_SENTINELS
    assert is_monitor_sentinel("hvoy_removed")
    assert is_monitor_sentinel("  HVOY_REMOVED  ")
    assert not is_monitor_sentinel("api.example.com")
    assert not is_monitor_sentinel("")


def test_load_monitor_history_excludes_sentinel(tmp_path):
    _write_monitor(
        tmp_path,
        [
            "2026-06-15T00:00:00Z,hvoy_removed,,hvoy,SERVICE_STOPPED,,,,,,",
            "2026-06-15T00:00:00Z,real.example.test,Real,hvoy,ONLINE,200,https://real.example.test/,R,h1,,",
        ],
    )
    obs = load_monitor_history(tmp_path)
    hosts = {o.host for o in obs}
    assert "real.example.test" in hosts
    assert "hvoy_removed" not in hosts
    # observed-service count excludes the sentinel
    assert service_id_for_host("hvoy_removed") not in group_by_service(obs)


def test_sentinel_included_only_when_requested(tmp_path):
    _write_monitor(tmp_path, ["2026-06-15T00:00:00Z,hvoy_removed,,hvoy,SERVICE_STOPPED,,,,,,"])
    assert load_monitor_history(tmp_path) == []
    with_sentinel = load_monitor_history(tmp_path, include_sentinels=True)
    assert len(with_sentinel) == 1 and with_sentinel[0].host == "hvoy_removed"


def test_historical_rows_are_never_edited(tmp_path):
    """The filter is read-time only: the CSV on disk is untouched."""
    _write_monitor(tmp_path, ["2026-06-15T00:00:00Z,hvoy_removed,,hvoy,SERVICE_STOPPED,,,,,,"])
    before = (tmp_path / "results" / "monitor_results.csv").read_bytes()
    load_monitor_history(tmp_path)
    assert (tmp_path / "results" / "monitor_results.csv").read_bytes() == before


# --- exclusions register: parsing -------------------------------------------


def _entry(domain, status, **kw):
    base = dict(domain=domain, status=status, reason="r", evidence="e", reviewed_at="2026-07-23", review_version="v1")
    base.update(kw)
    return base


def test_load_exclusions_parses_and_normalizes(tmp_path):
    p = tmp_path / "excl.csv"
    _write_exclusions(p, [_entry("Blog.MongoDB.org", "excluded"), _entry("openrouter.com", "questionable")])
    es = load_exclusions(p)
    assert {e.domain for e in es.excluded} == {"blog.mongodb.org"}
    assert {e.domain for e in es.questionable} == {"openrouter.com"}
    assert es.excluded_service_ids() == {service_id_for_host("blog.mongodb.org")}
    assert es.questionable_service_ids() == {service_id_for_host("openrouter.com")}


def test_load_exclusions_skips_unknown_status_and_blank_domain(tmp_path):
    p = tmp_path / "excl.csv"
    _write_exclusions(
        p,
        [
            _entry("a.test", "excluded"),
            _entry("b.test", "banned"),      # unknown status -> skipped
            _entry("", "excluded"),           # blank domain -> skipped
            _entry("# comment", "excluded"),  # comment -> skipped
        ],
    )
    es = load_exclusions(p)
    assert {e.domain for e in es.entries} == {"a.test"}


def test_load_exclusions_requires_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("domain,status\nx.test,excluded\n", encoding="utf-8")
    with pytest.raises(ExclusionsError, match="missing required columns"):
        load_exclusions(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(ExclusionsError, match="not found"):
        load_exclusions(tmp_path / "nope.csv")


def test_load_or_default_disabled_returns_none(tmp_path):
    assert load_exclusions_or_default(tmp_path, None, enabled=False) is None
    assert load_exclusions_or_default(tmp_path, None, enabled=True) is None  # no default file


# --- plan_queue integration -------------------------------------------------


def _inventory(hosts):
    inv = {}
    for h in hosts:
        sid = service_id_for_host(h)
        inv[sid] = ServiceIdentity(
            service_id=sid, host=h, canonical_url=f"https://{h}/", platform_name="", source="discovery",
            inventory_file="data/master_sites.csv", inventory_file_sha256="0" * 64,
            inventory_row={"domain": h}, inventory_row_sha256="1" * 64,
        )
    return inv


def _obs(host, status="ONLINE"):
    return MonitorObservation("2026-05-01T00:00:00Z", host, "P", "hvoy", status, "200", f"https://{host}/", "T", "h", "", "")


def test_plan_queue_excludes_and_reports(tmp_path):
    hosts = ["good1.test", "good2.test", "bad.test"]
    inv = _inventory(hosts)
    obs = [_obs(h) for h in hosts]  # all first_capture candidates
    p = tmp_path / "excl.csv"
    _write_exclusions(p, [_entry("bad.test", "excluded", reason="unrelated platform")])
    es = load_exclusions(p)

    q = plan_queue(inventory=inv, observations=obs, history={}, cfg=DEFAULT_CONFIG,
                   now_utc="2026-05-02T00:00:00Z", max_sites=50, exclusions=es)
    selected_hosts = {e["host"] for e in q["entries"]}
    assert "bad.test" not in selected_hosts
    assert {"good1.test", "good2.test"} <= selected_hosts
    assert q["counts"]["excluded_candidates"] == 1
    assert q["excluded"][0]["host"] == "bad.test"
    assert q["excluded"][0]["exclusion_reason"] == "unrelated platform"
    assert q["exclusions"]["applied"] is True


def test_plan_queue_questionable_is_flagged_not_removed(tmp_path):
    hosts = ["ok.test", "maybe.test"]
    inv = _inventory(hosts)
    obs = [_obs(h) for h in hosts]
    p = tmp_path / "excl.csv"
    _write_exclusions(p, [_entry("maybe.test", "questionable", reason="uncertain aggregator")])
    es = load_exclusions(p)

    q = plan_queue(inventory=inv, observations=obs, history={}, cfg=DEFAULT_CONFIG,
                   now_utc="2026-05-02T00:00:00Z", max_sites=50, exclusions=es)
    selected = {e["host"]: e for e in q["entries"]}
    assert "maybe.test" in selected, "questionable must remain selectable, not removed"
    assert selected["maybe.test"].get("questionable") is True
    assert selected["maybe.test"]["questionable_reason"] == "uncertain aggregator"
    assert q["counts"]["questionable_selected"] == 1
    assert selected["ok.test"].get("questionable") is None


def test_plan_queue_without_exclusions_is_unchanged(tmp_path):
    hosts = ["a.test", "b.test"]
    inv = _inventory(hosts)
    obs = [_obs(h) for h in hosts]
    q = plan_queue(inventory=inv, observations=obs, history={}, cfg=DEFAULT_CONFIG,
                   now_utc="2026-05-02T00:00:00Z", max_sites=50)
    assert q["counts"]["excluded_candidates"] == 0
    assert q["counts"]["questionable_selected"] == 0
    assert q["exclusions"]["applied"] is False
    assert {e["host"] for e in q["entries"]} == {"a.test", "b.test"}
