class DashParser:
    def __init__(self):
        pass

    def build(self, target: str, nodes: list, uri: str, request, host_suffix: str = ".default.svc.cluster.local", gateway_mode: bool = False) -> dict:
        message = {"VERSION": 1, "TTL": 5, "RELOAD-URI": f"{uri}{request.path}"}
        pathway_priority_nodes = [f"{node[0]}" for node in nodes] if nodes else []
        message["PATHWAY-PRIORITY"] = pathway_priority_nodes + ["cloud"]
        if nodes:
            message["PATHWAY-CLONES"] = self._generate_pathway_clones(nodes, host_suffix, gateway_mode)
        return message

    def _generate_pathway_clones(self, nodes: list, host_suffix: str, gateway_mode: bool) -> list:
        clones = []
        gateway_ports = {
            "delivery-node-1": 8001,
            "delivery-node-2": 8002,
            "delivery-node-3": 8003
        }
        for node_info in nodes:
            node_name = node_info[0]
            
            if gateway_mode and node_name in gateway_ports:
                host = f"localhost:{gateway_ports[node_name]}"
            else:
                host = f"{node_name}{host_suffix}"

            clone = {
                "BASE-ID": "cloud",
                "ID": f"{node_name}",
                "URI-REPLACEMENT": {
                    "HOST": f"{host}"
                },
            }
            clones.append(clone)
        return clones
