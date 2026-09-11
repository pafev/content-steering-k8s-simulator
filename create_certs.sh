#!/bin/bash

set -e

SERVICES=(
  "cdn-1"
  "cdn-2"
  "cdn-3"
)

echo "=================================================="
echo " Verifying the local mkcert CA installation... "
echo "=================================================="
mkcert -install
echo ""

for SERVICE_NAME in "${SERVICES[@]}"; do
  DEST_DIR=""

  if [[ "$SERVICE_NAME" == "cdn-"* ]]; then
    DEST_DIR="./cdn/certs"
  else
    echo "WARNING: Unknown service name: '$SERVICE_NAME'. Skipping."
    continue
  fi

  echo "--------------------------------------------------"
  echo "  Creating certificate for: $SERVICE_NAME"
  echo "  Destination directory:   $DEST_DIR"
  echo "--------------------------------------------------"

  mkdir -p "$DEST_DIR"

  echo "--> Generating certificate with mkcert..."
  mkcert -cert-file "./${SERVICE_NAME}.pem" -key-file "./${SERVICE_NAME}-key.pem" "$SERVICE_NAME" "$SERVICE_NAME.default.svc.cluster.local" "localhost" 127.0.0.1

  echo "--> Moving certificate files..."
  mv "./${SERVICE_NAME}.pem" "$DEST_DIR/"
  mv "./${SERVICE_NAME}-key.pem" "$DEST_DIR/"

  echo "--> Success! Certificate for '$SERVICE_NAME' created in $DEST_DIR"
  echo ""
done

echo "=================================================="
echo "   ALL CERTIFICATES WERE CREATED SUCCESSFULLY!   "
echo "=================================================="

K8S_CERTS_DIR="./manifests/k8s-certs.yaml"

echo ""
echo "--> Creating Kubernetes Secrets..."
echo "--------------------------------------------------"
echo "---" >"${K8S_CERTS_DIR}"
kubectl create secret generic cdn-1-certs --from-file=cdn.pem=./cdn/certs/cdn-1.pem --from-file=cdn-key.pem=./cdn/certs/cdn-1-key.pem --dry-run=client -o yaml >>"${K8S_CERTS_DIR}"
echo "---" >>"${K8S_CERTS_DIR}"
kubectl create secret generic cdn-2-certs --from-file=cdn.pem=./cdn/certs/cdn-2.pem --from-file=cdn-key.pem=./cdn/certs/cdn-2-key.pem --dry-run=client -o yaml >>"${K8S_CERTS_DIR}"
echo "---" >>"${K8S_CERTS_DIR}"
kubectl create secret generic cdn-3-certs --from-file=cdn.pem=./cdn/certs/cdn-3.pem --from-file=cdn-key.pem=./cdn/certs/cdn-3-key.pem --dry-run=client -o yaml >>"${K8S_CERTS_DIR}"
