#!/bin/bash

set -e

BUCKET_DIR="./bucket"
KIND_CONFIG="./manifests/kind-config.yaml"
CERTS_SCRIPT="./create_certs.sh"
CERTS_MANIFEST="./manifests/k8s-certs.yaml"
K8S_DEPLOY="./manifests/k8s-deploy.yaml"
KIND_CLUSTER_NAME="kind"

log() {
  echo -e "\033[1;34m[SETUP]\033[0m $1"
}

error() {
  echo -e "\033[1;31m[ERROR]\033[0m $1"
  exit 1
}

log "Checking media bucket in $BUCKET_DIR..."
BUCKET_MEDIA_FILE=""
if [ -d "$BUCKET_DIR" ]; then
  BUCKET_MEDIA_FILE="$(find "$BUCKET_DIR" -type f ! -path "$BUCKET_DIR/README.md" -print -quit)"
fi
if [ -z "$BUCKET_MEDIA_FILE" ]; then
  error "Media bucket is missing or empty. Please populate $BUCKET_DIR before running."
fi

log "Checking Kind cluster..."
if ! kind get clusters | grep -q "^$KIND_CLUSTER_NAME$"; then
  log "Cluster '$KIND_CLUSTER_NAME' not found. Creating..."
  kind create cluster --config "$KIND_CONFIG"
else
  log "Cluster '$KIND_CLUSTER_NAME' already exists."
  kubectl config use-context "kind-$KIND_CLUSTER_NAME"
  if ! docker exec "${KIND_CLUSTER_NAME}-control-plane" test -d /mnt/bucket; then
    error "The existing Kind cluster does not mount /mnt/bucket. Recreate it with: kind delete cluster --name $KIND_CLUSTER_NAME"
  fi
  if kubectl get pod cdn-1 >/dev/null 2>&1; then
    error "The existing Kind cluster still uses direct-mounted CDN pods. Recreate it with: kind delete cluster --name $KIND_CLUSTER_NAME"
  fi
fi

log "Building simulator images changed in this repository..."
docker build -t pafev/content-steering:steering-server-latest ./steering-server
docker build -t pafev/content-steering:client-latest ./client
docker build -t pafev/content-steering:telemetry-service-latest ./telemetry-service
docker build -t pafev/content-steering:origin-latest ./origin
docker build -t pafev/content-steering:cdn-latest ./cdn
docker build -t pafev/content-steering:gateway-latest ./gateway

log "Loading local images into Kind..."
kind load docker-image --name "$KIND_CLUSTER_NAME" pafev/content-steering:steering-server-latest
kind load docker-image --name "$KIND_CLUSTER_NAME" pafev/content-steering:client-latest
kind load docker-image --name "$KIND_CLUSTER_NAME" pafev/content-steering:telemetry-service-latest
kind load docker-image --name "$KIND_CLUSTER_NAME" pafev/content-steering:origin-latest
kind load docker-image --name "$KIND_CLUSTER_NAME" pafev/content-steering:cdn-latest
kind load docker-image --name "$KIND_CLUSTER_NAME" pafev/content-steering:gateway-latest

log "Running certificate generation script..."
if [ ! -f "$CERTS_SCRIPT" ]; then
  error "Certificate script $CERTS_SCRIPT not found."
fi
chmod +x "$CERTS_SCRIPT"
./"$CERTS_SCRIPT"

log "Applying certificate secrets to the cluster..."
if [ ! -f "$CERTS_MANIFEST" ]; then
  error "Certificate manifest $CERTS_MANIFEST was not generated."
fi
kubectl apply -f "$CERTS_MANIFEST"

log "Applying simulator deployments..."
if [ ! -f "$K8S_DEPLOY" ]; then
  error "Deployment manifest $K8S_DEPLOY not found."
fi
# Recreate only simulator standalone pods so rebuilt tags actually take effect.
# This also removes the legacy standalone CSS before applying its Deployment.
log "Restarting simulator pods (CDN caches are ephemeral)..."
kubectl delete pod steering-server dash-client gateway origin-server cdn-1-edge-1 cdn-2-edge-1 cdn-3-edge-1 --ignore-not-found
kubectl apply -f "$K8S_DEPLOY"
kubectl rollout restart deployment/steering-server deployment/telemetry-service
kubectl rollout status deployment/steering-server --timeout=180s
kubectl rollout status deployment/telemetry-service --timeout=180s

log "Waiting for pods to be ready..."
kubectl wait --for=condition=Ready pod/dash-client pod/gateway pod/origin-server pod/cdn-1-edge-1 pod/cdn-2-edge-1 pod/cdn-3-edge-1 --timeout=300s

log "--------------------------------------------------"
log " SETUP COMPLETED SUCCESSFULLY! "
log "--------------------------------------------------"
log "To access the UI, run:"
log "  kubectl port-forward pod/gateway 5000:80"
log "Then open: http://localhost:5000"
log "--------------------------------------------------"
