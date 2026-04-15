import threading
import time
import logging
from kubernetes import client, config

monitor_logger = logging.getLogger("ContainerMonitor")


class KubernetesMonitor:
    def __init__(
        self,
        interval_seconds: int = 2,
        namespace: str = "default",
        label_selector: str = "app=delivery-node",
    ):
        try:
            # Tenta carregar config de dentro do cluster (ServiceAccount)
            config.load_incluster_config()
        except config.ConfigException:
            # Fallback para execução local usando ~/.kube/config
            config.load_kube_config()

        self.v1 = client.CoreV1Api()
        self.namespace = namespace
        self.label_selector = label_selector
        self.interval = interval_seconds
        self.container_stats = {}  # {pod_name: [{"ip_address": ip, "latitude": lat, "longitude": lon}]}
        self._timer_thread = None
        self.running = False

    def start_collecting(self):
        if not self.running:
            self.running = True
            self._timer_thread = threading.Thread(
                target=self._collection_loop, daemon=True
            )
            self._timer_thread.start()
            monitor_logger.info(
                f"Kubernetes Pod discovery started (interval: {self.interval}s, selector: {self.label_selector})."
            )

    def _collection_loop(self):
        while self.running:
            self.collect_stats()
            # Dorme em pequenos intervalos para responder rápido ao stop
            for _ in range(self.interval * 10):
                if not self.running:
                    break
                time.sleep(0.1)

    def stop_collecting(self):
        monitor_logger.info("Requesting stop of pod discovery...")
        self.running = False
        if self._timer_thread and self._timer_thread.is_alive():
            self._timer_thread.join(timeout=self.interval + 1)
        self._timer_thread = None

    def collect_stats(self):
        try:
            pods = self.v1.list_namespaced_pod(
                self.namespace, label_selector=self.label_selector
            )
            new_stats = {}
            for pod in pods.items:
                if pod.status.phase != "Running":
                    continue

                name = pod.metadata.name
                ip = pod.status.pod_ip

                # Extrai coordenadas das variáveis de ambiente do primeiro container
                lat, lon = None, None
                if pod.spec.containers:
                    env = pod.spec.containers[0].env
                    if env:
                        for e in env:
                            if e.name == "LATITUDE":
                                try:
                                    lat = float(e.value)
                                except:
                                    pass
                            elif e.name == "LONGITUDE":
                                try:
                                    lon = float(e.value)
                                except:
                                    pass

                new_stats[name] = [
                    {"ip_address": ip, "latitude": lat, "longitude": lon}
                ]
            self.container_stats = new_stats
        except Exception as e:
            monitor_logger.error(f"Error in Kubernetes pod discovery: {e}")

    def getNodes(self) -> list:
        nodes = []
        for name, stats_list in self.container_stats.items():
            if stats_list:
                nodes.append((name, stats_list[-1]["ip_address"]))
        return nodes

    def get_node_coordinates(self) -> dict:
        coords = {}
        for name, stats_list in self.container_stats.items():
            if stats_list:
                s = stats_list[-1]
                if s["latitude"] is not None and s["longitude"] is not None:
                    coords[name] = {"lat": s["latitude"], "lon": s["longitude"]}
        return coords
