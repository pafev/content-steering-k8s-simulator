"""Run against tests/compose.yaml or a forwarded Kind gateway."""
import argparse
import json
import time
import uuid

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:15000")
    parser.add_argument("--browser", help="Path to a Chromium/Chrome/Brave executable")
    parser.add_argument("--seconds", type=int, default=20)
    args = parser.parse_args()
    run_id = "browser-" + uuid.uuid4().hex
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.browser, headless=True,
            args=["--autoplay-policy=no-user-gesture-required"],
        )
        context = browser.new_context()
        errors, reports, console = [], [], []
        pages, media_by_page = [], []

        def start_client():
            page = context.new_page()
            pages.append(page)
            media = []
            media_by_page.append(media)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda msg: console.append(msg.text))
            page.on("request", lambda req: reports.append(req.post_data)
                    if "/v1/cmcd/events" in req.url else None)
            page.on("request", lambda req: media.append(req.url)
                    if ".m4s" in req.url else None)
            page.goto(f"{args.base}/?run_id={run_id}&strategy=ucb1")
            page.get_by_role("button", name="Load video").click()
            try:
                page.wait_for_function("document.querySelector('video').readyState >= 1", timeout=20000)
            except Exception:
                print(json.dumps(dict(status=page.locator("#status").inner_text(),
                    console=console[-25:], reports=reports[-3:], media=media[-3:], errors=errors), indent=2), flush=True)
                raise
            page.evaluate("void document.querySelector('video').play().catch(console.error)")
            return page

        first = start_client()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            first_state = context.request.get(
                f"{args.base}/telemetry/v1/state/{run_id}").json()
            if sum(int(v.get("n", 0)) for v in first_state["model"].values()) >= 1:
                break
            first.wait_for_timeout(250)
        else:
            raise AssertionError("first client produced no correlated CMCD feedback")

        # A later client must consume the model updated by the first client. On a
        # zero-latency local VOD, one client can buffer the whole asset before the
        # next steering TTL, so staggering is the deterministic multi-client test.
        start_client()
        first.wait_for_timeout(args.seconds * 1000)
        state = context.request.get(f"{args.base}/telemetry/v1/state/{run_id}").json()
        playback = [page.evaluate("({time: document.querySelector('video').currentTime, error: document.querySelector('video').error?.message, status: document.getElementById('status').textContent, priority: document.getElementById('priority').textContent, pathway: document.getElementById('active-pathway').textContent})") for page in pages]
        print(json.dumps(dict(run_id=run_id, playback=playback, state=state,
                             report_examples=reports[:4],
                             media_examples=[items[:4] for items in media_by_page],
                             errors=errors), indent=2))
        assert not errors
        assert all(item["time"] > 3 and not item.get("error") for item in playback)
        assert sum(int(v.get("n", 0)) for v in state["model"].values()) >= 2
        assert all(any("cs_decision=" in url for url in media) for media in media_by_page)
        assert any('e=rr' in body for body in reports)
        assert sum(int(v.get("cache_hit_count", 0)) for v in state["cdn"].values()) > 0
        assert sum(bool(v) for v in media_by_page) == 2
        assert len({url.split("/", 4)[3] for media in media_by_page for url in media}) >= 2
        assert sum(int(v.get("n", 0)) > 0 for v in state["model"].values()) >= 2
        for aggregate in state["cmcd"].values():
            if "ttfb_sum_ms" in aggregate:
                assert float(aggregate["ttfb_sum_ms"]) <= float(aggregate["ttlb_sum_ms"])
        assert len({page.locator("#session-id").inner_text() for page in pages}) == 2
        browser.close()


if __name__ == "__main__":
    main()
