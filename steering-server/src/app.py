import time
import os
import csv
import json
import logging
import argparse
from flask import Flask, request, jsonify
from flask_cors import CORS
from dash_parser import DashParser
from monitor import KubernetesMonitor
from strategies import (
    EpsilonGreedy,
    RandomSelector,
    NoSteeringSelector,
    UCB1Selector,
    LinUCBSelector,
)

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "config.json"
)
with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

STEERING_PORT = 30500
PROJECT_ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
LOG_DIR = os.path.join(PROJECT_ROOT_DIR, "logs", "raw_data")
CSV_HEADERS = [
    "timestamp_server",
    "sim_time_client",
    "client_lat",
    "client_lon",
    "server_used_for_latency",
    "experienced_latency_ms_CLIENT",
    "experienced_latency_ms",
    "steering_decision_main_server",
    "rl_strategy",
    "rl_counts_json",
    "rl_actual_counts_json",
    "rl_values_json",
    "gamma_value",
]

selector_instance = None
selector_initialized = False
last_steering_main_server_decision = "N/A"
current_strategy_name = "N/A"
active_log_filename = None
last_client_coords = {"lat": None, "lon": None, "time": 0}
last_decision_contexts = {}

app_logger = logging.getLogger("SteeringApp")
monitor_logger = logging.getLogger("ContainerMonitor")
selector_strategies_logger = logging.getLogger("SelectorStrategies")


def _configure_all_loggers(default_level=logging.WARNING):
    loggers = [app_logger, monitor_logger, selector_strategies_logger]
    formatter = logging.Formatter("%(name)s - %(levelname)s: %(message)s")
    for logger in loggers:
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        logger.setLevel(default_level)
        logger.propagate = False


def _create_strategy_instance(strategy_name: str, monitor_ref):
    cfg = CONFIG.get("strategies", {}).get(strategy_name, {})
    constructors = {
        "epsilon_greedy": lambda: EpsilonGreedy(
            epsilon=cfg.get("epsilon", 0.2), counts={}, values={}, monitor=monitor_ref
        ),
        "no_steering": lambda: NoSteeringSelector(monitor=monitor_ref),
        "random": lambda: RandomSelector(monitor=monitor_ref),
        "ucb1": lambda: UCB1Selector(c=cfg.get("c", 1.0), monitor=monitor_ref),
        "linucb": lambda: LinUCBSelector(
            d=cfg.get("d", 3), alpha=cfg.get("alpha", 0.5), monitor=monitor_ref
        ),
    }
    builder = constructors.get(strategy_name)
    if builder is None:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    return builder()


def setup_csv_logging(filename: str):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, mode="w", newline="", buffering=1) as file:
        csv.writer(file).writerow(CSV_HEADERS)


def log_data_to_csv(data_dict: dict, filename: str):
    row = [data_dict.get(h) for h in CSV_HEADERS]
    with open(filename, mode="a", newline="", buffering=1) as file:
        csv.writer(file).writerow(row)


def get_unique_log_filename(
    base_name: str, user_suffix: str, directory: str = LOG_DIR
) -> str:
    cnt = 1
    while True:
        path = os.path.join(directory, f"{base_name}{user_suffix}_{cnt}.csv")
        if not os.path.exists(path):
            return path
        cnt += 1


