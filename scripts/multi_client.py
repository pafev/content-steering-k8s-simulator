"""Warm CDN caches and observe real dash.js clients through the public gateway."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import urlopen
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ("ucb1", "linucb", "epsilon_greedy", "fixed", "random")


def positive(value):
    value = float(value)
    if value <= 0 or not value < float("inf"):
        raise argparse.ArgumentTypeError("must be finite and positive")
    return value


def fetch(url, timeout):
    with urlopen(url, timeout=timeout) as response:
        # Drain the entire response: HEAD would not fill the object cache.
        while response.read(1024 * 1024):
            pass
        return response.headers.get("X-Cache-Status", "missing")


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
    failures = [url for url, status in zip(urls, second) if status != "HIT"]
    result = {"objects_per_cdn": len(objects), "requests": len(urls) * 2,
              "first_pass_hits": first.count("HIT"), "verified_hits": second.count("HIT")}
    if failures:
        raise RuntimeError(f"Warmup verification failed for {len(failures)} objects; first: {failures[0]}. "
                           "Check cache capacity, object cacheability and concurrent traffic.")
    return result


def observe(playwright, args, strategy, output):
    run_id = f"multi-{strategy}-{uuid.uuid4().hex}"
    directory = output / run_id
    directory.mkdir()
    browser = playwright.chromium.launch(
        executable_path=args.browser, headless=not args.headed,
        args=["--autoplay-policy=no-user-gesture-required"],
    )
    contexts, pages, errors, sessions = [], [], [], []
    started = time.monotonic()
    event_file = (directory / "events.jsonl").open("w")
    samples_file = (directory / "samples.jsonl").open("w")

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
                   cache=response.headers.get("x-cache-status"))

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
                      "clients": clients, "state": state}
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
        problems = []
        if errors:
            problems.append("Browser JavaScript errors occurred")
        if len({session["sid"] for session in sessions}) != args.clients:
            problems.append("Client sessions are not unique")
        if any(client["time"] <= 0 or client["error"] for client in clients):
            problems.append("At least one client did not play successfully")
        if not feedback:
            problems.append("No accepted learning feedback")
        summary = {"run_id": run_id, "strategy": strategy, "sessions": sessions,
                   "configuration": vars(args), "final": sample, "errors": errors,
                   "problems": problems, "success": not problems}
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
    args = parser.parse_args()
    if args.clients < 1 or args.workers < 1 or not 0 <= args.stagger < float("inf"):
        parser.error("clients/workers must be positive and stagger finite and nonnegative")
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
            runs.append(observe(playwright, args, strategy, output))
    (output / "runs.json").write_text(json.dumps(runs, indent=2) + "\n")
    print(f"\nCompleted. Results: {output}", flush=True)


if __name__ == "__main__":
    main()
