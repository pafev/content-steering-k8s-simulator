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
        request_host: str = "localhost",
    ) -> dict:
        message = {"VERSION": 1, "TTL": 5, "RELOAD-URI": f"{uri}{request.path}"}
        pathway_priority_nodes = [f"{node[0]}" for node in nodes] if nodes else []
        message["PATHWAY-PRIORITY"] = pathway_priority_nodes + ["cloud"]
        if nodes:
            message["PATHWAY-CLONES"] = self._generate_pathway_clones(
                nodes, host_suffix, gateway_mode, request_host
            )
        return message

    def _generate_pathway_clones(
        self, nodes: list, host_suffix: str, gateway_mode: bool, request_host: str = "localhost"
    ) -> list:
        clones = []
        # Se estiver em gateway_mode, usamos o host que o browser usou para acessar (ex: localhost:3003)
        # e simplificamos "delivery-node-1" para "node1" para bater com o Nginx
        for node_info in nodes:
            node_name = node_info[0]

            if gateway_mode:
                short_name = node_name.replace("delivery-node-", "node")
                host = f"{request_host}/{short_name}"
            else:
                host = f"{node_name}{host_suffix}"

            clone = {
                "BASE-ID": "cloud",
                "ID": f"{node_name}",
                "URI-REPLACEMENT": {"HOST": f"{host}"},
            }
            clones.append(clone)
        return clones
