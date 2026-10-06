# DASH Content Steering simulator

Multi-client DASH Content Steering simulator on Kubernetes/Kind, with real playback using dash.js 5.2.1, three Nginx CDN caches, a Caddy origin, CMCD telemetry, Redis, and a Content Steering Server (CSS). Based on [alissonpef/Content-Steering](https://github.com/alissonpef/Content-Steering).

The goal is to experiment with Content Steering policies over aggregated metrics from multiple clients. The project implements DASH; HLS playback is not included.

## Running

Requirements: Docker, Kind, kubectl, mkcert, and media in `bucket/`. Only the origin mounts this directory, in read-only mode. See [bucket/README.md](bucket/README.md).

```sh
./setup.sh
kubectl --context kind-kind port-forward pod/gateway 5000:80
```

Open http://localhost:5000 to inspect gateway, CSS, and telemetry health. Read a run at `/state/<run_id>`. To create dash-client pods and run a simulation, use [scripts/multi_client.py](scripts/multi_client.py).

The setup rebuilds and loads local images, restarts application pods, and clears ephemeral CDN caches. The Redis state remains until its pod is replaced. An existing Kind cluster without `/mnt/bucket` needs to be recreated.

## Architecture

```text
user -> gateway (read-only inspection)
dash-client pods -> CDN 1/2/3 (MPD and media) -> origin-server
                -> steering-server -> Redis
                -> telemetry-service -> Redis
CDN 1/2/3 -----------------> telemetry-service (UDP logs)
```

- `gateway`: user-facing inspection endpoint; it is outside the playback path.
- `dash-client` pods: one Chromium and dash.js player per simulated client.
- `steering-server`: applies the run's policy and returns `PATHWAY-PRIORITY`.
- `cdn-1..3`: independent pull-through caches; misses query the origin.
- `origin-server`: the only component that mounts the bucket.
- `telemetry-service`: correlates sessions, CMCD, and CDN logs.
- `Redis`: sessions, configuration, decisions, statistics, and audit per run.

NetChaos is responsible for latency, bandwidth, and congestion. The CSS consumes only the decision state in Redis and does not access the Kubernetes API.

### Flow

1. The client registers the `sid -> run_id` correlation.
2. dash.js queries the CSS and receives `VERSION`, `TTL`, `RELOAD-URI`, and `PATHWAY-PRIORITY`.
3. dash.js selects a `BaseURL@serviceLocation` and sends CMCD with the requests.
4. The CDN logs status, bytes, duration, and cache via UDP.
5. CMCD Response Mode (`e=rr`) and player events arrive via HTTP.
6. Each correlated CMCD response for a video segment attempt updates the requested CDN arm; new queries to the CSS use the shared model.

Clients in the same run share statistics, but receive decisions per request. Concurrent updates use Redis transactions, so CSS workers do not maintain diverging models.

The packaged MPD names the three CDN services and CSS directly. A dash-client pod loads its player page from its own loopback server, then dash.js selects among the CDN pathways. The gateway does not rewrite the MPD.

## Policies and Learning

| Strategy | Implementation |
| --- | --- |
| `fixed` | Fixed priority `cdn-1`, `cdn-2`, `cdn-3` |
| `random` | Uniform permutation per query |
| `epsilon_greedy` | Sample means, epsilon 0.2 and exploration of new arms |
| `ucb1` | `mean + sqrt(2 log(total) / observations)` |
| `linucb` | Disjoint ridge models, initial identity and alpha 1 |

The first session defines the run's strategy and seed; conflicting records are rejected. The seed controls the RNG for decisions, but report ordering and network scheduling must also be recorded for complete reproduction.

Each valid video segment attempt with `e=rr`, session, and decision trains the requested URL's CDN, once per CMCD report. A response of `rc=0` or HTTP error 4xx/5xx receives zero reward. For a 2xx response, the reward is `d/(d+ttlb)`, using media duration `d` and download time `ttlb` in milliseconds. A successful fallback CDN receives its own reward; no previous stall is attributed to it. The result is a limited indicator of media delivery capacity, not the session's observed QoE. This is a simulator choice, not a formula prescribed by CMCD or Content Steering.

LinUCB uses the context `[1, buffer_ms / (buffer_ms + 10000)]`, captured prior to the decision. `RELOAD-URI` carries the private `decision_id`, which the client copies to `cs_decision` in the media URL. These parameters serve simulator correlation and are not CMCD fields.

Decisions remain available during the session (one hour by default). A delayed report still trains if the session and decision exist. Absence of a report does not imply failure nor does it yield zero reward. An unavailable Redis makes the CSS return fixed priority to preserve playback.

## CMCD and RUM

CMCD v2 Response/Event Mode provides the player's RUM perspective: response times, buffer, state, startup, and errors. CDN logs complement this view with status, bytes, duration, and cache observed on the server.

Values declared by the client remain untrusted when copied to CDN logs. `mtp` is a historical client estimate, not measured throughput on the current request. Invalid pairs (`ttfb > ttlb`) remain in the audit, but do not enter aggregates. Learning uses `rc`, `d`, and `ttlb` from the CMCD report; `bl` provides context for LinUCB. CDN logs do not generate a second model update.

## Interfaces and State

- CSS service: `GET /manifest.json` and `GET /healthz` on port 30500.
- Telemetry service: `POST /v1/sessions`, `POST /v1/cmcd/events` (`application/cmcd`, 1–100 records), `GET /v1/state/<run_id>`, and `GET /healthz` on port 30600.
- Gateway inspection: `GET /`, `/healthz`, `/css/healthz`, `/telemetry/healthz`, and `/state/<run_id>` on port 80.

Sessions expire after one hour without renewal; the UI renews every 30 seconds. Run keys expire after 24 hours of inactivity. The Redis streams `run:<id>:decisions` and `run:<id>:observations` hold approximately the last 5,000 records. They are limited diagnostics, not durable storage. UDP logs are best effort.

## Run five clients and warm up caches

[scripts/multi_client.py](scripts/multi_client.py) warms the CDNs through temporary direct port forwards and records decisions, cache, playback, and shared state. It runs one dash-client pod per client. See [how to run simulations](docs/simulations.md) and the [risk matrix](docs/risk-matrix.md). [Design and learning rule](docs/design.md) summarizes the results.

## Tests

The dash.js bundle is a versioned dependency in `client/assets/vendor/dashjs/`. See [the dependency instructions](client/assets/vendor/dashjs/README.md) for upgrade and checksum. Simulator-specific behavior resides in `main.js` and, for the optional false telemetry test, `cmcd-lie.js`.

```sh
python3 -m venv .venv
.venv/bin/pip install -r steering-server/requirements.txt pytest
.venv/bin/python -m pytest tests telemetry-service/tests
node --check client/assets/js/main.js
```

Tests use temporary Redis instances. For browser and network validation, run a short [multi-client simulation](docs/simulations.md) in Kind.

## Simulator Invariants

- State and configuration are isolated by `run_id`; a client does not reset the run.
- The chosen strategy is not overridden by another telemetry heuristic.
- Each correlated segment response updates the model at most once.
- Context is captured at decision time and preserved until feedback.
- Evaluator-defined identities or labels do not enter the policies.
- Cache, telemetry, and decision remain separate components.

## Technical Foundations

- [ETSI TS 103 998](https://www.etsi.org/deliver/etsi_ts/103900_103999/103998/01.01.01_60/ts_103998v010101p.pdf): DASH signaling and CSS interaction; does not prescribe a decision algorithm.
- [Apple WWDC22](https://developer.apple.com/videos/play/wwdc2022/10144/): regional policies, buckets, and `RELOAD-URI`; does not document Apple TV+ internal architecture.
- [dash.js CMCD](https://dashif.org/dash.js/pages/usage/cmcd.html): Request, Response, and Event Mode.
- [Akamai — player analytics with CMCD](https://www.akamai.com/blog/cloud/get-your-player-analytics-with-cmcd): complementary player and CDN observations.
- [Auer et al., 2002](https://doi.org/10.1023/A:1013689704352): UCB1.
- [Li et al., WWW 2010](https://www.schapire.net/papers/www10.pdf): Disjoint LinUCB.
