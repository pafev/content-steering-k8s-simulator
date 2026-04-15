class DashParser:
    def __init__(self):
        pass

    def build(
        self,
        target: str,
        nodes: list,
        uri: str,
        request,
        host_suffix: str = ".default.svc.cluster.local",
        gateway_mode: bool = False,
    ) -> dict:
        message = {"VERSION": 1, "TTL": 5, "RELOAD-URI": f"{uri}{request.path}"}
        pathway_priority_nodes = [f"{node[0]}" for node in nodes] if nodes else []
        message["PATHWAY-PRIORITY"] = pathway_priority_nodes + ["cloud"]
        if nodes:
            message["PATHWAY-CLONES"] = self._generate_pathway_clones(
                nodes, host_suffix, gateway_mode
            )
        return message

    def _generate_pathway_clones(
        self, nodes: list, host_suffix: str, gateway_mode: bool
    ) -> list:
        clones = []
        # No modo path-based gateway, assumimos que o browser acessa via localhost:5000 (ou porta definida no port-forward)
        # O DASH CS irá concatenar esse host com o resto da URL.
        gateway_paths = {
            "delivery-node-1": "localhost:5000/node1",
            "delivery-node-2": "localhost:5000/node2",
            "delivery-node-3": "localhost:5000/node3",
        }
        for node_info in nodes:
            node_name = node_info[0]

            if gateway_mode and node_name in gateway_paths:
                host = gateway_paths[node_name]
            else:
                host = f"{node_name}{host_suffix}"

            clone = {
                "BASE-ID": "cloud",
                "ID": f"{node_name}",
                "URI-REPLACEMENT": {"HOST": f"{host}"},
            }
            clones.append(clone)
        return clones
