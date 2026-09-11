"""Bounded synthetic CMCD reports for the local simulator; no video playback."""
import argparse
import json
import math
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
import uuid


def request(base, path, data=None, content_type="application/json"):
    req = Request(base + path, data=data, headers={"Content-Type": content_type})
    with urlopen(req, timeout=10) as response:
        body = response.read()
        return json.loads(body) if body else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:5000")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--strategy", default="ucb1", choices=["fixed", "random", "epsilon_greedy", "ucb1", "linucb"])
    parser.add_argument("--clients", type=int, default=1)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--ttlb-ms", type=float, default=100)
    parser.add_argument("--pathway", choices=["cdn-1", "cdn-2", "cdn-3"])
    args = parser.parse_args()
    if not 1 <= args.clients <= 100 or not 1 <= args.rounds <= 100:
        parser.error("Use 1-100 clients and 1-100 rounds")
    if not math.isfinite(args.ttlb_ms) or args.ttlb_ms < 0:
        parser.error("ttlb-ms must be finite and nonnegative")
    base = args.base.rstrip("/")
    sessions = [str(uuid.uuid4()) for _ in range(args.clients)]
    for sid in sessions:
        request(base, "/telemetry/v1/sessions", json.dumps(dict(
            run_id=args.run_id, sid=sid, strategy=args.strategy, seed=1,
            cid="synthetic-client",
        )).encode())
    for round_number in range(args.rounds):
        for sid in sessions:
            manifest = request(base, "/steering/manifest.json?" + urlencode(dict(run_id=args.run_id, sid=sid)))
            token = parse_qs(urlsplit(manifest["RELOAD-URI"]).query)["decision_id"][0]
            chosen = manifest["PATHWAY-PRIORITY"][0]
            pathway = args.pathway or chosen
            url = f"{base}/cdn{pathway[-1]}/Eldorado/4sec/avc/100000/seg-1.m4s?cs_decision={token}"
            report = f'e=rr,ot=v,rc=200,sid="{sid}",sn={round_number},ts={int(time.time()*1000)},ttlb={args.ttlb_ms},url="{url}",v=2'
            result = request(base, "/telemetry/v1/cmcd/events", report.encode(), "application/cmcd")
            print(json.dumps(dict(sid=sid, recommended=chosen, reported=pathway, result=result)))
        if round_number + 1 < args.rounds:
            time.sleep(manifest["TTL"])


if __name__ == "__main__":
    main()
