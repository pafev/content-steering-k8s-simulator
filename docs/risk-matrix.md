# False telemetry risk matrix

This experiment uses the fixed count of 10 real dash.js players per run.
Modified players vary throughout the experiment and replace honest players.
A modified player downloads genuine segments and changes only its CMCD `ttlb` for
successful CDN-1 video responses. For a requested claimed reward `r`, it
reports `ttlb = round(d × (1/r − 1))`, where `d` is that segment's reported duration
in milliseconds. The CSS still uses its existing reward `d/(d+ttlb)`.

## Network delays and calibration

The [fault manifest](../manifests/risk-matrix-netchaos.yaml) applies initial
4, 12, and 9 ms delays to packets leaving CDN-1, CDN-2, and CDN-3 for the
player PodIPs. This shapes the media response direction.
The ordering is based on one hour of IPv4 ICMP measurements from
[RIPE Atlas probe 24628](https://atlas.ripe.net/api/v2/probes/24628/) on a
São Paulo Vivo connection (2026-10-06 02:00–03:00 UTC). Median averages over
15 ping rounds were 3.841 ms to
[Fastly](https://atlas.ripe.net/api/v2/measurements/177401244/results/?probe_ids=24628&start=1791252000&stop=1791255600),
4.550 ms to
[Cloudflare](https://atlas.ripe.net/api/v2/measurements/176906978/results/?probe_ids=24628&start=1791252000&stop=1791255600),
and 5.161 ms to
[Amazon](https://atlas.ripe.net/api/v2/measurements/177401165/results/?probe_ids=24628&start=1791252000&stop=1791255600).
The simulator CDNs are anonymous; these measurements justify only the rank,
not an identity or a measured segment download time for any simulated CDN.

Browser `ttlb` includes the full HTTPS media transfer, so it can be much
larger than one configured one-way delay. The
[netem manual](https://man7.org/linux/man-pages/man8/tc-netem.8.html) also
warns that queue placement matters for realistic TCP performance. A 10-player
control with the former 50/112/84 ms
settings measured median video `ttlb` of 416/915/691 ms. Two 10-player
controls with 4/12/9 ms on player egress measured 55/113/97 ms and
51.5/115/90.5 ms. One of those two controls had a long CDN-3 download tail
and did not preserve the CDN-3 > CDN-2 mean-reward order. These are historical
measurements for the earlier player-egress profile. The new
CDN-egress profile must be recalibrated with a clean control before any attack
pair is interpreted. Check its browser `ttlb`, tail, and learned reward order.
In one 10-player, 40+80-second pilot with the 1080p default, CDN-egress
4/12/9 ms produced median browser video `ttlb` of 47/108.5/83 ms for
CDN-1/2/3. Learned mean rewards were 0.9883/0.9745/0.9804, preserving
CDN-1 > CDN-3 > CDN-2. Treat this as a local calibration, not a CDN-wide
latency estimate; repeat controls before the full matrix.
The earlier M=1, r=0.5 pilot used an 80-second observation window after
40 seconds of training; its D metrics are not comparable with new 120-second
full-run metrics.

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
The player pods
also have a `steering-client-index` label (1–10) for later client-specific faults.

Run one clean control and one attack with the same strategy, replicate, video,
10 players and fault setup. The first run warms
all CDN caches; the second reuses them. After the clean control, generate and
inspect calibration before
running the pilot attack cell M=1, r=0.5:

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 10 \
  --seconds 120 --replicate 1 \
  --fault-manifest manifests/risk-matrix-netchaos.yaml \
  --output results/risk-matrix-manual-delays
.venv/bin/python scripts/plot_risk_matrix.py results/risk-matrix-manual-delays --strategy ucb1
```

Check `results/risk-matrix-manual-delays/plots/ucb1/calibration.json` before
continuing. Repeat controls before treating a small reward gap as stable.

```sh
.venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 10 \
  --seconds 120 --attack-delay 40 --replicate 1 \
  --malicious-count 1 --attack-reward 0.5 \
  --fault-manifest manifests/risk-matrix-netchaos.yaml \
  --skip-warmup --output results/risk-matrix-manual-delays
.venv/bin/python scripts/plot_risk_matrix.py results/risk-matrix-manual-delays --strategy ucb1
```

The plotter writes `D_steer.png`, `D_viewer.png`, `metrics.json`, and
`calibration.json` under `results/risk-matrix-manual-delays/plots/ucb1/`. Gray
cells have not run. Check each run's `summary.json` for `success`, `problems`,
cache hits, and `accepted_falsified` before interpreting a pair. The attack
starts after 40 seconds of clean learning. Both metrics use the full
120 seconds in the attack and control, so the clean first 40 seconds dilute
the measured effect. `--skip-warmup` disables cache validation; cache
status remains in `events.jsonl` for inspection.

## Metrics

For each honest player, `P` is the fraction of observed CSS steering responses
whose first priority is CDN-2 or CDN-3. The run's `P` is the mean of those
player fractions. Use steering responses from the full run.

`D_steer = P_attack − P_control` for the **same honest slots** M+1–10.
Positive values mean the modified reports shifted honest players toward the
two delayed CDNs. This measures CSS decisions, not necessarily the segment
path ultimately used after fallback.

For each honest player, `B = rebuffer_seconds / (played_seconds +
rebuffer_seconds)` during the observation period. `D_viewer = mean(B_attack)
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
      --seconds 120 --attack-delay 40 --replicate 1 --malicious-count "$count" \
      --attack-reward "$reward" --skip-warmup \
      --fault-manifest manifests/risk-matrix-netchaos.yaml \
      --output results/risk-matrix-manual-delays
  done
done
.venv/bin/python scripts/plot_risk_matrix.py results/risk-matrix-manual-delays --strategy ucb1
```

For independent replicates, use another `--replicate` number and include one
new clean control with that number. Use one output root for one fault setup;
the plotter pairs by strategy and replicate and rejects duplicate controls or
a changed fault manifest. Repeat cells with
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
