import json
import time

from conftest import css, telemetry
from defense import TelemetryDefense
from store import TelemetryStore


def test_bilateral_filter_dedup_quarantine_and_run_isolation(db, monkeypatch):
    monkeypatch.setenv("DEFENSE_ENABLED", "true")
    reference = {"version": 1, "window_seconds": 30,
                 "samples": {p: list(range(100, 200)) for p in ("cdn-1", "cdn-2", "cdn-3")}}
    store = TelemetryStore(db, TelemetryDefense(reference))
    monkeypatch.setattr(telemetry, "store", store)
    css_client = css.create_app(db).test_client()
    store.register_session("run", "s")
    store.register_session("other", "o")
    from test_steering import decision, report
    _, token = decision(css_client, sid="s")
    for sequence, duration in enumerate((1, 500, 1)):
        event = report(token, sid="s", sequence=sequence, duration=duration)
        expected = "quarantined" if sequence == 2 else "filtered"
        assert store.record_cmcd_event(event) == expected
        assert store.record_cmcd_event(event) == "already_observed"
    assert store.get_state("run")["model"]["cdn-1"] == {}
    assert store.get_state("run")["defense"] == {"filtered": "2", "quarantined": "1"}
    assert store.record_cmcd_event(report(token, sid="s", sequence=3, duration=150)) == "quarantined"
    _, other_token = decision(css_client, run="other", sid="o")
    assert store.record_cmcd_event(report(other_token, sid="o", duration=150)) == "learned"
    assert store.get_state("other")["model"]["cdn-1"]["n"] == "1"


def test_rolling_window_expires_and_failure_still_learns(db, monkeypatch):
    monkeypatch.setenv("DEFENSE_ENABLED", "true")
    reference = {"version": 1, "window_seconds": 30,
                 "samples": {p: list(range(100, 200)) for p in ("cdn-1", "cdn-2", "cdn-3")}}
    store = TelemetryStore(db, TelemetryDefense(reference))
    css_client = css.create_app(db).test_client()
    from test_steering import decision, report
    store.register_session("run", "s")
    _, token = decision(css_client, sid="s")
    assert store.record_cmcd_event(report(token, sid="s", duration=150)) == "learned"
    key = "run:run:defense:window:cdn-1"
    assert db.zcard(key) == 1
    low, high, count = store.defense.bounds(db, "run", "cdn-1", time.time() + 31)
    assert count == 0 and low == 100 and high == 198
    failed = report(token, sid="s", sequence=1)
    failed["rc"] = 503
    failed.pop("ttlb")
    assert store.record_cmcd_event(failed) == "learned"
    assert store.get_state("run")["model"]["cdn-1"]["n"] == "2"
