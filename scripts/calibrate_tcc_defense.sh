#!/usr/bin/env bash
# Six separate honest pilots, then activate the telemetry defense reference.
set -euo pipefail
if (($# != 1)); then echo "Usage: bash scripts/calibrate_tcc_defense.sh OUTPUT-ROOT" >&2; exit 2; fi
out=$1
mkdir -p "$out"
for i in 1 2 3 4 5 6; do
  existing=$(find "$out/pilot-$i" -path '*/multi-*/summary.json' -print -quit 2>/dev/null || true)
  if [[ -n "$existing" ]]; then
    continue
  fi
  .venv/bin/python scripts/multi_client.py --strategy ucb1 --clients 10 \
    --seconds 120 --measurement-start 40 --reward-lambda 10 \
    --max-video-kbps 3000 --require-fresh-cache --allow-viewer-failure \
    --capture-video-feedback --fault-manifest manifests/risk-matrix-netchaos.yaml \
    --output "$out/pilot-$i"
done
.venv/bin/python scripts/build_defense_reference.py "$out" "$out/reference.json"
kubectl --context kind-kind create configmap telemetry-defense-reference \
  --from-file=reference.json="$out/reference.json" --dry-run=client -o yaml | \
  kubectl --context kind-kind apply -f -
kubectl --context kind-kind set env deployment/telemetry-service DEFENSE_ENABLED=true
kubectl --context kind-kind rollout restart deployment/telemetry-service
kubectl --context kind-kind rollout status deployment/telemetry-service --timeout=180s
