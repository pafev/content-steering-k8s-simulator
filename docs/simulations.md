# Run simulations

Run commands from the repository root. The examples use the `kind-kind` context
and the packaged video in `bucket/`. Install
Docker, Kind, kubectl, mkcert, and Python first.

## Start the simulator

```sh
./setup.sh
```

The gateway is optional for simulations. To inspect health and run state, use
`kubectl --context kind-kind port-forward pod/gateway 5000:80` and open
`http://localhost:5000`.

Install the runner and plotting dependencies:

```sh
python3 -m venv .venv
.venv/bin/pip install -r scripts/requirements.txt -r scripts/plot-requirements.txt
```

`./setup.sh` builds the dash-client image, restarts the
simulator pods and clears their ephemeral CDN caches. Ensure the NetChaos
controller and agents are installed in the same Kind cluster before applying a
latency fault; see the separate NetChaos Simulator project.
Check that its CRD, controller, and node agents are present:

```sh
kubectl --context kind-kind get crd networkchaos.net-chaos-simulator.pafev.dev
kubectl --context kind-kind get pods -n net-chaos-simulator-system
```

## Clean baseline

The runner launches one dash-client pod per client. Each pod fetches its MPD
and segments from CDN services, steering from the CSS, and sends CMCD directly
to telemetry. The runner warms CDN caches through temporary CDN port forwards.

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 5 \
  --seconds 60 --output results/clean
```

The runner starts independent dash.js sessions in one fresh run, warms
all CDN caches with full GETs, verifies HITs, and saves the results. Use
`--strategy all` for separate UCB1, epsilon-greedy, and LinUCB runs. Use a
new invocation for each independent trial; do not reuse a run ID.

## Modified player reporting false latency

Run another clean baseline without an active NetChaos fault. Then start five
honest players and one modified dash.js player (six total):

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 6 \
  --seconds 60 --malicious-count 1 --malicious-cdn cdn-1 \
  --attack-reward 0.5 --output results/modified-player
```

The modified player follows CSS decisions and downloads real media. For
successful CDN-1 video responses, it changes `ttlb` so that the reported
delivery reward `d/(d+5×ttlb)` is about 0.5.

The run's `modified-players.json` records original and claimed timing,
matching responses, and telemetry ingestion results. The role label is used
only by the runner, not by CSS policy.

For the 10-player attack experiment and matched controls, see [risk-matrix.md](risk-matrix.md).

## Read and plot results

Each invocation writes `results/<output>/<timestamp>/<run_id>/`. The useful
files are `summary.json` (configuration, final model, validity checks, attack
counts and the path to its detailed artifact),
`events.jsonl` (steering responses, media responses, feedback),
`samples.jsonl` (playback and model snapshots), and
`cache-validation.json`.
Attack runs also write `modified-players.json`.
The timestamp directory contains `warmup.json` and `runs.json`.

```sh
.venv/bin/python scripts/plot_run.py results/clean/<timestamp>
.venv/bin/python scripts/plot_run.py results/modified-player/<timestamp>
```

Open each run's `plots/index.html` or `plots/overview.png`. The six panels
show CDN mean reward and learning counts, CSS first priorities, actual media
pathways, playback position, and cache status. For the attack, compare the
honest clients' first priorities and CDN-1 mean reward before and after the
modified player reports. Mean reward is a reported delivery outcome, not session
QoE; playback position is sampled, so a flat interval is not by itself proof of
a stall. Cache state and network scheduling can differ between trials. Repeat
trials before drawing general performance conclusions.
