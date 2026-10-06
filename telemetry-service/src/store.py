"""CMCD ingestion and shared, cumulative sufficient statistics in Redis."""
import hashlib
import json
import math
import os
import re
import time
from urllib.parse import parse_qs, urlsplit

import redis

from cmcd import cmcd_value, extract_cmcd
PATHWAYS = ["cdn-1", "cdn-2", "cdn-3"]
STRATEGIES = {"fixed", "random", "epsilon_greedy", "ucb1", "linucb"}
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", "3600"))
RUN_TTL = int(os.getenv("RUN_TTL_SECONDS", "86400"))


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def pathway_from_url(url):
    parsed = urlsplit(url)
    match = re.fullmatch(r"(cdn-[123])\.default\.svc\.cluster\.local", parsed.hostname or "")
    if match:
        return match[1]
    return None


class TelemetryStore:
    def __init__(self, connection=None):
        self.redis = connection or redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True,
            socket_connect_timeout=1, socket_timeout=1,
        )

    def ping(self):
        return bool(self.redis.ping())

    def register_session(self, run_id, sid, cid="", strategy="ucb1", seed=1):
        if not all(isinstance(v, str) and IDENTIFIER.fullmatch(v) for v in (run_id, sid)):
            raise ValueError("run_id and sid must contain 1-128 letters, digits, '_' or '-'")
        if strategy not in STRATEGIES or type(seed) is not int:
            raise ValueError("Unknown strategy or invalid seed")
        config = dict(strategy=strategy, seed=seed,
                      reward_version="cmcd-delivery-duration-v1",
                      policy_version=1, epsilon=0.2, linucb_alpha=1.0,
                      ucb1_bonus="sqrt(2*ln(completed_observations)/arm_observations)")
        session_key, config_key = f"session:{sid}", f"run:{run_id}:config"
        with self.redis.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(session_key, config_key)
                    previous_run = pipe.hget(session_key, "run_id")
                    previous_config = pipe.get(config_key)
                    if previous_run and previous_run != run_id:
                        raise ValueError("Session already belongs to another run; create a new sid")
                    if previous_config and json.loads(previous_config) != config:
                        raise ValueError("Run configuration differs; use a new run_id")
                    pipe.multi()
                    pipe.hset(session_key, mapping={"run_id": run_id, "cid": str(cid), "last_seen": time.time()})
                    pipe.expire(session_key, SESSION_TTL)
                    pipe.set(config_key, json.dumps(config), ex=RUN_TTL)
                    pipe.execute()
                    return
                except redis.WatchError:
                    continue

    def _session(self, sid):
        return self.redis.hgetall(f"session:{sid}") if isinstance(sid, str) else {}

    def _audit(self, pipe, run_id, source, payload, **extra):
        key = f"run:{run_id}:observations"
        pipe.xadd(key, {"data": json.dumps(dict(source=source, received_at=time.time(), payload=payload, **extra))}, maxlen=5000)
        pipe.expire(key, RUN_TTL)

    def record_access_log(self, log):
        cmcd = extract_cmcd(log)
        sid, pathway = cmcd.get("sid"), log.get("pathway")
        session = self._session(sid)
        if not session or pathway not in PATHWAYS:
            return False
        run_id = session["run_id"]
        key = f"run:{run_id}:cdn:{pathway}"
        pipe = self.redis.pipeline()
        pipe.hincrby(key, "request_count", 1)
        pipe.hincrby(key, "bytes", int(log.get("size", 0)))
        pipe.hincrbyfloat(key, "duration_sum_seconds", float(log.get("duration", 0)))
        if int(log.get("status", 0)) >= 400:
            pipe.hincrby(key, "error_count", 1)
        cache = log.get("cache_status", "")
        if cache in {"HIT", "MISS", "EXPIRED", "STALE", "UPDATING", "BYPASS", "REVALIDATED"}:
            pipe.hincrby(key, f"cache_{cache.lower()}_count", 1)
        pipe.hset(key, "last_seen", time.time())
        pipe.expire(key, RUN_TTL)
        pipe.expire(f"session:{sid}", SESSION_TTL)
        # CMCD inside this log is client-reported, not independently measured.
        self._audit(pipe, run_id, "cdn_log", log)
        pipe.execute()
        return True

    def record_cmcd_event(self, event):
        sid = event.get("sid")
        session = self._session(sid)
        if not session:
            return "unknown_session"
        run_id = session["run_id"]
        url = event.get("url", "")
        if not isinstance(url, str):
            return "invalid_url"
        pathway = pathway_from_url(url)
        key = f"run:{run_id}:cmcd:{pathway or 'session'}"
        pipe = self.redis.pipeline()
        pipe.hincrby(key, "event_count", 1)
        pipe.hincrby(key, f"event:{event['e']}", 1)
        ttlb = cmcd_value(event, "ttlb", "v")
        for field in ("ttfb", "ttlb", "msd"):
            value = cmcd_value(event, field, "v")
            # TTFB is a component of TTLB. dash.js can expose a wall-clock
            # timestamp as TTFB for an MPD ResourceTiming entry; do not turn
            # that structurally invalid pair into a meaningless aggregate.
            invalid_ttfb = (field == "ttfb" and number(value) and
                            number(ttlb) and ttlb >= 0 and value > ttlb)
            if number(value) and value >= 0 and not invalid_ttfb:
                pipe.hincrbyfloat(key, f"{field}_sum_ms", value)
                pipe.hincrby(key, f"{field}_count", 1)
        bl = cmcd_value(event, "bl", "v")
        if number(bl) and bl >= 0:
            pipe.hset(f"session:{sid}", "buffer_ms", bl)
        pipe.expire(f"session:{sid}", SESSION_TTL)
        pipe.expire(f"run:{run_id}:config", RUN_TTL)
        pipe.expire(key, RUN_TTL)
        pipe.execute()
        result = self._learn_response(run_id, sid, pathway, url, event)
        pipe = self.redis.pipeline()
        self._audit(pipe, run_id, "client_cmcd", event, learning=result)
        pipe.execute()
        return result

    def _learn_response(self, run_id, sid, pathway, url, event):
        """Credit the CDN attempted by one correlated CMCD video response."""
        if event.get("e") != "rr" or event.get("ot") != "v" or not pathway:
            return "observation_only"
        duration, status = cmcd_value(event, "ttlb", "v"), cmcd_value(event, "rc", "v")
        if type(status) is not int or not (status == 0 or 200 <= status < 300 or 400 <= status <= 599):
            return "invalid_response"
        if duration is not None and (not number(duration) or duration < 0):
            return "invalid_duration"
        if 200 <= status < 300:
            media_duration = cmcd_value(event, "d", "v")
            if not number(duration) or not number(media_duration) or media_duration <= 0:
                return "invalid_duration"
            reward = media_duration / (media_duration + duration)
        else:
            reward = 0.0
        decision_id = parse_qs(urlsplit(url).query).get("cs_decision", [""])[0]
        if not re.fullmatch(r"[a-f0-9]{32}", decision_id):
            return "uncorrelated"
        raw = self.redis.get(f"decision:{decision_id}")
        if not raw:
            return "expired_decision"
        decision = json.loads(raw)
        if decision["sid"] != sid or decision["run_id"] != run_id:
            return "session_mismatch"
        sequence = event.get("sn")
        observation_id = (str(sequence) if type(sequence) is int and sequence >= 0 else
                          hashlib.sha256(f"{url}|{event.get('ts')}".encode()).hexdigest())
        seen_key = f"run:{run_id}:response:{sid}:{observation_id}"
        model_key = f"run:{run_id}:model:{pathway}"
        x0, x1 = decision["context"]
        with self.redis.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(seen_key)
                    if pipe.exists(seen_key):
                        return "already_observed"
                    pipe.multi()
                    pipe.set(seen_key, decision_id, ex=RUN_TTL)
                    pipe.hincrby(model_key, "n", 1)
                    for field, value in dict(reward_sum=reward, a00=x0*x0, a01=x0*x1,
                                             a11=x1*x1, b0=reward*x0, b1=reward*x1).items():
                        pipe.hincrbyfloat(model_key, field, value)
                    pipe.expire(model_key, RUN_TTL)
                    pipe.set(f"run:{run_id}:last_feedback", time.time(), ex=RUN_TTL)
                    self._audit(pipe, run_id, "learning_update", event, decision=decision,
                                pathway=pathway, reward=reward)
                    pipe.execute()
                    return "learned"
                except redis.WatchError:
                    continue

    def get_state(self, run_id):
        pipe = self.redis.pipeline()
        pipe.get(f"run:{run_id}:config")
        pipe.get(f"run:{run_id}:last_decision")
        pipe.get(f"run:{run_id}:last_feedback")
        for kind in ("cdn", "cmcd", "model"):
            for pathway in PATHWAYS:
                pipe.hgetall(f"run:{run_id}:{kind}:{pathway}")
        pipe.hgetall(f"run:{run_id}:cmcd:session")
        config, decision, last_feedback, *values = pipe.execute()
        return dict(
            run_id=run_id, config=json.loads(config) if config else None,
            last_decision=json.loads(decision) if decision else None,
            last_feedback=float(last_feedback) if last_feedback else None,
            cdn=dict(zip(PATHWAYS, values[:3])),
            cmcd=dict(zip(PATHWAYS + ["session"], values[3:6] + [values[9]])),
            model=dict(zip(PATHWAYS, values[6:9])),
        )
