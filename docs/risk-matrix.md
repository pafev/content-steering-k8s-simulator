# False telemetry risk matrix

This experiment uses the fixed count of 10 real dash.js players per run.
The player is capped at the MPD's 576p, 1.5 Mb/s representation to keep ten
simultaneous browser decoders within the Kind cluster's CPU capacity. Keep this
workload fixed across controls and attack cells. The runner waits for old
dash-client pods and NetChaos objects to disappear and for both Kind workers
to settle before starting a new run; inspect each `idle-check.json`.
Modified players vary throughout the experiment and replace honest players.
A modified player downloads genuine segments and changes only its CMCD `ttlb` for
successful CDN-1 video responses. `--attack-ttlb` specifies the fixed TTLB
declared in milliseconds. The CSS uses `d/(d+lambda×ttlb)`;
`--reward-lambda` defaults to 5.

## Network delays and calibration

The [fault manifest](../manifests/risk-matrix-netchaos.yaml) applies initial
4, 12, and 9 ms delays to packets leaving CDN-1, CDN-2, and CDN-3 for the
player PodIPs. This shapes the media response direction.
The ordering is based on one hour of IPv4 ICMP measurements from
[RIPE Atlas probe 24628](https://atlas.ripe.net/api/v2/probes/24628/).

Run a clean control and inspect `calibration.json`: it reports accepted video
samples, median/p90 browser `ttlb`, and mean learning reward per CDN. Check the
observed CDN reward order before interpreting attacks; the configured delays
alone do not guarantee it.

## Run a matched pair

Follow [simulations.md](simulations.md) to start Kind, the simulator, NetChaos,
and optionally port-forward the gateway to inspect the system. Install `scripts/requirements.txt`
and `scripts/plot-requirements.txt`. The runner creates one dash-client pod per
player, applies faults after the pods are ready, and removes them at the end
of each run. Check `kubectl --context kind-kind get networkchaos` while a run
is active. Run one experiment at a time: the fault manifest selects all
`dash-client` pods as targets and names `cdn-1-edge-1`, `cdn-2-edge-1`, and
`cdn-3-edge-1` as sources. Update the manifest if the CDN pods are renamed.
The player pods also have a `steering-client-index` label (1–10) for later client-specific faults.

Run one clean control and one attack with the same strategy, replicate, video,
10 players and fault setup. The first run warms
all CDN caches; the second reuses them. After the clean control, generate and
inspect calibration before
running the pilot attack cell M=1, declared TTLB=800 ms:

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 10 \
  --seconds 120 --measurement-start 40 --replicate 1 \
  --fault-manifest manifests/risk-matrix-netchaos.yaml \
  --output results/risk-matrix
.venv/bin/python scripts/plot_risk_matrix.py results/risk-matrix --strategy ucb1
```

Check `results/risk-matrix/plots/ucb1/calibration.json` before
continuing. Repeat controls before treating a small reward gap as stable.

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 10 \
  --seconds 120 --measurement-start 40 --attack-delay 40 --replicate 1 \
  --malicious-count 1 --attack-ttlb 800 \
  --fault-manifest manifests/risk-matrix-netchaos.yaml \
  --skip-warmup --output results/risk-matrix
.venv/bin/python scripts/plot_risk_matrix.py results/risk-matrix --strategy ucb1
```

The plotter writes `D_steer.png`, `D_viewer.png`, `Delta_c.png`,
`metrics.json`, `calibration.json`, `controls.csv`, `controls-summary.csv`
and `cells.csv` under
`results/risk-matrix/plots/ucb1/`. Runs made before interval byte snapshots
were implemented cannot be used for the cost plot. Gray
cells have not run. Check each run's `summary.json` for `success`, `problems`,
cache hits, and `accepted_falsified` before interpreting a pair. The attack
starts after 40 seconds of clean learning. Both runs measure only seconds
40–120 through `--measurement-start 40`; `--attack-delay 40` separately
enables false telemetry. Set `--measurement-start 0` on both runs to measure
the full duration while still delaying the attack.
`--skip-warmup` omite o aquecimento. O runner exige que a mídia venha do
cache da CDN. O NGINX pode retornar `STALE`, `UPDATING` ou `REVALIDATED`
enquanto entrega um corpo armazenado; esses estados ficam separados de misses
reais em `cache-validation.json`. Veja a
[documentação do NGINX](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_cache_use_stale).
Nas matrizes, `--require-fresh-cache` exige `HIT` em todas as respostas de
mídia. A CDN ignora o `Cache-Control: max-age=3600` da origem para que seu
`proxy_cache_valid 24h` governe os objetos estáticos; a primeira célula de cada
invocação faz aquecimento completo. Uma célula falha por cache é repetida na
retomada; o plotter ignora tentativas falhas e respostas não `HIT`.

## Metrics

For each honest player, `P` is the fraction of observed CSS steering responses
whose first priority is CDN-2 or CDN-3. The run's `P` is the mean of those
player fractions. Use steering responses from seconds 40–120 in both runs.

`D_steer = P_attack − mean(P_control,c)` across all six controls of the
replicate for the **same honest slots** M+1–10.
Positive values mean the modified reports shifted honest players toward the
two delayed CDNs. This measures CSS decisions, not necessarily the segment
path ultimately used after fallback.

For each honest player, `B = rebuffer_seconds / (played_seconds +
rebuffer_seconds)` during seconds 40–120. `D_viewer = B_attack −
mean(B_control,c)` over the same slots and six controls. Positive values mean
more buffering.
Startup time is recorded in `summary.json` but is outside this metric. A
zero `D_viewer` is possible even when steering changes because the player may
have enough buffer. Neither chart alone defines a healthy/impaired boundary;
choose a practical threshold and uncertainty rule before drawing one.

`metrics.json` also records `honest_reward_gap = mean_reward(CDN-1) −
max(mean_reward(CDN-2), mean_reward(CDN-3))` from the mean of six controls,
`claimed_reward_gap = mean_accepted_claimed_reward − best_alternative_control_reward`, and
`falsified_feedback_share = accepted_falsified_CDN1_reports /
all_accepted_CDN1_learning_reports` from the attack. The latter is the actual
exposure of the CDN-1 learner; a modified player steered away from CDN-1 may
send few falsified reports. `control_order_valid` records whether the intended
reward order was observed. These values make the risk map interpretable for
its measured baseline, without treating one absolute reward boundary as
universal.

## Complete the 6 × 6 matrices

The revised [research protocol](research-protocol.md) uses UCB1 and three reward
sensitivities (lambda 1, 5, 15). It runs two attacks per cell in separately
randomized passes, with a clean control after each block of six attacks in the
first pass. From the repository root, run:

```sh
bash scripts/run_research_matrices.sh low results/research-matrices
bash scripts/run_research_matrices.sh medium results/research-matrices
bash scripts/run_research_matrices.sh high results/research-matrices
```

The first argument selects the reward sensitivity. There is one complete
matrix per sensitivity: 72 attack runs and six controls (78 total). The
optional second argument sets the output root. The script saves both randomized
cell orders, waits for the runner's idle barrier before every execution, and
resumes successful cells after interruption. Re-running `low` after its first
36 attacks adds only the second attack for each cell; its six controls are reused.
Failed runs remain on disk for audit and are retried.
Each completed invocation writes `D_steer.png`, `D_viewer.png`,
`Delta_c.png`, `metrics.json`, `calibration.json`, `controls.csv`,
`controls-summary.csv`, `attack-runs.csv` and `cells.csv` under `plots/ucb1/`.
`cells.csv` and the figures contain means of the two attacks per cell;
`attack-runs.csv` and `metrics.json` retain both individual effects. The plotter
requires six controls and two valid attacks in each of the 36 cells.
The x-axis uses the same declared TTLB values (90, 200, 340, 530, 800,
1200 ms) for all three lambda regimes. Per-cell mean accepted rewards and
costs live in `cells.csv`; individual values are in `attack-runs.csv`. Figures
show one mean effect number per cell.
The pilot runs live in a separate directory and are never pooled into a matrix.

The runner waits for NetChaos finalizer cleanup before removing dash-client
pods. Use the updated NetChaos controller and agent builds; the controller
must add its finalizer and the agent must delete the leaf qdisc before the
class. Check that no
experiment resources remain:

```sh
kubectl --context kind-kind get networkchaos
kubectl --context kind-kind get pods -l app=dash-client
```
