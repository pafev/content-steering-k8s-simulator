"""DASH Content Steering endpoint; all learning state lives in Redis."""
import hashlib
import json
import os
import random
import time
import uuid

import redis
from flask import Flask, jsonify, request

from dash_parser import DashParser
from policies import rank_pathways

PATHWAYS = ["cdn-1", "cdn-2", "cdn-3"]


def create_app(connection=None):
    app = Flask(__name__)
    db = connection or redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True,
        socket_connect_timeout=1, socket_timeout=1,
    )
    ttl = int(os.getenv("STEERING_TTL_SECONDS", "5"))
    retention = int(os.getenv("RUN_TTL_SECONDS", "86400"))
    feedback_age = int(os.getenv("FEEDBACK_MAX_AGE_SECONDS", "60"))

    @app.get("/healthz")
    def health():
        try:
            db.ping()
            return jsonify(status="ok")
        except redis.RedisError:
            return jsonify(status="unavailable"), 503

    @app.get("/manifest.json")
    def steering():
        run_id, sid = request.args.get("run_id", ""), request.args.get("sid", "")
        priority, decision_id = PATHWAYS, None
        try:
            # Registration is optional for playback, required for shared learning.
            session = db.hgetall(f"session:{sid}") if sid else {}
            raw_config = db.get(f"run:{run_id}:config") if run_id else None
            if raw_config and session.get("run_id") == run_id:
                config = json.loads(raw_config)
                sequence = db.incr(f"run:{run_id}:sequence")
                db.expire(f"run:{run_id}:sequence", retention)
                pipe = db.pipeline()
                for pathway in PATHWAYS:
                    pipe.hgetall(f"run:{run_id}:model:{pathway}")
                pipe.get(f"run:{run_id}:last_feedback")
                *models, last_feedback = pipe.execute()
                stats = dict(zip(PATHWAYS, models))
                # Freshness does not erase classical cumulative model memory.
                stale = bool(last_feedback) and time.time() - float(last_feedback) > feedback_age
                buffer_ms = max(0.0, float(session.get("buffer_ms", 0)))
                context = [1.0, buffer_ms / (buffer_ms + 10000.0)]
                seed = hashlib.sha256(f"{config['seed']}:{sequence}".encode()).hexdigest()
                priority = rank_pathways(
                    config["strategy"], PATHWAYS, {} if stale else stats,
                    context, random.Random(seed),
                )
                decision_id = uuid.uuid4().hex
                decision = dict(
                    id=decision_id, run_id=run_id, sid=sid, sequence=sequence,
                    strategy=config["strategy"], context=context,
                    priority=priority, created_at=time.time(), consumed=False,
                    stale_feedback=stale,
                )
                pipe = db.pipeline()
                pipe.set(f"decision:{decision_id}", json.dumps(decision), ex=feedback_age)
                pipe.set(f"run:{run_id}:last_decision", json.dumps(decision), ex=retention)
                pipe.xadd(f"run:{run_id}:decisions", {"data": json.dumps(decision)}, maxlen=5000)
                pipe.expire(f"run:{run_id}:decisions", retention)
                pipe.expire(f"run:{run_id}:config", retention)
                pipe.execute()
        except redis.RedisError:
            app.logger.warning("Redis unavailable; using fixed playback fallback")
            priority, decision_id = PATHWAYS, None
        params = {k: v for k, v in (("run_id", run_id), ("sid", sid), ("decision_id", decision_id)) if v}
        public_path = request.headers.get("X-Forwarded-Prefix", "") + "/manifest.json"
        response = jsonify(DashParser().build(priority, params, ttl, public_path))
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


app = create_app()
