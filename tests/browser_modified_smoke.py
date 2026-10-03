"""Verify a modified player lies about a real CDN-1 video download."""
import argparse
import json
import uuid

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:5000")
    parser.add_argument("--browser", default="/usr/bin/brave-browser")
    args = parser.parse_args()
    run = "modified-smoke-" + uuid.uuid4().hex
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser, headless=True,
                                             args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page()
        reports, media, errors = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda req: reports.append(req.post_data)
                if "/telemetry/v1/cmcd/events" in req.url else None)
        page.on("response", lambda response: media.append(response.url)
                if "/cdn1/" in response.url and ".m4s" in response.url and response.status == 200 else None)
        page.goto(f"{args.base}/?run_id={run}&strategy=fixed&attack_cdn=cdn-1&attack_ttlb_ms=20000")
        page.get_by_role("button", name="Load video").click()
        page.wait_for_function("document.querySelector('video').readyState >= 1")
        page.evaluate("document.querySelector('video').play()")
        try:
            page.wait_for_function("window.__cmcdLieAudit?.length > 0", timeout=5000)
        finally:
            print(json.dumps(dict(audit=page.evaluate("window.__cmcdLieAudit?.slice(0, 3)"),
                                  reports=reports[:3], media=media[:3], errors=errors), indent=2))
        assert not errors
        assert media
        assert any("ttlb=20000" in body and "ot=v" in body for body in reports)
        browser.close()


if __name__ == "__main__":
    main()
