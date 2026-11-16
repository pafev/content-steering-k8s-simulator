"""Run-scoped filtering of untrusted successful video timing reports."""
import hashlib
import json
import math
import os
from pathlib import Path

PATHWAYS = ("cdn-1", "cdn-2", "cdn-3")
WINDOW_SECONDS = 30


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty reference")
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


class TelemetryDefense:
    def __init__(self, reference=None):
        if reference is None:
            path = os.getenv("DEFENSE_REFERENCE_PATH")
            reference = json.loads(Path(path).read_text()) if path and Path(path).is_file() else None
        self.enabled = os.getenv("DEFENSE_ENABLED", "false").lower() == "true"
        if self.enabled and reference is None:
            raise ValueError("defense enabled without a reference")
        self.reference = reference
        if reference is not None:
            if reference.get("version") != 1 or reference.get("window_seconds") != WINDOW_SECONDS:
                raise ValueError("invalid defense reference version/window")
            for pathway in PATHWAYS:
                values = reference.get("samples", {}).get(pathway)
                if not isinstance(values, list) or len(values) < 100 or any(
                    isinstance(v, bool) or not isinstance(v, (int, float))
                    or not math.isfinite(v) or v < 0 for v in values
                ):
                    raise ValueError(f"insufficient/invalid reference for {pathway}")
            self.sha256 = hashlib.sha256(json.dumps(reference, sort_keys=True).encode()).hexdigest()
        else:
            self.sha256 = None

    def bounds(self, redis, run_id, pathway, now):
        key = f"run:{run_id}:defense:window:{pathway}"
        recent = [float(v.split(":", 1)[0]) for v in redis.zrangebyscore(key, now - WINDOW_SECONDS, now)]
        values = self.reference["samples"][pathway] + recent
        return percentile(values, .01), percentile(values, .99), len(recent)

    @staticmethod
    def classify(history, ttlb, low, high):
        abnormal = ttlb < low or ttlb > high
        recent = (history + [int(abnormal)])[-5:]
        return abnormal, recent, len(recent) >= 3 and sum(recent) >= 3
