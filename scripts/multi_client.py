"""Warm CDN caches and observe real dash.js clients through the public gateway."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import Request, urlopen
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ("ucb1", "linucb", "epsilon_greedy", "fixed", "random")
BROWSER_ACCEPT_ENCODING = "gzip, deflate, br, zstd"


def positive(value):
    value = float(value)
    if value <= 0 or not value < float("inf"):
        raise argparse.ArgumentTypeError("must be finite and positive")
    return value


def fetch(url, timeout):
    with urlopen(Request(url, headers={"Accept-Encoding": BROWSER_ACCEPT_ENCODING}), timeout=timeout) as response:
        # Drain the entire response: HEAD would not fill the object cache.
        digest, size = hashlib.sha256(), 0
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        return dict(cache=response.headers.get("X-Cache-Status", "missing"),
                    status=response.status, bytes=size, sha256=digest.hexdigest())


def warm_caches(base, bucket, mpd, workers, timeout):
    match = re.fullmatch(r"/cdn[123]/(.+\.mpd)", mpd)
    if not match:
        raise ValueError("--mpd must be a gateway path such as /cdn1/Eldorado/4sec/avc/manifest.mpd")
    manifest = (bucket / match[1]).resolve()
    if not manifest.is_relative_to(bucket.resolve()) or not manifest.is_file():
        raise ValueError(f"MPD not found inside bucket: {manifest}")
    # Expand the packaged SegmentTemplate layout, excluding unused encodings
    # left in the bucket but not advertised by this MPD.
    ns = {"d": "urn:mpeg:dash:schema:mpd:2011"}
    tree = ET.parse(manifest)
    objects = {manifest}
    for adaptation in tree.findall(".//d:AdaptationSet", ns):
        for representation in adaptation.findall("d:Representation", ns):
            if adaptation.find("d:BaseURL", ns) is not None or representation.find("d:BaseURL", ns) is not None:
                raise ValueError("Warmup does not support adaptation/representation BaseURL overrides")
            template = representation.find("d:SegmentTemplate", ns)
            if template is None:
                template = adaptation.find("d:SegmentTemplate", ns)
            if template is None:
                raise ValueError("Warmup requires representation/adaptation SegmentTemplate")
            for field in ("initialization", "media"):
                pattern = template.get(field, "")
                pattern = pattern.replace("$Bandwidth$", representation.get("bandwidth", ""))
                pattern = pattern.replace("$RepresentationID$", representation.get("id", ""))
                pattern = re.sub(r"\$(Number|Time)(%0\d+d)?\$", "*", pattern)
                if not pattern or "$" in pattern or urlsplit(pattern).scheme or pattern.startswith("/"):
                    raise ValueError(f"Unsupported relative SegmentTemplate: {pattern}")
                if ".." in Path(pattern).parts:
                    raise ValueError(f"Template escapes MPD directory: {pattern}")
                matches = [p for p in manifest.parent.glob(pattern) if p.is_file()]
                if not matches:
                    raise ValueError(f"No packaged objects match {pattern}")
                objects.update(matches)
    if len(objects) == 1:
        raise ValueError("MPD has no warmable representations")
    objects = sorted(objects)
    for obj in objects:
        if not obj.resolve().is_relative_to(bucket.resolve()):
            raise ValueError(f"Object points outside bucket: {obj}")
    urls = [f"{base}/cdn{cdn}/{quote(obj.relative_to(bucket).as_posix(), safe='/')}"
            for cdn in (1, 2, 3) for obj in objects]
    print(f"Warming {len(objects)} objects on each of 3 CDNs (two full GET passes)", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        first = list(pool.map(lambda url: fetch(url, timeout), urls))
        second = list(pool.map(lambda url: fetch(url, timeout), urls))
    failures = [dict(url=url, first=a, second=b) for url, a, b in zip(urls, first, second)
                if b["cache"] != "HIT" or b["status"] != 200 or a["sha256"] != b["sha256"]]
    # Gateway MPDs have rewritten authorities; media objects should match the
    # packaged bytes. Verify representative objects per CDN without extra GETs.
    representatives = []
    for cdn in (1, 2, 3):
        candidates = [(obj, a, b) for obj, a, b in zip(
            objects, first[(cdn-1)*len(objects):cdn*len(objects)],
            second[(cdn-1)*len(objects):cdn*len(objects)])
                      if obj.suffix != ".mpd"]
        for obj, a, b in candidates[:3]:
            expected = hashlib.sha256(obj.read_bytes()).hexdigest()
            representatives.append(dict(cdn=f"cdn-{cdn}", object=obj.relative_to(bucket).as_posix(),
                                        first=a, second=b, expected_sha256=expected,
                                        matches=a["sha256"] == expected and b["sha256"] == expected))
    failures.extend(item for item in representatives if not item["matches"])
    result = {"objects_per_cdn": len(objects), "requests": len(urls) * 2,
              "accept_encoding": BROWSER_ACCEPT_ENCODING,
              "first_pass_hits": sum(item["cache"] == "HIT" for item in first),
              "verified_hits": sum(item["cache"] == "HIT" for item in second),
              "representatives": representatives, "failures": failures[:20],
              "warmed_paths": [urlsplit(url).path for url in urls]}
    if failures:
        raise RuntimeError(f"Warmup verification failed for {len(failures)} objects; first: {failures[0]}. "
                           "Check cache capacity, object cacheability and concurrent traffic.")
    return result


def observe(playwright, args, strategy, output, warmup=None):
    run_id = f"multi-{strategy}-{uuid.uuid4().hex}"
    directory = output / run_id
    directory.mkdir()
    browser = playwright.chromium.launch(
        executable_path=args.browser, headless=not args.headed,
        args=["--autoplay-policy=no-user-gesture-required"],
    )
    contexts, pages, errors, sessions = [], [], [], []
    malicious_page, malicious_sid, malicious_started_at = None, None, None
    malicious_media, malicious_feedback = [], []
    started = time.monotonic()
    event_file = (directory / "events.jsonl").open("w")
    samples_file = (directory / "samples.jsonl").open("w")
    warmed = set(warmup["warmed_paths"]) if warmup else set()
    unexpected_misses = []

    def record(kind, client, **data):
        event_file.write(json.dumps({"elapsed": round(time.monotonic() - started, 3),
                                    "kind": kind, "client": client, **data}) + "\n")
        event_file.flush()

    def on_response(response, client):
        path = urlsplit(response.url).path
        if path == "/steering/manifest.json":
            try:
                record("steering", client, url=response.url, status=response.status,
                       response=response.json())
            except Exception as error:
                record("capture_error", client, message=str(error))
        elif path == "/telemetry/v1/cmcd/events":
            try:
                record("feedback", client, status=response.status, result=response.json())
            except Exception as error:
                record("capture_error", client, message=str(error))
        elif re.match(r"/cdn[123]/", path):
            record("media", client, url=response.url, status=response.status,
                   cache=response.headers.get("x-cache-status"),
                   range=response.request.headers.get("range"),
                   accept_encoding=response.request.all_headers().get("accept-encoding"),
                   vary=response.headers.get("vary"),
                   cache_control=response.headers.get("cache-control"))
            if warmed and path in warmed and not path.endswith(".mpd") and response.headers.get("x-cache-status") != "HIT":
                unexpected_misses.append(dict(client=client, url=response.url,
                                              status=response.status,
                                              cache=response.headers.get("x-cache-status"),
                                              range=response.request.headers.get("range")))

    def on_malicious_response(response):
        path = urlsplit(response.url).path
        if re.match(r"/cdn[123]/", path) and path.endswith(".m4s"):
            malicious_media.append(dict(url=response.url, status=response.status))
        elif path == "/telemetry/v1/cmcd/events":
            try:
                malicious_feedback.append(response.json())
            except Exception as error:
                errors.append({"client": "malicious", "error": str(error)})

    try:
        print(f"\nRun {run_id}\nArtifacts: {directory}", flush=True)
        for index in range(args.clients):
            context = browser.new_context()
            contexts.append(context)
            page = context.new_page()
            pages.append(page)
            client = index + 1
            page.on("response", lambda response, c=client: on_response(response, c))
            page.on("pageerror", lambda error, c=client: errors.append({"client": c, "error": str(error)}))
            query = urlencode({"run_id": run_id, "strategy": strategy, "mpd": args.mpd})
            page.goto(f"{args.base}/?{query}", timeout=args.timeout * 1000)
            page.get_by_role("button", name="Load video").click()
            page.wait_for_function("document.querySelector('video').readyState >= 1",
                                   timeout=args.timeout * 1000)
            sid = page.locator("#session-id").inner_text()
            sessions.append({"client": client, "sid": sid})
            record("session", client, sid=sid)
            page.evaluate("document.querySelector('video').play()")
            if index + 1 < args.clients and args.stagger:
                page.wait_for_timeout(args.stagger * 1000)

        # Duration starts once all clients are playing; earlier clients also play
        # during startup. Never loop/reset players automatically: it creates sids.
        deadline = time.monotonic() + args.seconds
        while True:
            if args.malicious_cdn and malicious_page is None and time.monotonic() - started >= args.malicious_start_after:
                context = browser.new_context()
                malicious_page = context.new_page()
                malicious_page.on("response", on_malicious_response)
                malicious_page.on("pageerror", lambda error: errors.append({"client": "malicious", "error": str(error)}))
                query = urlencode({"run_id": run_id, "strategy": strategy, "mpd": args.mpd,
                                   "attack_cdn": args.malicious_cdn,
                                   "attack_ttlb_ms": args.malicious_ttlb_ms})
                malicious_page.goto(f"{args.base}/?{query}", timeout=args.timeout * 1000)
                malicious_page.get_by_role("button", name="Load video").click()
                malicious_page.wait_for_function("document.querySelector('video').readyState >= 1",
                                                 timeout=args.timeout * 1000)
                malicious_sid = malicious_page.locator("#session-id").inner_text()
                malicious_page.evaluate("document.querySelector('video').play()")
                malicious_started_at = round(time.monotonic() - started, 3)
                print(f"  modified player started at t={malicious_started_at:.1f}s, sid={malicious_sid}", flush=True)
            response = contexts[0].request.get(
                f"{args.base}/telemetry/v1/state/{run_id}", timeout=args.timeout * 1000)
            if not response.ok:
                raise RuntimeError(f"Telemetry state returned HTTP {response.status}")
            state = response.json()
            clients = [page.evaluate("""() => {
                const v = document.querySelector('video');
                return {time: v.currentTime, ended: v.ended, paused: v.paused,
                    error: v.error?.message || null,
                    priority: document.getElementById('priority').textContent,
                    pathway: document.getElementById('active-pathway').textContent,
                    status: document.getElementById('status').textContent};
            }""") for page in pages]
            sample = {"elapsed": round(time.monotonic() - started, 3),
                      "clients": clients, "state": state,
                      "malicious_started_at": malicious_started_at}
            samples_file.write(json.dumps(sample) + "\n")
            samples_file.flush()
            scores = []
            for pathway, model in state["model"].items():
                n = int(model.get("n", 0))
                mean = f"{float(model.get('reward_sum', 0))/n:.3f}" if n else "—"
                scores.append(f"{pathway}: n={n} mean={mean}")
            print(f"t={sample['elapsed']:.1f}s | " + " | ".join(scores), flush=True)
            for index, client in enumerate(clients, 1):
                print(f"  client {index}: play={client['time']:.1f}s requested={client['pathway']} "
                      f"priority={client['priority']}", flush=True)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            pages[0].wait_for_timeout(min(args.interval, remaining) * 1000)

        feedback = sum(int(model.get("n", 0)) for model in state["model"].values())
        state = contexts[0].request.get(
            f"{args.base}/telemetry/v1/state/{run_id}", timeout=args.timeout * 1000).json()
        problems = []
        if errors:
            problems.append("Browser JavaScript errors occurred")
        if len({session["sid"] for session in sessions}) != args.clients:
            problems.append("Client sessions are not unique")
        if any(client["time"] <= 0 or client["error"] for client in clients):
            problems.append("At least one client did not play successfully")
        if not feedback:
            problems.append("No accepted learning feedback")
        if unexpected_misses:
            problems.append(f"{len(unexpected_misses)} warmed browser media requests were not cache HITs")
        malicious = None
        if args.malicious_cdn:
            if malicious_page is None:
                problems.append("Modified player did not start")
            else:
                audit = malicious_page.evaluate("window.__cmcdLieAudit || []")
                playback = malicious_page.evaluate("document.querySelector('video').currentTime")
                def media_identity(url):
                    parsed = urlsplit(url)
                    return parsed.path, parse_qs(parsed.query).get("cs_decision", [""])[0]
                delivered = {media_identity(item["url"]) for item in malicious_media if item["status"] == 200}
                matched = sum(media_identity(item["url"]) in delivered for item in audit)
                learned = sum(item.get("results", {}).get("learned", 0) for item in malicious_feedback)
                malicious = dict(sid=malicious_sid, started_at=malicious_started_at,
                                 playback_time=playback, audit=audit, media=malicious_media,
                                 feedback=malicious_feedback, matched_deliveries=matched)
                (directory / "modified-player.json").write_text(json.dumps(malicious, indent=2) + "\n")
                if not audit or matched != len(audit) or not learned or playback <= 0:
                    problems.append("Modified player did not deliver and report correlated video segments")
        (directory / "cache-validation.json").write_text(json.dumps({
            "warmed_browser_misses": unexpected_misses,
            "browser_media_checked": bool(warmed),
        }, indent=2) + "\n")
        summary = {"run_id": run_id, "strategy": strategy, "sessions": sessions,
                   "configuration": vars(args), "final": {**sample, "state": state}, "errors": errors,
                   "malicious": malicious, "problems": problems, "success": not problems}
        (directory / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
        if problems:
            raise RuntimeError("; ".join(problems))
        return {"run_id": run_id, "summary": str(directory / "summary.json")}
    except Exception as error:
        (directory / "failure.json").write_text(json.dumps({"error": str(error),
                                                          "sessions": sessions, "errors": errors}, indent=2))
        raise
    finally:
        browser.close()
        event_file.close()
        samples_file.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:5000")
    parser.add_argument("--mpd", default="/cdn1/Eldorado/4sec/avc/manifest.mpd")
    parser.add_argument("--bucket", type=Path, default=ROOT / "bucket")
    parser.add_argument("--strategy", choices=(*STRATEGIES, "all"), default="ucb1")
    parser.add_argument("--clients", type=int, default=5)
    parser.add_argument("--seconds", type=positive, default=60)
    parser.add_argument("--interval", type=positive, default=5)
    parser.add_argument("--stagger", type=float, default=1, help="Seconds between client starts")
    parser.add_argument("--timeout", type=positive, default=30, help="Request and startup timeout in seconds")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent warmup downloads")
    parser.add_argument("--browser", help="Chromium/Chrome/Brave executable; otherwise Playwright Chromium")
    parser.add_argument("--headed", action="store_true", help="Show the browser windows (requires a display)")
    parser.add_argument("--skip-warmup", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "multi-client")
    parser.add_argument("--malicious-cdn", choices=("cdn-1", "cdn-2", "cdn-3"),
                        help="Start one real player that falsifies this CDN's response TTLB")
    parser.add_argument("--malicious-ttlb-ms", type=int, default=20000)
    parser.add_argument("--malicious-start-after", type=float, default=15,
                        help="Seconds after the first honest client starts")
    args = parser.parse_args()
    if args.clients < 1 or args.workers < 1 or not 0 <= args.stagger < float("inf"):
        parser.error("clients/workers must be positive and stagger finite and nonnegative")
    if args.malicious_ttlb_ms <= 0 or not 0 <= args.malicious_start_after < float("inf"):
        parser.error("malicious TTLB must be positive and start delay finite and nonnegative")
    args.base = args.base.rstrip("/")
    args.bucket = args.bucket.resolve()
    from playwright.sync_api import sync_playwright
    output = args.output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    output.mkdir(parents=True)
    try:
        warmup = None if args.skip_warmup else warm_caches(args.base, args.bucket, args.mpd, args.workers, args.timeout)
    except Exception as error:
        (output / "warmup-failure.json").write_text(json.dumps({"error": str(error)}, indent=2) + "\n")
        raise
    (output / "warmup.json").write_text(json.dumps(warmup, indent=2) + "\n")
    runs = []
    with sync_playwright() as playwright:
        for strategy in (STRATEGIES[:3] if args.strategy == "all" else [args.strategy]):
            runs.append(observe(playwright, args, strategy, output, warmup))
    (output / "runs.json").write_text(json.dumps(runs, indent=2) + "\n")
    print(f"\nCompleted. Results: {output}", flush=True)


if __name__ == "__main__":
    main()
