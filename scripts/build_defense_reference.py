"""Build an immutable calibration reference from six independent honest pilots."""
import hashlib
import json
import math
import sys
from pathlib import Path

root, output = map(Path, sys.argv[1:3])
paths = sorted(root.glob("*/*/multi-*/summary.json"))
runs = []
samples = {pathway: [] for pathway in ("cdn-1", "cdn-2", "cdn-3")}
for path in paths:
    summary = json.loads(path.read_text())
    cfg = summary["configuration"]
    if not summary["success"] or cfg["malicious_count"] != 0 or cfg["seconds"] != 120:
        raise SystemExit(f"Invalid calibration pilot: {path}")
    if cfg["reward_lambda"] != 10 or cfg["max_video_kbps"] != 3000:
        raise SystemExit(f"Wrong calibration conditions: {path}")
    if cfg["fault_sha256"] != hashlib.sha256(Path("manifests/risk-matrix-netchaos.yaml").read_bytes()).hexdigest():
        raise SystemExit(f"Wrong NetChaos manifest: {path}")
    cache = json.loads((path.parent / "cache-validation.json").read_text())
    if cache.get("cached_non_hit_responses"):
        raise SystemExit(f"Cache validation failed: {path}")
    file = path.parent / "video-feedback.jsonl"
    if not file.exists():
        raise SystemExit(f"Missing raw calibration TTLBs: {file}")
    for line in file.read_text().splitlines():
        item = json.loads(line)
        value = item["ttlb_ms"]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise SystemExit(f"Invalid TTLB in {file}")
        samples[item["pathway"]].append(value)
    runs.append(summary["run_id"])
if len(runs) != 6 or len(set(runs)) != 6 or any(len(v) < 100 for v in samples.values()):
    raise SystemExit(f"Need six unique pilots and >=100 values per CDN: {len(runs)}, {[len(v) for v in samples.values()]}")
reference = dict(version=1, window_seconds=30, source_run_ids=runs,
                 fault_sha256=hashlib.sha256(Path("manifests/risk-matrix-netchaos.yaml").read_bytes()).hexdigest(),
                 samples=samples)
output.write_text(json.dumps(reference, sort_keys=True) + "\n")
print(output)
