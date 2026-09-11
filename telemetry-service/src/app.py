import json
import logging
import socketserver
import threading
from collections import Counter

import redis
from flask import Flask, jsonify, request

from cmcd import parse_cmcd
from logs import parse_access_log_datagram
from store import TelemetryStore, number

store = TelemetryStore()
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024


@app.errorhandler(redis.RedisError)
def redis_unavailable(error):
    app.logger.warning("Redis unavailable: %s", error)
    return jsonify(error="Telemetry unavailable"), 503


@app.get("/healthz")
def healthz():
    return jsonify(status="ok", redis=store.ping())


@app.post("/v1/sessions")
def register_session():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Expected a JSON object"), 400
    try:
        store.register_session(
            data.get("run_id"), data.get("sid"), data.get("cid", ""),
            data.get("strategy", "ucb1"), data.get("seed", 1),
        )
    except ValueError as error:
        return jsonify(error=str(error)), 400
    return "", 204


@app.post("/v1/cmcd/events")
def cmcd_events():
    if request.mimetype != "application/cmcd":
        return jsonify(error="Content-Type must be application/cmcd"), 415
    lines = [line.strip() for line in request.get_data(as_text=True).splitlines() if line.strip()]
    if not 1 <= len(lines) <= 100:
        return jsonify(error="Expected 1-100 CMCD records"), 400
    events = [parse_cmcd(line) for line in lines]
    if any(
        not isinstance(e.get("sid"), str) or e.get("e") not in {"rr", "ps", "e", "t"}
        or not number(e.get("ts")) for e in events
    ):
        return jsonify(error="Each record needs sid, numeric ts and a supported e"), 400
    results = Counter(store.record_cmcd_event(event) for event in events)
    return jsonify(results=results)


@app.get("/v1/state/<run_id>")
def state(run_id):
    return jsonify(store.get_state(run_id))


class CdnLogHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            store.record_access_log(parse_access_log_datagram(self.request[0]))
        except (ValueError, TypeError, KeyError, redis.RedisError):
            app.logger.exception("CDN log could not be ingested")


class CdnLogServer(socketserver.UDPServer):
    allow_reuse_address = True
    max_packet_size = 65535


def start_log_receiver(port=9000):
    # Bounded single receiver; UDP remains best effort, not a durable input.
    server = CdnLogServer(("0.0.0.0", port), CdnLogHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
