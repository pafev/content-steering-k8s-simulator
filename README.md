# Content Steering (DASH) em cluster Kubernetes

repository inspired by [alissonpef/Content-Steering](https://github.com/alissonpef/Content-Steering)

## How to Run

First, set up a Kubernetes cluster for testing, either from a cloud provider (AWS, Azure, Digital Ocean, etc.) or locally (Kind)

### Certificate Generation

Communication between components occurs via the HTTPS protocol. Therefore, you will need to generate SSL certificates for the content delivery nodes and the steering server.

To do this, run the script below:

```bash
./create_certs.sh
```

Next, you will apply these certificates to the cluster:

```bash
kubectl apply -f ./k8s-deploy-certs.yaml
```

### Installing the components

To install the components on the cluster, simply run the following command from the root of the repository:

```bash
kubectl apply -f ./k8s-deploy.yaml
```

Wait for the components to stabilize and for all of them to be in the "Running" state

Then, to interact with and view the client interface locally, set up a port forwarding rule with the gateway

```bash
kubectl port-forward pod/gateway 5000:80
```

E então acesse `http://localhost:5000` para visualizar a interface do cliente.

Obs.: o gateway apenas simula a interface do cliente, enviando as requests realizadas no seu browser para o real componente do cliente que está rodando dentro do cluster Kubernetes, pois todo tráfego de content steering ocorre internamente no cluster
