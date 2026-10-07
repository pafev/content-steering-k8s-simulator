"""Warm CDN caches and observe one dash-client pod per client."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import socket
import statistics
import subprocess
import time
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.request import Request, urlopen
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
STRATEGIES = ("ucb1", "linucb", "epsilon_greedy", "fixed", "random")
BROWSER_ACCEPT_ENCODING = "gzip, deflate, br, zstd"
PLAYER_BASE = "http://localhost:8080"


def pathway_from_url(url):
    parsed = urlsplit(url)
    match = re.fullmatch(
        r"(cdn-[123])\.default\.svc\.cluster\.local", parsed.hostname or ""
    )
    if match:
        return match[1]
    return None


def cache_path(url):
    parsed = urlsplit(url)
    pathway = pathway_from_url(url)
    if not pathway:
        return None
    return f"/cdn{pathway[-1]}{parsed.path}"


class ServiceForwards:
    """Temporary host access for orchestration; player traffic stays in the cluster."""

    def __init__(self, output, warmup):
        self.output = output
        self.warmup = warmup
        self.processes = []
        self.bases = {}

    def __enter__(self):
        try:
            services = (["cdn-1", "cdn-2", "cdn-3"] if self.warmup else []) + [
                "telemetry-service"
            ]
            for service in services:
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                target = 30600 if service == "telemetry-service" else 80
                log = (self.output / f"{service}-port-forward.log").open("w")
                process = subprocess.Popen(
                    [
                        "kubectl",
                        "--context",
                        "kind-kind",
                        "port-forward",
                        f"service/{service}",
                        f"{port}:{target}",
                    ],
                    stdout=log,
                    stderr=log,
                )
                self.processes.append((process, log))
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"Port-forward for {service} exited; see {log.name}"
                        )
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=1):
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError(
                        f"Port-forward for {service} did not start; see {log.name}"
                    )
                self.bases[service] = f"http://127.0.0.1:{port}"
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        for process, log in self.processes:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            log.close()


class DashClients:
    """One remotely controlled Chromium pod per player; browser traffic stays in its pod."""

    def __init__(self, count, output, fault_manifest=None):
        self.names, self.forwards, self.endpoints = [], [], []
        self.output = output
        self.count = count
        self.fault_manifest = fault_manifest
        self.fault_applied = False

    def __enter__(self):
        try:
            for index in range(self.count):
                name = f"dash-client-{uuid.uuid4().hex[:8]}-{index + 1}"
                pod = {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {
                        "name": name,
                        "labels": {
                            "app": "dash-client",
                            "steering-client-index": str(index + 1),
                        },
                    },
                    "spec": {
                        "containers": [
                            {
                                "name": "player",
                                "image": "pafev/content-steering:client-latest",
                                "imagePullPolicy": "IfNotPresent",
                                "ports": [{"containerPort": 9222}],
                                "readinessProbe": {
                                    "exec": {
                                        "command": [
                                            "python",
                                            "-c",
                                            "import socket; socket.create_connection(('127.0.0.1', 9222), 1).close()",
                                        ]
                                    },
                                    "periodSeconds": 5,
                                },
                            }
                        ]
                    },
                }
                subprocess.run(
                    ["kubectl", "--context", "kind-kind", "apply", "-f", "-"],
                    input=json.dumps(pod),
                    text=True,
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
                self.names.append(name)
            subprocess.run(
                [
                    "kubectl",
                    "--context",
                    "kind-kind",
                    "wait",
                    "--for=condition=Ready",
                    "pod",
                    *self.names,
                    "--timeout=180s",
                ],
                check=True,
            )
            if self.fault_manifest:
                self.fault_applied = True
                applied_after = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                subprocess.run(
                    [
                        "kubectl",
                        "--context",
                        "kind-kind",
                        "apply",
                        "-f",
                        str(self.fault_manifest),
                    ],
                    check=True,
                )
                sources = ("cdn-1-edge-1", "cdn-2-edge-1", "cdn-3-edge-1")
                for _ in range(60):
                    result = subprocess.run(
                        [
                            "kubectl",
                            "--context",
                            "kind-kind",
                            "logs",
                            "-n",
                            "net-chaos-simulator-system",
                            "deployment/net-chaos-simulator-controller-manager",
                            f"--since-time={applied_after}",
                        ],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0 and all(
                        sum(
                            "Latency applied successfully" in line and source in line
                            for line in result.stdout.splitlines()
                        )
                        >= self.count
                        for source in sources
                    ):
                        break
                    time.sleep(0.5)
                else:
                    raise RuntimeError(
                        "NetChaos did not confirm all CDN-to-player rules"
                    )
            for name in self.names:
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                log = (self.output / f"{name}-port-forward.log").open("w")
                process = subprocess.Popen(
                    [
                        "kubectl",
                        "--context",
                        "kind-kind",
                        "port-forward",
                        f"pod/{name}",
                        f"{port}:9222",
                    ],
                    stdout=log,
                    stderr=log,
                )
                self.forwards.append((process, log))
                endpoint = f"http://127.0.0.1:{port}"
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError(
                            f"Port-forward for {name} exited; see {log.name}"
                        )
                    try:
                        with urlopen(endpoint + "/json/version", timeout=1):
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError(
                        f"Browser in {name} did not expose CDP; see {log.name}"
                    )
                self.endpoints.append(endpoint)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        cleanup_error = None
        if self.fault_applied:
            try:
                subprocess.run(
                    [
                        "kubectl", "--context", "kind-kind", "delete", "-f",
                        str(self.fault_manifest), "--ignore-not-found", "--wait=true",
                        "--timeout=90s",
                    ],
                    check=True,
                )
            except subprocess.CalledProcessError as error:
                cleanup_error = error
        for process, log in self.forwards:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            log.close()
        if self.names and not cleanup_error:
            subprocess.run(
                [
                    "kubectl",
                    "--context",
                    "kind-kind",
                    "delete",
                    "pod",
                    *self.names,
                    "--ignore-not-found",
                    "--wait=false",
                ],
                check=False,
            )
        if cleanup_error:
            raise RuntimeError("NetChaos fault cleanup did not finish") from cleanup_error


def positive(value):
    value = float(value)
    if value <= 0 or not value < float("inf"):
        raise argparse.ArgumentTypeError("must be finite and positive")
    return value


def fetch(url, timeout):
    with urlopen(
        Request(url, headers={"Accept-Encoding": BROWSER_ACCEPT_ENCODING}),
        timeout=timeout,
    ) as response:
        # Drain the entire response: HEAD would not fill the object cache.
        digest, size = hashlib.sha256(), 0
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        return dict(
            cache=response.headers.get("X-Cache-Status", "missing"),
            status=response.status,
            bytes=size,
            sha256=digest.hexdigest(),
        )


def read_state(base, run_id, timeout):
    url = f"{base}/v1/state/{run_id}"
    for attempt in range(3):
        try:
            with urlopen(url, timeout=timeout) as response:
                return json.load(response)
        except OSError:
            if attempt == 2:
                raise
            time.sleep(0.2)


def learned_video_report(body, result):
    """Extract the one accepted successful video report in a CMCD POST."""
    if result.get("results", {}).get("learned") != 1:
        return None
    lines = [line for line in (body or "").splitlines() if line]
    if len(lines) != 1:
        return None  # The experiment configures dash.js with batchSize=1.
    line = lines[0]
    if not re.search(r"(?:^|,)e=rr(?:,|$)", line) or not re.search(
        r"(?:^|,)ot=v(?:,|$)", line
    ):
        return None
    status = re.search(r"(?:^|,)rc=(\d+)(?=,|$)", line)
    duration = re.search(r"(?:^|,)d=(\d+)(?=,|$)", line)
    ttlb = re.search(r"(?:^|,)ttlb=(\d+)(?=,|$)", line)
    url = re.search(r'(?:^|,)url="([^"]+)"', line)
    if not all((status, duration, ttlb, url)) or not 200 <= int(status[1]) < 300:
        return None
    pathway = pathway_from_url(url[1])
    if (
        not pathway
        or not urlsplit(url[1]).path.endswith(".m4s")
        or int(duration[1]) <= 0
    ):
        return None
    return dict(pathway=pathway, ttlb_ms=int(ttlb[1]))


def warm_caches(cdn_bases, bucket, mpd, workers, timeout):
    match = re.fullmatch(r"/(.+\.mpd)", urlsplit(mpd).path)
    if not match:
        raise ValueError("--mpd must be a CDN MPD URL")
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
            if (
                adaptation.find("d:BaseURL", ns) is not None
                or representation.find("d:BaseURL", ns) is not None
            ):
                raise ValueError(
                    "Warmup does not support adaptation/representation BaseURL overrides"
                )
            template = representation.find("d:SegmentTemplate", ns)
            if template is None:
                template = adaptation.find("d:SegmentTemplate", ns)
            if template is None:
                raise ValueError(
                    "Warmup requires representation/adaptation SegmentTemplate"
                )
            for field in ("initialization", "media"):
                pattern = template.get(field, "")
                pattern = pattern.replace(
                    "$Bandwidth$", representation.get("bandwidth", "")
                )
                pattern = pattern.replace(
                    "$RepresentationID$", representation.get("id", "")
                )
                pattern = re.sub(r"\$(Number|Time)(%0\d+d)?\$", "*", pattern)
                if (
                    not pattern
                    or "$" in pattern
                    or urlsplit(pattern).scheme
                    or pattern.startswith("/")
                ):
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
    urls = [
        f"{cdn_bases[f'cdn-{cdn}']}/{quote(obj.relative_to(bucket).as_posix(), safe='/')}"
        for cdn in (1, 2, 3)
        for obj in objects
    ]
    print(
        f"Warming {len(objects)} objects on each of 3 CDNs (two full GET passes)",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=workers) as pool:
        first = list(pool.map(lambda url: fetch(url, timeout), urls))
        second = list(pool.map(lambda url: fetch(url, timeout), urls))
    failures = [
        dict(url=url, first=a, second=b)
        for url, a, b in zip(urls, first, second)
        if b["cache"] != "HIT" or b["status"] != 200 or a["sha256"] != b["sha256"]
    ]
    # Verify representative media objects per CDN without extra GETs.
    representatives = []
    for cdn in (1, 2, 3):
        candidates = [
            (obj, a, b)
            for obj, a, b in zip(
                objects,
                first[(cdn - 1) * len(objects) : cdn * len(objects)],
                second[(cdn - 1) * len(objects) : cdn * len(objects)],
            )
            if obj.suffix != ".mpd"
        ]
        for obj, a, b in candidates[:3]:
            expected = hashlib.sha256(obj.read_bytes()).hexdigest()
            representatives.append(
                dict(
                    cdn=f"cdn-{cdn}",
                    object=obj.relative_to(bucket).as_posix(),
                    first=a,
                    second=b,
                    expected_sha256=expected,
                    matches=a["sha256"] == expected and b["sha256"] == expected,
                )
            )
    failures.extend(item for item in representatives if not item["matches"])
    result = {
        "objects_per_cdn": len(objects),
        "requests": len(urls) * 2,
        "accept_encoding": BROWSER_ACCEPT_ENCODING,
        "first_pass_hits": sum(item["cache"] == "HIT" for item in first),
        "verified_hits": sum(item["cache"] == "HIT" for item in second),
        "representatives": representatives,
        "failures": failures[:20],
        "warmed_paths": [
            f"/cdn{cdn}/{obj.relative_to(bucket).as_posix()}"
            for cdn in (1, 2, 3)
            for obj in objects
        ],
    }
    if failures:
        raise RuntimeError(
            f"Warmup verification failed for {len(failures)} objects; first: {failures[0]}. "
            "Check cache capacity, object cacheability and concurrent traffic."
        )
    return result


def observe(playwright, args, strategy, output, warmup=None):
    run_id = f"multi-{strategy}-{uuid.uuid4().hex}"
    directory = output / run_id
    directory.mkdir()
    browsers = [
        playwright.chromium.connect_over_cdp(endpoint)
        for endpoint in args.player_endpoints
    ]
    contexts, pages, errors, sessions = [], [], [], []
    modified = {}
    started = time.monotonic()
    event_file = (directory / "events.jsonl").open("w")
    samples_file = (directory / "samples.jsonl").open("w")
    warmed = set(warmup["warmed_paths"]) if warmup else set()
    unexpected_misses = []
    video_reports = []
    gateway_requests = []

    def record(kind, client, **data):
        event_file.write(
            json.dumps(
                {
                    "elapsed": round(time.monotonic() - started, 3),
                    "kind": kind,
                    "client": client,
                    **data,
                }
            )
            + "\n"
        )
        event_file.flush()

    def on_response(response, client):
        parsed = urlsplit(response.url)
        path = parsed.path
        if parsed.hostname == "gateway.default.svc.cluster.local":
            gateway_requests.append(dict(client=client, url=response.url))
        pathway = pathway_from_url(response.url)
        if client in modified:
            if pathway and path.endswith(".m4s"):
                modified[client]["media"].append(
                    dict(url=response.url, status=response.status)
                )
        if (
            urlsplit(response.url).hostname
            == "steering-server.default.svc.cluster.local"
            and path == "/manifest.json"
        ):
            try:
                record(
                    "steering",
                    client,
                    url=response.url,
                    status=response.status,
                    response=response.json(),
                )
            except Exception as error:
                record("capture_error", client, message=str(error))
        elif (
            urlsplit(response.url).hostname
            == "telemetry-service.default.svc.cluster.local"
            and path == "/v1/cmcd/events"
        ):
            try:
                result = response.json()
                if client in modified:
                    modified[client]["feedback"].append(
                        {
                            "report": response.request.post_data,
                            "response": result,
                        }
                    )
                video = learned_video_report(response.request.post_data, result)
                if video:
                    video_reports.append(video)
                record("feedback", client, status=response.status, result=result)
            except Exception as error:
                if client in modified:
                    errors.append({"client": client, "error": str(error)})
                record("capture_error", client, message=str(error))
        elif pathway:
            record(
                "media",
                client,
                url=response.url,
                status=response.status,
                cache=response.headers.get("x-cache-status"),
                range=response.request.headers.get("range"),
                accept_encoding=response.request.all_headers().get("accept-encoding"),
                vary=response.headers.get("vary"),
                cache_control=response.headers.get("cache-control"),
            )
            if (
                warmed
                and cache_path(response.url) in warmed
                and not path.endswith(".mpd")
                and response.headers.get("x-cache-status") != "HIT"
            ):
                unexpected_misses.append(
                    dict(
                        client=client,
                        url=response.url,
                        status=response.status,
                        cache=response.headers.get("x-cache-status"),
                        range=response.request.headers.get("range"),
                    )
                )

    def start_player(page, query):
        page.goto(f"{PLAYER_BASE}/?{urlencode(query)}", timeout=args.timeout * 1000)
        page.evaluate("""() => {
            const video = document.querySelector('video');
            const metric = {requested: performance.now(), started: null,
                            waiting: null, rebufferMs: 0};
            const wait = () => {
                if (metric.started !== null && metric.waiting === null && !video.paused)
                    metric.waiting = performance.now();
            };
            video.addEventListener('waiting', wait);
            video.addEventListener('stalled', wait);
            video.addEventListener('playing', () => {
                const now = performance.now();
                if (metric.started === null) metric.started = now;
                if (metric.waiting !== null) {
                    metric.rebufferMs += now - metric.waiting;
                    metric.waiting = null;
                }
            });
            window.__viewerMetric = metric;
        }""")
        page.get_by_role("button", name="Load video").click()
        page.wait_for_function(
            "document.querySelector('video').readyState >= 1",
            timeout=args.timeout * 1000,
        )
        sid = page.locator("#session-id").inner_text()
        page.evaluate("document.querySelector('video').play()")
        return sid

    def viewer_snapshot(page):
        return page.evaluate("""() => {
            const m = window.__viewerMetric;
            const now = performance.now();
            return {playback: document.querySelector('video').currentTime,
                    rebuffer_ms: m.rebufferMs + (m.waiting === null ? 0 : now - m.waiting),
                    startup_ms: m.started === null ? null : m.started - m.requested};
        }""")

    try:
        print(f"\nRun {run_id}\nArtifacts: {directory}", flush=True)
        for index in range(args.clients):
            context = browsers[index].new_context(ignore_https_errors=True)
            contexts.append(context)
            page = context.new_page()
            pages.append(page)
            client = index + 1
            role = "modified" if client <= args.malicious_count else "honest"
            if role == "modified":
                modified[client] = {"page": page, "media": [], "feedback": []}
            page.on("response", lambda response, c=client: on_response(response, c))
            page.on(
                "pageerror",
                lambda error, c=client: errors.append(
                    {"client": c, "error": str(error)}
                ),
            )
            query = {"run_id": run_id, "strategy": strategy, "mpd": args.mpd}
            if role == "modified":
                query.update(
                    attack_cdn=args.malicious_cdn, attack_reward=args.attack_reward
                )
                if args.attack_delay:
                    query["attack_enabled"] = "false"
            sid = start_player(page, query)
            if role == "modified":
                modified[client]["sid"] = sid
            sessions.append({"client": client, "sid": sid, "role": role})
            record("session", client, sid=sid, role=role)
            if index + 1 < args.clients and args.stagger:
                page.wait_for_timeout(args.stagger * 1000)

        # The run duration starts when all players are active. Attack delay
        # postpones only false telemetry; metrics cover the full run.
        observation_start = round(time.monotonic() - started, 3)
        viewer_initial = [viewer_snapshot(page) for page in pages]
        run_start = time.monotonic()
        deadline = run_start + args.seconds
        attack_at = run_start + args.attack_delay if args.attack_delay else None
        while True:
            if attack_at is not None and time.monotonic() >= attack_at:
                for client, player in modified.items():
                    player["page"].evaluate("window.__cmcdLieEnabled = true")
                    record("attack_enabled", client)
                attack_at = None
            state = read_state(args.telemetry_base, run_id, args.timeout)
            clients = [
                page.evaluate("""() => {
                const v = document.querySelector('video');
                return {time: v.currentTime, ended: v.ended, paused: v.paused,
                    error: v.error?.message || null,
                    priority: document.getElementById('priority').textContent,
                    pathway: document.getElementById('active-pathway').textContent,
                    status: document.getElementById('status').textContent};
            }""")
                for page in pages
            ]
            sample = {
                "elapsed": round(time.monotonic() - started, 3),
                "clients": clients,
                "state": state,
            }
            samples_file.write(json.dumps(sample) + "\n")
            samples_file.flush()
            scores = []
            for pathway, model in state["model"].items():
                n = int(model.get("n", 0))
                mean = f"{float(model.get('reward_sum', 0)) / n:.3f}" if n else "—"
                scores.append(f"{pathway}: n={n} mean={mean}")
            print(f"t={sample['elapsed']:.1f}s | " + " | ".join(scores), flush=True)
            for index, client in enumerate(clients, 1):
                print(
                    f"  client {index}: play={client['time']:.1f}s requested={client['pathway']} "
                    f"priority={client['priority']}",
                    flush=True,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            wait = min(args.interval, remaining)
            if attack_at is not None:
                wait = min(wait, max(0, attack_at - time.monotonic()))
            pages[0].wait_for_timeout(wait * 1000)

        feedback = sum(int(model.get("n", 0)) for model in state["model"].values())
        state = read_state(args.telemetry_base, run_id, args.timeout)
        viewer_final = [viewer_snapshot(page) for page in pages]
        viewers = []
        for session, initial, final in zip(sessions, viewer_initial, viewer_final):
            played = max(0.0, final["playback"] - initial["playback"])
            rebuffer = max(0.0, (final["rebuffer_ms"] - initial["rebuffer_ms"]) / 1000)
            viewers.append(
                {
                    **session,
                    "played_seconds": played,
                    "rebuffer_seconds": rebuffer,
                    "buffering_ratio": rebuffer / (played + rebuffer)
                    if played + rebuffer
                    else None,
                    "startup_ms": final["startup_ms"],
                }
            )
        problems = []
        if errors:
            problems.append("Browser JavaScript errors occurred")
        if len({session["sid"] for session in sessions}) != args.clients:
            problems.append("Client sessions are not unique")
        if any(client["time"] <= 0 or client["error"] for client in clients):
            problems.append("At least one client did not play successfully")
        if any(
            viewer["buffering_ratio"] is None or viewer["startup_ms"] is None
            for viewer in viewers
        ):
            problems.append("At least one player has incomplete playback measurements")
        if not feedback:
            problems.append("No accepted learning feedback")
        if unexpected_misses:
            problems.append(
                f"{len(unexpected_misses)} browser media requests were not cache HITs"
            )
        if gateway_requests:
            problems.append(
                f"{len(gateway_requests)} dash-client requests went through the gateway"
            )
        malicious = None
        if modified:
            details = []
            for client, player in modified.items():
                audit = player["page"].evaluate("window.__cmcdLieAudit || []")

                def media_identity(url):
                    parsed = urlsplit(url)
                    return parsed.path, parse_qs(parsed.query).get("cs_decision", [""])[
                        0
                    ]

                delivered = {
                    media_identity(item["url"])
                    for item in player["media"]
                    if item["status"] == 200
                }
                matched = sum(
                    media_identity(item["url"]) in delivered for item in audit
                )
                learned_sequences = {
                    int(match[1])
                    for item in player["feedback"]
                    if item["response"].get("results", {}).get("learned", 0)
                    if (
                        match := re.search(
                            r"(?:^|,)sn=(\d+)(?=,|$)", item["report"] or ""
                        )
                    )
                }
                accepted = sum(item["sn"] in learned_sequences for item in audit)
                details.append(
                    dict(
                        client=client,
                        sid=player["sid"],
                        audit=audit,
                        media=player["media"],
                        feedback=player["feedback"],
                        matched_deliveries=matched,
                        accepted_falsified=accepted,
                    )
                )
                if matched != len(audit):
                    problems.append(
                        f"Modified player {client} reported video without a matching download"
                    )
            (directory / "modified-players.json").write_text(
                json.dumps(details, indent=2) + "\n"
            )
            malicious = dict(
                artifact="modified-players.json",
                count=len(modified),
                altered_reports=sum(len(item["audit"]) for item in details),
                matched_deliveries=sum(item["matched_deliveries"] for item in details),
                accepted_falsified=sum(item["accepted_falsified"] for item in details),
            )
            if not malicious["accepted_falsified"]:
                problems.append(
                    f"No falsified {args.malicious_cdn} report was accepted for learning"
                )
        delivery_calibration = {}
        for pathway in ("cdn-1", "cdn-2", "cdn-3"):
            values = sorted(
                item["ttlb_ms"] for item in video_reports if item["pathway"] == pathway
            )
            model = state["model"].get(pathway, {})
            count = int(model.get("n", 0))
            delivery_calibration[pathway] = {
                "successful_video_reports": len(values),
                "median_ttlb_ms": statistics.median(values) if values else None,
                "p90_ttlb_ms": values[(9 * len(values) - 1) // 10] if values else None,
                "learning_count": count,
                "mean_learning_reward": float(model.get("reward_sum", 0)) / count
                if count
                else None,
            }
        (directory / "cache-validation.json").write_text(
            json.dumps(
                {
                    "warmed_browser_misses": unexpected_misses,
                    "browser_media_checked": bool(warmed),
                    "gateway_requests": gateway_requests,
                },
                indent=2,
            )
            + "\n"
        )
        summary = {
            "run_id": run_id,
            "strategy": strategy,
            "sessions": sessions,
            "configuration": {
                k: v
                for k, v in vars(args).items()
                if k not in ("player_endpoints", "telemetry_base")
            },
            "observation_start": observation_start,
            "delivery_calibration": delivery_calibration,
            "viewers": viewers,
            "final": {**sample, "state": state},
            "errors": errors,
            "malicious": malicious,
            "problems": problems,
            "success": not problems,
        }
        (directory / "summary.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
        if problems:
            raise RuntimeError("; ".join(problems))
        return {"run_id": run_id, "summary": str(directory / "summary.json")}
    except Exception as error:
        (directory / "failure.json").write_text(
            json.dumps(
                {"error": str(error), "sessions": sessions, "errors": errors}, indent=2
            )
        )
        raise
    finally:
        for context in contexts:
            context.close()
        for browser in browsers:
            browser.close()
        event_file.close()
        samples_file.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mpd",
        default="https://cdn-1.default.svc.cluster.local/Eldorado/4sec/avc/manifest.mpd",
    )
    parser.add_argument("--bucket", type=Path, default=ROOT / "bucket")
    parser.add_argument("--strategy", choices=(*STRATEGIES, "all"), default="ucb1")
    parser.add_argument(
        "--clients",
        type=int,
        default=5,
        help="Total players, including modified players",
    )
    parser.add_argument("--seconds", type=positive, default=60)
    parser.add_argument(
        "--attack-delay",
        type=float,
        default=0,
        help="Seconds from the start of an attack run until false telemetry begins",
    )
    parser.add_argument("--interval", type=positive, default=5)
    parser.add_argument(
        "--stagger", type=float, default=1, help="Seconds between client starts"
    )
    parser.add_argument(
        "--timeout",
        type=positive,
        default=30,
        help="Request and startup timeout in seconds",
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="Concurrent warmup downloads"
    )
    parser.add_argument("--skip-warmup", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=ROOT / "results" / "multi-client"
    )
    parser.add_argument(
        "--malicious-count",
        type=int,
        default=0,
        help="Number of players replaced with modified players",
    )
    parser.add_argument(
        "--malicious-cdn", choices=("cdn-1", "cdn-2", "cdn-3"), default="cdn-1"
    )
    parser.add_argument(
        "--attack-reward",
        type=float,
        help="Reward the modified player claims for successful target-CDN video responses",
    )
    parser.add_argument(
        "--replicate",
        type=int,
        default=1,
        help="Matching control and attack runs share this replicate number",
    )
    parser.add_argument(
        "--fault-manifest",
        type=Path,
        help="NetChaos manifest applied after dash-client pods are ready",
    )
    args = parser.parse_args()
    parsed_mpd = urlsplit(args.mpd)
    if (
        parsed_mpd.scheme != "https"
        or parsed_mpd.hostname != "cdn-1.default.svc.cluster.local"
        or not re.fullmatch(r"/.+\.mpd", parsed_mpd.path)
        or parsed_mpd.query
        or parsed_mpd.fragment
    ):
        parser.error(
            "--mpd must be an HTTPS MPD URL on cdn-1.default.svc.cluster.local"
        )
    if args.clients < 1 or args.workers < 1 or not 0 <= args.stagger < float("inf"):
        parser.error(
            "clients/workers must be positive and stagger finite and nonnegative"
        )
    if not 0 <= args.attack_delay < args.seconds:
        parser.error("attack-delay must be nonnegative and shorter than seconds")
    if not 0 <= args.malicious_count < args.clients or args.replicate < 1:
        parser.error(
            "malicious-count must leave at least one honest player; replicate must be positive"
        )
    if args.malicious_count and (
        args.attack_reward is None or not 0 < args.attack_reward < 1
    ):
        parser.error(
            "attack-reward must be between 0 and 1 when modified players are requested"
        )
    if not args.malicious_count and args.attack_reward is not None:
        parser.error("attack-reward requires malicious-count")
    if not args.malicious_count and args.attack_delay:
        parser.error("attack-delay requires malicious-count")
    if args.fault_manifest and not args.fault_manifest.is_file():
        parser.error("--fault-manifest must point to a file")
    args.fault_sha256 = (
        hashlib.sha256(args.fault_manifest.read_bytes()).hexdigest()
        if args.fault_manifest
        else None
    )
    args.bucket = args.bucket.resolve()
    from playwright.sync_api import sync_playwright

    output = args.output / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    output.mkdir(parents=True)
    runs = []
    with ServiceForwards(output, warmup=not args.skip_warmup) as services:
        args.telemetry_base = services.bases["telemetry-service"]
        try:
            warmup = (
                None
                if args.skip_warmup
                else warm_caches(
                    services.bases, args.bucket, args.mpd, args.workers, args.timeout
                )
            )
        except Exception as error:
            (output / "warmup-failure.json").write_text(
                json.dumps({"error": str(error)}, indent=2) + "\n"
            )
            raise
        (output / "warmup.json").write_text(json.dumps(warmup, indent=2) + "\n")
        with sync_playwright() as playwright:
            for strategy in (
                STRATEGIES[:3] if args.strategy == "all" else [args.strategy]
            ):
                with DashClients(args.clients, output, args.fault_manifest) as pods:
                    args.player_endpoints = pods.endpoints
                    runs.append(observe(playwright, args, strategy, output, warmup))
    (output / "runs.json").write_text(json.dumps(runs, indent=2) + "\n")
    print(f"\nCompleted. Results: {output}", flush=True)


if __name__ == "__main__":
    main()
