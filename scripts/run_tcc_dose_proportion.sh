#!/usr/bin/env bash
# Final dose/proportion series on the 4/12/9 ms network.
set -euo pipefail
if (($# != 2)); then
  echo "Usage: bash scripts/run_tcc_dose_proportion.sh NETCHAOS.yaml OUTPUT-ROOT" >&2
  exit 2
fi
fault=$1 out=$2
[[ -f "$fault" ]] || { echo "Missing manifest: $fault" >&2; exit 2; }
runner=.venv/bin/python
mkdir -p "$out"
"$runner" - "$fault" "$out" <<'PY'
import hashlib, json, pathlib, random, sys
fault, root = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
cells = ([(3, t) for t in (90, 200, 340, 530, 800, 1200)] +
         [(m, t) for m in (1, 5) for t in (530, 800)])
plan = dict(fault_sha256=hashlib.sha256(fault.read_bytes()).hexdigest(),
            cells=cells, clients=10, seconds=120, attack_delay=40,
            measurement_start=40, reward_lambda=10, max_video_kbps=3000)
path = root / 'plan.json'
if path.exists() and json.loads(path.read_text()) != plan:
    raise SystemExit('Existing plan differs; choose another output root')
path.write_text(json.dumps(plan, indent=2) + '\n')
order = root / 'order.txt'
if not order.exists():
    attacks = cells * 2
    random.Random(20261108).shuffle(attacks)
    controls_at = {round(i * len(attacks) / 6) for i in range(6)}
    lines = []
    for i, (m, t) in enumerate(attacks):
        if i in controls_at:
            lines.append('0 0')
        lines.append(f'{m} {t}')
    order.write_text('\n'.join(lines) + '\n')
PY
if [[ ${TCC_PLAN_ONLY:-0} == 1 ]]; then cat "$out/order.txt"; exit 0; fi

has_run() {
  "$runner" - "$out" "$fault" "$1" "$2" "$3" <<'PY'
import hashlib, json, pathlib, sys
root, fault = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
m, ttlb, target = map(int, sys.argv[3:])
digest = hashlib.sha256(fault.read_bytes()).hexdigest()
found = 0
for path in root.glob('*/multi-*/summary.json'):
    try:
        summary = json.loads(path.read_text()); c = summary['configuration']
        cache = json.loads((path.parent / 'cache-validation.json').read_text())
        viewers = {v['client']: v for v in summary['viewers']}
        valid_qoe = all('qoe_full' in viewers[i] for i in range(m + 1, 11))
    except (KeyError, ValueError, OSError):
        continue
    if (summary.get('success') and valid_qoe and not cache.get('cached_non_hit_responses')
        and c.get('fault_sha256') == digest and c.get('strategy') == 'ucb1'
        and c.get('clients') == 10 and c.get('seconds') == 120
        and c.get('measurement_start') == 40 and c.get('reward_lambda') == 10
        and c.get('max_video_kbps') == 3000 and c.get('allow_viewer_failure')
        and c.get('require_fresh_cache') and c.get('malicious_count') == m
        and (m == 0 or (c.get('attack_ttlb') == ttlb and c.get('attack_delay') == 40
             and c.get('malicious_cdn') == 'cdn-1' and not c.get('attack_from_start')))):
        found += 1
sys.exit(0 if found >= target else 1)
PY
}
started=0 controls=0
declare -A attacks=()
while read -r m ttlb; do
  if ((m == 0)); then
    controls=$((controls + 1)); target=$controls
  else
    key="$m-$ttlb"; attacks[$key]=$((${attacks[$key]:-0} + 1)); target=${attacks[$key]}
  fi
  if has_run "$m" "$ttlb" "$target"; then
    echo "Reuse M=$m TTLB=$ttlb ($target)"
    continue
  fi
  warmup=(); ((started == 0)) || warmup=(--skip-warmup)
  attack=(); ((m == 0)) || attack=(--malicious-count "$m" --attack-ttlb "$ttlb" --attack-delay 40)
  "$runner" scripts/multi_client.py --strategy ucb1 --clients 10 --seconds 120 \
    --measurement-start 40 --reward-lambda 10 --max-video-kbps 3000 \
    --require-fresh-cache --allow-viewer-failure --fault-manifest "$fault" \
    --output "$out" "${attack[@]}" "${warmup[@]}"
  started=$((started + 1))
  has_run "$m" "$ttlb" "$target" || { echo "Invalid run M=$m TTLB=$ttlb" >&2; exit 1; }
done < "$out/order.txt"
"$runner" scripts/plot_tcc_series.py "$out"
