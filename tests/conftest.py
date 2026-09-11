import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
import redis

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "steering-server/src"), str(ROOT / "telemetry-service/src")]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


css = load_module("css_app", "steering-server/src/app.py")
telemetry = load_module("telemetry_app", "telemetry-service/src/app.py")


@pytest.fixture
def db(tmp_path):
    socket_path = str(tmp_path / "redis.sock")
    process = subprocess.Popen(
        ["redis-server", "--port", "0", "--unixsocket", socket_path,
         "--save", "", "--appendonly", "no"], stdout=subprocess.DEVNULL,
    )
    connection = redis.Redis(unix_socket_path=socket_path, decode_responses=True)
    try:
        for _ in range(100):
            try:
                connection.ping()
                break
            except redis.ConnectionError:
                if process.poll() is not None:
                    pytest.fail("Temporary Redis failed to start")
                time.sleep(0.02)
        else:
            pytest.fail("Temporary Redis did not become ready")
        yield connection
    finally:
        connection.close()
        process.terminate()
        process.wait(timeout=5)


@pytest.fixture
def services(db, monkeypatch):
    from store import TelemetryStore
    store = TelemetryStore(db)
    monkeypatch.setattr(telemetry, "store", store)
    return css.create_app(db).test_client(), telemetry.app.test_client(), store
