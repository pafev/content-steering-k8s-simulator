#!/usr/bin/env bash
# Three UCB1 reward regimes; each replicate has 36 attacks and six controls.
set -euo pipefail

replicates="${1:-3}"
root="${2:-results/research-matrices}"
runner=.venv/bin/python
fault=manifests/risk-matrix-netchaos.yaml

has_run() {
  "$runner" - "$out" "$rep" "$lambda" "$1" "$2" "$3" <<'PY'
import json, pathlib, sys
root, rep, lam, kind, count, ttlb = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4], int(sys.argv[5]), int(sys.argv[6])
matches = 0
for path in pathlib.Path(root).glob('*/multi-*/summary.json'):
    try:
        summary = json.loads(path.read_text())
        cfg = summary['configuration']
    except (KeyError, ValueError):
        continue
    if (summary.get('success') and cfg['replicate'] == rep
        and cfg.get('reward_lambda', 5) == lam
        and ((kind == 'control' and cfg['malicious_count'] == 0)
             or (kind == 'attack' and cfg['malicious_count'] == count
                 and cfg.get('attack_ttlb') == ttlb))):
        matches += 1
target = count if kind == 'control' else 1
sys.exit(0 if matches >= target else 1)
PY
}

check_control() {
  "$runner" - "$out" "$rep" "$lambda" <<'PY'
import json, pathlib, sys
root, rep, lam = pathlib.Path(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
controls = []
for path in root.glob('*/multi-*/summary.json'):
    summary = json.loads(path.read_text())
    cfg = summary['configuration']
    if cfg['replicate'] == rep and cfg.get('reward_lambda', 5) == lam and cfg['malicious_count'] == 0:
        controls.append((path, summary))
path, summary = max(controls, key=lambda item: item[0].parent.parent.name)
values = summary['delivery_calibration']
rewards = {p: values[p]['mean_learning_reward'] for p in ('cdn-1', 'cdn-2', 'cdn-3')}
if not summary['success'] or not rewards['cdn-1'] > rewards['cdn-3'] > rewards['cdn-2']:
    raise SystemExit(f'Control failed or CDN reward order changed: {path} {rewards}')
print(f'Control accepted: {path} {rewards}')
PY
}

for regime in low:1 medium:5 high:15; do
  label="${regime%%:*}"
  lambda="${regime#*:}"
  out="$root/$label"
  mkdir -p "$out"
  for ((rep=1; rep<=replicates; rep++)); do
    order="$out/order-replicate-${rep}.txt"
    if [[ ! -f "$order" ]]; then
      "$runner" - "$rep" "$lambda" "$order" <<'PY'
import pathlib, random, sys
rep, lam, output = int(sys.argv[1]), int(sys.argv[2]), pathlib.Path(sys.argv[3])
cells = [(m, ttlb) for m in range(1, 7) for ttlb in (90, 200, 340, 530, 800, 1200)]
seed = 20261029 + 100 * lam + rep
random.Random(seed).shuffle(cells)
output.write_text("".join(f"{m} {ttlb}\n" for m, ttlb in cells))
output.with_name(output.name.replace("order-", "seed-")).write_text(f"{seed}\n")
PY
    fi
    completed=0
    while read -r count ttlb; do
      # A fresh invocation starts a new run_id and waits for Kind to settle.
      if ! has_run attack "$count" "$ttlb"; then
        warmup=()
        if ((completed > 0)); then warmup=(--skip-warmup); fi
        "$runner" scripts/multi_client.py --strategy ucb1 --clients 10 \
          --seconds 120 --measurement-start 40 --attack-delay 40 \
          --reward-lambda "$lambda" --replicate "$rep" \
          --malicious-count "$count" --attack-ttlb "$ttlb" \
          --fault-manifest "$fault" --output "$out" \
          "${warmup[@]}"
      fi
      ((completed+=1))
      if ((completed % 6 == 0)); then
        if ! has_run control "$((completed / 6))" 0; then
          "$runner" scripts/multi_client.py --strategy ucb1 --clients 10 \
            --seconds 120 --measurement-start 40 --reward-lambda "$lambda" \
            --replicate "$rep" --fault-manifest "$fault" \
            --skip-warmup --output "$out"
        fi
        check_control
      fi
    done < "$order"
  done
  "$runner" scripts/plot_risk_matrix.py "$out" --strategy ucb1 --require-complete
done
