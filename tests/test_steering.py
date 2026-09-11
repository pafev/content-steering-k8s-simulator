import concurrent.futures
import json
import random
from urllib.parse import parse_qs, urlsplit

import pytest
import redis

from conftest import css
from policies import rank_pathways

PATHS = ["cdn-1", "cdn-2", "cdn-3"]


def decision(client, run="run", sid="honest"):
    result = client.get(f"/manifest.json?run_id={run}&sid={sid}")
    assert result.status_code == 200
    data = result.get_json()
    token = parse_qs(urlsplit(data["RELOAD-URI"]).query)["decision_id"][0]
    return data, token


def report(token, sid="honest", pathway="cdn-1", duration=100, **extra):
    return dict(e="rr", sid=sid, ts=123456, ot="v", rc=200, ttlb=duration,
                url=f"http://localhost/cdn{pathway[-1]}/video/seg-1.m4s?cs_decision={token}", **extra)


def test_standard_manifest_and_explicit_routes(services):
    client, _, _ = services
    data = client.get("/manifest.json").get_json()
    assert data == {"VERSION": 1, "TTL": 5, "RELOAD-URI": "/manifest.json", "PATHWAY-PRIORITY": PATHS}
    proxied = client.get("/manifest.json", headers={"X-Forwarded-Prefix": "/steering"}).get_json()
    assert proxied["RELOAD-URI"] == "/steering/manifest.json"
    assert client.get("/unknown").status_code == 404
    assert client.post("/manifest.json").status_code == 405
    assert client.post("/latency_event").status_code == 404


def test_two_clients_share_learning_other_run_is_isolated(services, db):
    client, _, store = services
    store.register_session("run", "honest")
    store.register_session("run", "other")
    store.register_session("independent", "third")
    for sid, duration in [("honest", 1000), ("other", 0)]:
        _, token = decision(client, sid=sid)
        assert store.record_cmcd_event(report(token, sid=sid, duration=duration)) == "learned"
    model = store.get_state("run")["model"]["cdn-1"]
    assert int(model["n"]) == 2
    assert float(model["reward_sum"]) == 1.5
    assert store.get_state("independent")["model"]["cdn-1"] == {}
    assert db.get("policy:run") is None  # no heuristic overriding the strategy


def test_decision_context_and_actual_pathway_survive_delay(services, db):
    client, _, store = services
    store.register_session("run", "honest", strategy="linucb")
    db.hset("session:honest", "buffer_ms", 10000)
    data, token = decision(client)
    actual = next(p for p in PATHS if p != data["PATHWAY-PRIORITY"][0])
    db.hset("session:honest", "buffer_ms", 90000)
    assert store.record_cmcd_event(report(token, pathway=actual)) == "learned"
    model = store.get_state("run")["model"][actual]
    assert float(model["a01"]) == 0.5
    assert float(model["a11"]) == 0.25


def test_duplicate_feedback_is_one_atomic_update(services):
    client, _, store = services
    store.register_session("run", "honest")
    _, token = decision(client)
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: store.record_cmcd_event(report(token)), range(16)))
    assert results.count("learned") == 1
    assert int(store.get_state("run")["model"]["cdn-1"]["n"]) == 1


def test_registration_and_feedback_boundaries(services, db):
    client, api, store = services
    store.register_session("run", "honest")
    with pytest.raises(ValueError):
        store.register_session("different", "honest")
    with pytest.raises(ValueError):
        store.register_session("run", "other", strategy="fixed")
    assert api.post("/v1/rum/events", json={}).status_code == 404
    _, token = decision(client)
    store.register_session("different", "other")
    assert store.record_cmcd_event(report(token, sid="other")) == "session_mismatch"
    assert store.record_cmcd_event(report(token, duration=float("nan"))) == "invalid_duration"
    audio = report(token)
    audio["ot"] = "a"
    assert store.record_cmcd_event(audio) == "observation_only"
    db.delete(f"decision:{token}")
    assert store.record_cmcd_event(report(token)) == "expired_decision"


