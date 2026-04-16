# Simulator Architecture Summary (for AI Context)

## Overview
This is a DASH Content Steering simulator running on Kubernetes (Kind). It allows simulating dynamic CDN selection based on real-time metrics (latency, distance) and RL strategies.

## Components
1.  **DASH Client (dash-client):** Nginx-based static server serving the DASH player (dash.js). It acts as a reverse proxy for the Steering Server and Delivery Nodes to keep traffic internal.
2.  **Steering Server:** Flask API that implements the Content Steering spec.
    *   **Strategies:** Epsilon-greedy, UCB1, LinUCB, Oracle Best.
    *   **Oracle:** Simulates network conditions, micro-bursts, and location-based latency.
    *   **Gateway Mode (Default):** Returns URIs compatible with the Client's reverse proxy logic.
3.  **Delivery Nodes (delivery-node-1, 2, 3):** Caddy servers serving video segments from a shared dataset.
4.  **Gateway Pod:** An external-facing Nginx proxy that allows local browser access to the `dash-client` UI while maintaining internal cluster traffic for latency simulation.

## Infrastructure (Kind)
*   **Cluster:** 1 Control Plane + 2 Workers.
*   **Dataset:** Mounted via `hostPath` from `./delivery-nodes/dataset` to `/mnt/dataset` on all nodes using `kind-config.yaml`.
*   **Certs:** SSL handled via `mkcert` and Kubernetes Secrets.

## Networking Logic
*   **Browser** -> `localhost:5000` (Gateway) -> `dash-client:80` (Internal).
*   **dash-client** -> `/steering/` -> `steering-server:30500`.
*   **dash-client** -> `/node[1-3]/` -> `delivery-node-[1-3]:443`.
