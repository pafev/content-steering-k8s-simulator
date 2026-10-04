# Run simulations

Run commands from the repository root. The examples use the `kind-kind` context,
the packaged video in `bucket/`, and the local gateway on port 5000. Install
Docker, Kind, kubectl, mkcert, Python, and a Chromium-compatible browser first.

## Start the simulator

```sh
./setup.sh
kubectl --context kind-kind port-forward pod/gateway 5000:80
```

Keep the port forward running. In another terminal, install the runner and
plotting dependencies:

```sh
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt -r scripts/plot-requirements.txt
.venv/bin/playwright install chromium
```

If Chromium is already installed, pass `--browser /path/to/browser` to the
runner instead of installing Playwright Chromium. `./setup.sh` restarts the
simulator pods and clears their ephemeral CDN caches. Ensure the NetChaos
controller and agents are installed in the same Kind cluster before applying a
latency fault; see the separate NetChaos Simulator project.
Check that its CRD, controller, and node agents are present:

```sh
kubectl --context kind-kind get crd networkchaos.net-chaos-simulator.pafev.dev
kubectl --context kind-kind get pods -n net-chaos-simulator-system
```

## Clean baseline

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 5 \
  --seconds 60 --output results/clean
```

The runner starts five independent dash.js sessions in one fresh run, warms
all three CDN caches with full GETs, verifies HITs, and saves the results. Use
`--strategy all` for separate UCB1, epsilon-greedy, and LinUCB runs. Use a
new invocation for each independent trial; do not reuse a run ID.

## CDN-1 latency with NetChaos

Run a clean baseline first. With the NetChaos controller and agents ready,
apply a fault to gateway egress toward the CDN-1 service:

```sh
kubectl --context kind-kind apply -f - <<'YAML'
apiVersion: net-chaos-simulator.pafev.dev/v1
kind: NetworkChaos
metadata:
  name: content-steering-cdn1-delay
  namespace: default
spec:
  sourceSelector:
    name: gateway
  targetServiceSelector:
    name: cdn-1
  delay: 200ms
YAML
kubectl --context kind-kind get networkchaos content-steering-cdn1-delay
```

Then run the same workload on already warmed caches:

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 5 \
  --seconds 60 --skip-warmup --output results/cdn1-latency
kubectl --context kind-kind delete networkchaos content-steering-cdn1-delay
```

This fault affects gateway-to-CDN-1 traffic, including proxied player media
requests. It does not model every possible client-to-CDN route. Warm caches
help expose delivery-path latency instead of only CDN-to-origin fill latency.
Verify that the fault resource and traffic-control rule are gone before a clean
run; an earlier local trial encountered a NetChaos finalizer cleanup error.
Save the applied fault manifest and its observed status alongside the results.

## Modified player reporting false latency

Run another clean baseline without an active NetChaos fault. Then start five
honest players and one modified dash.js player:

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 5 \
  --seconds 60 --malicious-cdn cdn-1 --malicious-ttlb-ms 20000 \
  --malicious-start-after 15 --output results/modified-player
```

The sixth player joins about 15 seconds after the first honest player. It
follows CSS decisions and downloads real media. For successful CDN-1 video
segment responses, it replaces the measured `ttlb` in its outgoing CMCD
report with 20,000 ms. It does not fabricate downloads. The run's
`modified-player.json` records the original and claimed timing, successful
matching responses, and telemetry ingestion results. The modified player's
label is used only by the runner, not by CSS policy.

## Read and plot results

Each invocation writes `results/<output>/<timestamp>/<run_id>/`. The useful
files are `summary.json` (configuration, final model, validity checks, attack
counts and the path to its detailed artifact),
`events.jsonl` (steering responses, media responses, feedback),
`samples.jsonl` (playback and model snapshots), and
`cache-validation.json`. Attack runs also write `modified-player.json`.
The timestamp directory contains `warmup.json` and `runs.json`.

```sh
.venv/bin/python scripts/plot_run.py results/clean/<timestamp>
.venv/bin/python scripts/plot_run.py results/cdn1-latency/<timestamp>
.venv/bin/python scripts/plot_run.py results/modified-player/<timestamp>
```

Open each run's `plots/index.html` or `plots/overview.png`. The six panels
show CDN mean reward and learning counts, CSS first priorities, actual media
pathways, playback position, and cache status. For the attack, compare the
honest clients' first priorities and CDN-1 mean reward before and after the
modified player joins. Mean reward is a reported delivery outcome, not session
QoE; playback position is sampled, so a flat interval is not by itself proof of
a stall. Cache state and network scheduling can differ between trials. Repeat
trials before drawing general performance conclusions.
