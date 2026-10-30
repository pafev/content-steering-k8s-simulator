#!/usr/bin/env bash
# One UCB1 risk matrix per reward regime and invocation.
set -euo pipefail

if (( $# < 1 || $# > 2 )); then
  echo "Usage: bash scripts/run_research_matrices.sh low|medium|high [output-root]" >&2
  exit 2
fi
label="$1"
case "$label" in
  low) lambda=1 ;;
  medium) lambda=5 ;;
  high) lambda=15 ;;
  *) echo "Unknown regime: $label (choose low, medium or high)" >&2; exit 2 ;;
esac
rep=1  # Internal identifier retained for matching the existing partial matrix.
root="${2:-results/research-matrices}"
out="$root/$label"
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
        cache = json.loads((path.parent / 'cache-validation.json').read_text())
    except (KeyError, ValueError, OSError):
        continue
    if (summary.get('success') and not cache.get('cached_non_hit_responses')
        and cfg['replicate'] == rep
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

mkdir -p "$out"
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
started=0
while read -r count ttlb; do
  # A fresh invocation starts a new run_id and waits for Kind to settle.
  if ! has_run attack "$count" "$ttlb"; then
    warmup=()
    if ((started > 0)); then warmup=(--skip-warmup); fi
    "$runner" scripts/multi_client.py --strategy ucb1 --clients 10 \
      --seconds 120 --measurement-start 40 --attack-delay 40 \
      --require-fresh-cache \
      --reward-lambda "$lambda" --replicate "$rep" \
      --malicious-count "$count" --attack-ttlb "$ttlb" \
      --fault-manifest "$fault" --output "$out" \
      "${warmup[@]}"
    ((started+=1))
  fi
  ((completed+=1))
  if ((completed % 6 == 0)); then
    if ! has_run control "$((completed / 6))" 0; then
      warmup=()
      if ((started > 0)); then warmup=(--skip-warmup); fi
      "$runner" scripts/multi_client.py --strategy ucb1 --clients 10 \
        --seconds 120 --measurement-start 40 --reward-lambda "$lambda" \
        --require-fresh-cache \
        --replicate "$rep" --fault-manifest "$fault" \
        --output "$out" "${warmup[@]}"
      ((started+=1))
    fi
    check_control
  fi
done < "$order"
"$runner" scripts/plot_risk_matrix.py "$out" --strategy ucb1 \
  --replicate "$rep" --output "$out/plots/ucb1" --require-complete