def test_client_reports_enter_through_cmcd_http(services):
    client, api, store = services
    assert api.post("/v1/sessions", json={"run_id": "run", "sid": "honest"}).status_code == 204
    _, token = decision(client)
    body = f'e=rr,ot=v,rc=200,sid="honest",ts=123,ttlb=50,url="http://localhost/cdn1/a.m4s?cs_decision={token}",v=2'
    response = api.post("/v1/cmcd/events", data=body, content_type="application/cmcd")
    assert response.get_json()["results"] == {"learned": 1}
    assert store.get_state("run")["model"]["cdn-1"]["n"] == "1"


def test_invalid_ttfb_ttlb_pair_is_not_aggregated(services):
    _, _, store = services
    store.register_session("run", "honest")
    result = store.record_cmcd_event(dict(
        e="rr", ot="m", sid="honest", ts=123, rc=200,
        ttfb=1_700_000_000_000, ttlb=20,
        url="http://localhost/cdn1/manifest.mpd",
    ))
    assert result == "observation_only"
    aggregate = store.get_state("run")["cmcd"]["cdn-1"]
    assert "ttfb_count" not in aggregate
    assert aggregate["ttlb_count"] == "1"
    assert float(aggregate["ttlb_sum_ms"]) == 20


def test_cdn_cmcd_does_not_double_count_reward(services):
    _, _, store = services
    store.register_session("run", "honest")
    store.record_access_log(dict(pathway="cdn-1", status=200, size=100, duration=0.1,
        cache_status="HIT", request={"headers": {"CMCD": 'sid="honest",mtp=999999'}}))
    state = store.get_state("run")
    assert state["cdn"]["cdn-1"]["cache_hit_count"] == "1"
    assert state["model"]["cdn-1"] == {}


def test_stale_feedback_preserves_model_but_explores(services, db):
    client, _, store = services
    store.register_session("run", "honest")
    db.set("run:run:last_feedback", 1)
    db.hset("run:run:model:cdn-1", mapping={"n": 100, "reward_sum": 99})
    _, token = decision(client)
    assert json.loads(db.get(f"decision:{token}"))["stale_feedback"] is True
    assert db.hget("run:run:model:cdn-1", "n") == "100"


def test_redis_failure_keeps_playback_fallback():
    class Unavailable:
        def hgetall(self, key):
            raise redis.ConnectionError()
    client = css.create_app(Unavailable()).test_client()
    result = client.get("/manifest.json?run_id=r&sid=s")
    assert result.status_code == 200
    assert result.get_json()["PATHWAY-PRIORITY"] == PATHS


def test_ucb1_explores_and_uses_canonical_bonus():
    stats = {p: {"n": 10, "reward_sum": 5} for p in PATHS}
    stats["cdn-3"] = {"n": 1, "reward_sum": 0}
    assert rank_pathways("ucb1", PATHS, stats, [1, 0], random.Random(1))[0] == "cdn-3"
    stats["cdn-2"] = {}
    assert rank_pathways("ucb1", PATHS, stats, [1, 0], random.Random(1))[0] == "cdn-2"


def test_linucb_uses_disjoint_contextual_models():
    # Same evidence count, opposite response to the buffer feature.
    stats = {
        "cdn-1": dict(n=10, a00=10, a01=0, a11=10, b0=5, b1=5),
        "cdn-2": dict(n=10, a00=10, a01=0, a11=10, b0=6, b1=-5),
    }
    assert rank_pathways("linucb", PATHS[:2], stats, [1, 0], random.Random(1))[0] == "cdn-2"
    assert rank_pathways("linucb", PATHS[:2], stats, [1, 1], random.Random(1))[0] == "cdn-1"


@pytest.mark.parametrize("strategy", ["fixed", "random", "epsilon_greedy", "ucb1", "linucb"])
def test_seeded_policies_return_all_pathways(strategy):
    first = rank_pathways(strategy, PATHS, {}, [1, 0], random.Random(42))
    assert sorted(first) == PATHS
    assert first == rank_pathways(strategy, PATHS, {}, [1, 0], random.Random(42))
