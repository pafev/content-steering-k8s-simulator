"""Serve this client's player page locally and run its Chromium instance."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import subprocess

from playwright.sync_api import sync_playwright


server = ThreadingHTTPServer(("127.0.0.1", 8080), partial(SimpleHTTPRequestHandler, directory="/app"))
Thread(target=server.serve_forever, daemon=True).start()

with sync_playwright() as playwright:
    subprocess.run([
        playwright.chromium.executable_path,
        "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        "--remote-debugging-port=9222", "--remote-debugging-address=0.0.0.0",
        "--remote-allow-origins=*", "--autoplay-policy=no-user-gesture-required",
        "--user-data-dir=/tmp/dash-client-chromium", "about:blank",
    ], check=True)