class Main:
    def __init__(
        self, sel_inst, strategy_arg, log_suffix, host_suffix, gateway_mode=True
    ):
        global selector_instance, current_strategy_name
        selector_instance, current_strategy_name = sel_inst, strategy_arg
        self.log_suffix, self.host_suffix, self.gateway_mode = (
            log_suffix,
            host_suffix,
            gateway_mode,
        )
        self.last_reported_latencies = {}
        self.app = Flask(__name__)
        CORS(self.app)
        self._register_routes()

    def _initialize_selector_if_needed(self) -> bool:
        global selector_initialized, selector_instance
        if not selector_initialized or not selector_instance.nodes:
            nodes_info = monitor.getNodes()
            if nodes_info:
                node_names = [info[0] for info in nodes_info if info and info[0]]
                selector_instance.initialize(node_names)
                selector_initialized = True
                return True
            return False
        return True

    def _get_simple_context(self, srv_name: str):
        import numpy as np

        t = time.localtime()
        time_of_day = (t.tm_hour + t.tm_min / 60.0) / 24.0
        last_lat = self.last_reported_latencies.get(srv_name, 50.0)
        norm_lat = min(1.0, float(last_lat) / 2000.0)
        return np.array([1.0, time_of_day, norm_lat])

    def _register_routes(self):
        @self.app.route("/reset_simulation", methods=["POST"])
        def reset_simulation():
            global selector_instance, active_log_filename, selector_initialized
            self.last_reported_latencies = {}
            data = request.get_json(silent=True) or {}
            target_dir = LOG_DIR
            if data.get("log_subdir"):
                target_dir = os.path.join(
                    LOG_DIR, os.path.normpath(data.get("log_subdir"))
                )

            active_log_filename = get_unique_log_filename(
                f"log_{current_strategy_name}", self.log_suffix, target_dir
            )
            setup_csv_logging(active_log_filename)
            selector_instance = _create_strategy_instance(
                current_strategy_name, monitor
            )
            selector_initialized = False
            return jsonify(
                {
                    "message": "Reset OK",
                    "new_log": os.path.basename(active_log_filename),
                }
            ), 200

        @self.app.route("/coords", methods=["POST"])
        def coords_update():
            global last_steering_main_server_decision, last_client_coords
            data = request.json
            s_t, lat, lon, rt_c, srv_u_fb = (
                data.get("time"),
                data.get("lat"),
                data.get("long"),
                data.get("rt"),
                data.get("server_used"),
            )
            if srv_u_fb and srv_u_fb != "cloud":
                last_steering_main_server_decision = srv_u_fb
            if srv_u_fb and rt_c is not None:
                self.last_reported_latencies[srv_u_fb] = rt_c
            last_client_coords.update({"lat": lat, "lon": lon, "time": time.time()})

            log_base = self._build_log_base(s_t, lat, lon)
            if srv_u_fb and rt_c is not None:
                return self._handle_rl_feedback(srv_u_fb, rt_c, log_base)
            return self._handle_location_only(srv_u_fb, rt_c, log_base)

        @self.app.route("/sim_state", methods=["GET"])
        def sim_state():
            return jsonify(
                {
                    "latencies": self.last_reported_latencies,
                    "decision": last_steering_main_server_decision,
                    "strategy": current_strategy_name,
                }
            ), 200

        @self.app.route("/<path:name>", methods=["GET", "POST"])
        def do_remote_steering(name: str):
            global last_steering_main_server_decision, last_decision_contexts
            if not self._initialize_selector_if_needed():
                return jsonify({"error": "Not ready"}), 503

            if isinstance(selector_instance, LinUCBSelector):
                node_names = [
                    info[0] for info in monitor.getNodes() if info and info[0]
                ]
                contexts = {n: self._get_simple_context(n) for n in node_names}
                last_decision_contexts = contexts
                ordered_nodes = selector_instance.select_arm(contexts=contexts)
            else:
                ordered_nodes = selector_instance.select_arm()

            last_steering_main_server_decision = (
                ordered_nodes[0] if ordered_nodes else "N/A"
            )
            uri = f"{request.headers.get('X-Forwarded-Proto', request.scheme)}://{request.headers.get('X-Forwarded-Host', request.host)}{request.headers.get('X-Forwarded-Prefix', '')}"
            resp = dash_parser.build(
                target=request.args.get("_DASH_pathway", ""),
                nodes=[(n, n) for n in ordered_nodes],
                uri=uri,
                request=request,
                host_suffix=self.host_suffix,
                gateway_mode=self.gateway_mode,
                request_host=request.headers.get("X-Forwarded-Host", request.host),
            )
            response = jsonify(resp)
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response, 200

    def run(self):
        s_dir = os.path.dirname(os.path.abspath(__file__))
        cert, key = (
            os.path.join(s_dir, "..", "certs", "steering-server.pem"),
            os.path.join(s_dir, "..", "certs", "steering-server-key.pem"),
        )
        self.app.run(
            host="0.0.0.0",
            port=STEERING_PORT,
            debug=False,
            ssl_context=(cert, key) if os.path.exists(cert) else None,
        )

    def _build_log_base(self, s_t, lat, lon):
        return {
            "timestamp_server": time.time(),
            "sim_time_client": s_t,
            "client_lat": lat,
            "client_lon": lon,
            "steering_decision_main_server": last_steering_main_server_decision,
            "rl_strategy": current_strategy_name,
            "rl_counts_json": json.dumps(getattr(selector_instance, "counts", {})),
            "rl_actual_counts_json": json.dumps(
                getattr(selector_instance, "real_counts", {})
            ),
            "rl_values_json": json.dumps(getattr(selector_instance, "values", {})),
            "gamma_value": None,
        }

    def _handle_rl_feedback(self, srv_name, rt_real, log_base):
        log_entry = {
            **log_base,
            "server_used_for_latency": srv_name,
            "experienced_latency_ms_CLIENT": rt_real,
            "experienced_latency_ms": rt_real,
        }
        if active_log_filename:
            log_data_to_csv(log_entry, filename=active_log_filename)
        if not self._initialize_selector_if_needed() or not hasattr(
            selector_instance, "update"
        ):
            return "OK", 200
        reward = 1000.0 / float(rt_real) if float(rt_real) > 0 else 0.0
        kw = (
            {"context": self._get_simple_context(srv_name)}
            if isinstance(selector_instance, LinUCBSelector)
            else {}
        )
        selector_instance.update(srv_name, reward, **kw)
        return "OK", 200

    def _handle_location_only(self, srv_name, rt_c, log_base):
        if active_log_filename:
            log_entry = {
                **log_base,
                "server_used_for_latency": srv_name,
                "experienced_latency_ms_CLIENT": rt_c,
                "experienced_latency_ms": rt_c,
            }
            log_data_to_csv(log_entry, filename=active_log_filename)
        return "OK", 200


dash_parser = DashParser()
monitor = KubernetesMonitor()
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", type=str, default="epsilon_greedy")
    parser.add_argument("--log_suffix", type=str, default="")
    parser.add_argument("--host_suffix", type=str, default=".default.svc.cluster.local")
    args = parser.parse_args()
    _configure_all_loggers(logging.INFO)
    current_strategy_name = args.strategy
    monitor.start_collecting()
    time.sleep(2)
    selector_instance = _create_strategy_instance(args.strategy, monitor)
    Main(
        selector_instance, current_strategy_name, args.log_suffix, args.host_suffix
    ).run()
