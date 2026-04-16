# Content Steering (DASH) on Kubernetes Cluster

This repository contains a Content Steering simulator for DASH running on a Kubernetes cluster (Kind). The simulator allows for real-time testing of different CDN selection strategies.

Inspired by: [alissonpef/Content-Steering](https://github.com/alissonpef/Content-Steering)

## Architecture

For details on component architecture and network logic, please refer to the [AGENTS.md](./AGENTS.md) file.

## Requirements

- **Docker**
- **Kind** (for local cluster)
- **kubectl**
- **mkcert** (for SSL certificate generation)

## How to Run (Automatic Setup)

The `setup.sh` script automates the entire process of cluster creation, certificate generation, and manifest deployment.

1.  Ensure your dataset is present in `./delivery-nodes/dataset`.
2.  Run the setup script:

```bash
./setup.sh
```

The script will:
- Validate the presence of the dataset.
- Create the Kind cluster (if it doesn't exist) using the `kind-config.yaml` file.
- Generate local SSL certificates and Kubernetes secrets.
- Apply the deployment manifests from `k8s-deploy.yaml`.
- Wait until all Pods are ready.

## Interface Access

After the setup is finished, to view the DASH client interface, you need to configure a port-forward for the gateway component:

```bash
kubectl port-forward pod/gateway 5000:80
```

Access the simulator at: `http://localhost:5000`

> **Note:** The gateway acts as a reverse proxy for the actual client component inside the cluster, ensuring that all Content Steering traffic remains internal so that latency simulations are accurate.
