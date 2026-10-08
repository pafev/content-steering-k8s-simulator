# False telemetry risk matrix

This experiment uses the fixed count of 10 real dash.js players per run.
Modified players vary throughout the experiment and replace honest players.
A modified player downloads genuine segments and changes only its CMCD `ttlb` for
successful CDN-1 video responses. For a requested claimed reward `r`, it
reports `ttlb = round(d × (1/r − 1) / 5)`, where `d` is that segment's reported duration
in milliseconds. The CSS uses the reward `d/(d+5×ttlb)`.

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
running the pilot attack cell M=1, r=0.5:

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 10 \
  --seconds 120 --measurement-start 40 --replicate 1 \
  --fault-manifest manifests/risk-matrix-netchaos.yaml \
  --output results/risk-matrix
.venv/bin/python scripts/plot_risk_matrix.py results/risk-matrix --strategy ucb1
```

Check `results/risk-matrix-ttlb5-720p/plots/ucb1/calibration.json` before
continuing. Repeat controls before treating a small reward gap as stable.

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 10 \
  --seconds 120 --measurement-start 40 --attack-delay 40 --replicate 1 \
  --malicious-count 1 --attack-reward 0.5 \
  --fault-manifest manifests/risk-matrix-netchaos.yaml \
  --skip-warmup --output results/risk-matrix
.venv/bin/python scripts/plot_risk_matrix.py results/risk-matrix --strategy ucb1
```

The plotter writes `D_steer.png`, `D_viewer.png`, `metrics.json`, and
`calibration.json` under `results/risk-matrix/plots/ucb1/`. Gray
cells have not run. Check each run's `summary.json` for `success`, `problems`,
cache hits, and `accepted_falsified` before interpreting a pair. The attack
starts after 40 seconds of clean learning. Both runs measure only seconds
40–120 through `--measurement-start 40`; `--attack-delay 40` separately
enables false telemetry. Set `--measurement-start 0` on both runs to measure
the full duration while still delaying the attack.
`--skip-warmup` disables cache validation; cache
status remains in `events.jsonl` for inspection.

## Metrics

For each honest player, `P` is the fraction of observed CSS steering responses
whose first priority is CDN-2 or CDN-3. The run's `P` is the mean of those
player fractions. Use steering responses from seconds 40–120 in both runs.

`D_steer = P_attack − P_control` for the **same honest slots** M+1–10.
Positive values mean the modified reports shifted honest players toward the
two delayed CDNs. This measures CSS decisions, not necessarily the segment
path ultimately used after fallback.

For each honest player, `B = rebuffer_seconds / (played_seconds +
rebuffer_seconds)` during seconds 40–120. `D_viewer = mean(B_attack)
− mean(B_control)` over the same slots. Positive values mean more buffering.
Startup time is recorded in `summary.json` but is outside this metric. A
zero `D_viewer` is possible even when steering changes because the player may
have enough buffer. Neither chart alone defines a healthy/impaired boundary;
choose a practical threshold and uncertainty rule before drawing one.

`metrics.json` also records `honest_reward_gap = mean_reward(CDN-1) −
max(mean_reward(CDN-2), mean_reward(CDN-3))` from the clean control,
`claimed_reward_gap = claimed_reward − best_alternative_control_reward`, and
`falsified_feedback_share = accepted_falsified_CDN1_reports /
all_accepted_CDN1_learning_reports` from the attack. The latter is the actual
exposure of the CDN-1 learner; a modified player steered away from CDN-1 may
send few falsified reports. `control_order_valid` records whether the intended
reward order was observed. These values make the risk map interpretable for
its measured baseline, without treating one absolute reward boundary as
universal.

## Complete the 6 × 6 matrix

For each strategy (`ucb1`, `epsilon_greedy`, `linucb`), run a clean 10-player
control for each replicate, then attack runs for M=1,2,3,4,5,6 and
r=0.9,0.8,0.7,0.6,0.5,0.4. There are 36 attack cells per strategy, plus the
matched controls. Skip the pilot cell when using the same replicate and output
directory. Example shell loop for the remaining UCB1 cells:

```sh
for count in 1 2 3 4 5 6; do
  for reward in 0.9 0.8 0.7 0.6 0.5 0.4; do
    if [ "$count" = 1 ] && [ "$reward" = 0.5 ]; then continue; fi
    .venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 10 \
      --seconds 120 --measurement-start 40 --attack-delay 40 \
      --replicate 1 --malicious-count "$count" \
      --attack-reward "$reward" --skip-warmup \
      --fault-manifest manifests/risk-matrix-netchaos.yaml \
      --output results/risk-matrix
  done
done
.venv/bin/python scripts/plot_risk_matrix.py results/risk-matrix --strategy ucb1
```

For independent replicates, use another `--replicate` number and include one
new clean control with that number. Use one output root for one fault setup;
the plotter pairs by strategy and replicate and rejects duplicate controls,
a changed fault manifest, or different measurement cutoffs. Repeat cells with
multiple replicates before estimating a risk boundary.

The runner waits for NetChaos finalizer cleanup before removing dash-client
pods. Use the updated NetChaos controller and agent builds; the controller
must add its finalizer and the agent must delete the leaf qdisc before the
class. Check that no
experiment resources remain:

```sh
kubectl --context kind-kind get networkchaos
kubectl --context kind-kind get pods -l app=dash-client
```
