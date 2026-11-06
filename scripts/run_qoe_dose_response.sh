#!/usr/bin/env bash
# Six shared controls; two delayed M=3 attacks for each declared TTLB.
set -euo pipefail

if (($# < 2)); then
  echo "Usage: bash scripts/run_qoe_dose_response.sh FAULT-MANIFEST OUTPUT-ROOT [TTLB-MS ...]" >&2
  exit 2
fi
fault="$1"
out="$2"
shift 2
doses=("$@")
if ((${#doses[@]} == 0)); then
  doses=(1200 2500 3500 5000 8000 12000)
fi
if [[ ! -f "$fault" ]]; then
  echo "Missing NetChaos manifest: $fault" >&2
  exit 2
fi
mkdir -p "$out"
runner=.venv/bin/python

"$runner" - "$out" "$fault" "${doses[@]}" <<'PY'
import hashlib, json, pathlib, random, sys
root = pathlib.Path(sys.argv[1])
fault = pathlib.Path(sys.argv[2])
try:
    doses = sorted(int(value) for value in sys.argv[3:])
except ValueError as error:
    raise SystemExit(f"Invalid TTLB: {error}")
if len(doses) < 3 or len(doses) != len(set(doses)) or doses[0] <= 0:
    raise SystemExit("Supply at least three distinct positive TTLBs")
dose_file = root / "doses.txt"
content = "".join(f"{value}\n" for value in doses)
if dose_file.exists() and dose_file.read_text() != content:
    raise SystemExit(f"Different doses already recorded in {dose_file}; use a new output root")
dose_file.write_text(content)
scenario_file = root / "scenario.json"
scenario = {"fault_sha256": hashlib.sha256(fault.read_bytes()).hexdigest(),
            "ttlb_ms": doses, "malicious_count": 3, "reward_lambda": 10}
if scenario_file.exists() and json.loads(scenario_file.read_text()) != scenario:
    raise SystemExit(f"Different scenario already recorded in {scenario_file}; use a new output root")
scenario_file.write_text(json.dumps(scenario, indent=2) + "\n")
order_file = root / "order.txt"
if not order_file.exists():
    attacks = doses * 2
    random.Random(20261106).shuffle(attacks)
    controls_at = {round(index * len(attacks) / 6) for index in range(6)}
    order = []
    for index, ttlb in enumerate(attacks):
        if index in controls_at:
            order.append("control -")
        order.append(f"attack {ttlb}")
    order_file.write_text("\n".join(order) + "\n")
PY

if [[ "${QOE_PLAN_ONLY:-0}" == 1 ]]; then
  cat "$out/order.txt"
  exit 0
fi

has_run() {
  "$runner" - "$out" "$fault" "$1" "$2" "$3" <<'PY'
import hashlib, json, pathlib, sys
root, fault, kind, ttlb, target = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]) if sys.argv[4] != '-' else 0, int(sys.argv[5])
fault_hash = hashlib.sha256(fault.read_bytes()).hexdigest()
matches = 0
for path in root.glob('*/multi-*/summary.json'):
    try:
        summary = json.loads(path.read_text())
        cfg = summary['configuration']
        cache = json.loads((path.parent / 'cache-validation.json').read_text())
        viewers = {item['client']: item for item in summary['viewers']}
        complete_qoe = all(viewers[i]['qoe']['qoe_index'] is not None for i in range(4, 11))
    except (KeyError, ValueError, OSError):
        continue
    if (summary.get('success') and complete_qoe and not cache.get('cached_non_hit_responses')
        and cfg.get('fault_sha256') == fault_hash and cfg.get('strategy') == 'ucb1'
        and cfg.get('clients') == 10 and cfg.get('reward_lambda') == 10
        and cfg.get('seconds') == 120 and cfg.get('measurement_start') == 40
        and cfg.get('replicate') == 1 and cfg.get('allow_viewer_failure')
        and cfg.get('require_fresh_cache')
        and ((kind == 'control' and cfg['malicious_count'] == 0)
             or (kind == 'attack' and cfg['malicious_count'] == 3
                 and cfg.get('malicious_cdn') == 'cdn-1'
                 and cfg.get('attack_ttlb') == ttlb
                 and cfg.get('attack_delay') == 40
                 and not cfg.get('attack_from_start')))):
        matches += 1
sys.exit(0 if matches >= target else 1)
PY
}

started=0
controls=0
declare -A attacks=()
while read -r kind ttlb; do
  if [[ "$kind" == control ]]; then
    controls=$((controls + 1))
    target="$controls"
  else
    attacks[$ttlb]=$((${attacks[$ttlb]:-0} + 1))
    target="${attacks[$ttlb]}"
  fi
  if has_run "$kind" "$ttlb" "$target"; then
    echo "Reuse $kind $ttlb ($target)"
    continue
  fi
  warmup=()
  if ((started > 0)); then warmup=(--skip-warmup); fi
  attack_args=()
  if [[ "$kind" == attack ]]; then
    attack_args=(--malicious-count 3 --attack-ttlb "$ttlb" --attack-delay 40)
  fi
  "$runner" scripts/multi_client.py --strategy ucb1 --clients 10 \
    --seconds 120 --measurement-start 40 --reward-lambda 10 --replicate 1 \
    --require-fresh-cache --allow-viewer-failure \
    --fault-manifest "$fault" --output "$out" \
    "${attack_args[@]}" "${warmup[@]}"
  started=$((started + 1))
  if ! has_run "$kind" "$ttlb" "$target"; then
    echo "Run finished without complete honest-client QoE: $kind $ttlb" >&2
    exit 1
  fi
done < "$out/order.txt"

"$runner" scripts/plot_qoe_dose_response.py "$out" --output "$out/plots"
