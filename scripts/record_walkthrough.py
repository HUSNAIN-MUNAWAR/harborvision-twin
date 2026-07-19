from __future__ import annotations

import shutil
from pathlib import Path

from browser_bridge import ROOT, api_bridge, build_embedded_html
from playwright.sync_api import Page, sync_playwright

OUT = ROOT / "docs" / "demo"


def open_view(page: Page, label: str, pause_ms: int = 1200) -> None:
    page.get_by_role("button", name=label).click()
    page.wait_for_timeout(pause_ms)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.webm"):
        stale.unlink()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(OUT),
            record_video_size={"width": 1440, "height": 900},
        )
        page = context.new_page()
        page.expose_function("__harborApiBridge", api_bridge)
        page.set_content(build_embedded_html(), wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        page.get_by_role("button", name="Enter operations console").click()
        page.wait_for_selector("text=Executive command center")
        page.wait_for_timeout(1600)

        open_view(page, "Digital twin")
        if page.locator("#load-playback").count():
            page.locator("#load-playback").click()
            page.wait_for_timeout(1000)
            if page.locator("#play-playback").count():
                page.locator("#play-playback").click()
                page.wait_for_timeout(1800)
                page.locator("#pause-playback").click()
        open_view(page, "Container registry")
        if page.locator(".container-open").count():
            page.locator(".container-open").first.click()
            page.wait_for_timeout(1100)
        open_view(page, "Yard intelligence")
        if page.locator(".block-open").count():
            page.locator(".block-open").first.click()
            page.wait_for_timeout(1000)
        open_view(page, "Safety center")
        open_view(page, "Equipment health")
        if page.locator(".equipment-open").count():
            page.locator(".equipment-open").first.click()
            page.wait_for_timeout(900)
        open_view(page, "Incidents")
        if page.locator(".incident-open").count():
            page.locator(".incident-open").first.click()
            page.wait_for_timeout(1000)
        open_view(page, "Simulation control")
        page.locator("#simulation-scenario").select_option("gate_congestion")
        page.get_by_role("button", name="Create run").click()
        page.wait_for_timeout(700)
        page.get_by_role("button", name="start", exact=True).click()
        page.wait_for_timeout(500)
        page.get_by_role("button", name="advance", exact=True).click()
        page.wait_for_timeout(1400)
        open_view(page, "Analytics")
        open_view(page, "Reports")
        if page.locator(".report-preview").count():
            page.locator(".report-preview").first.click()
            page.wait_for_timeout(1300)
        open_view(page, "System health")

        video = page.video
        context.close()
        browser.close()
        source = Path(video.path())
        target = OUT / "harborvision-phase2-walkthrough.webm"
        if source != target:
            shutil.move(source, target)
        print(target)


if __name__ == "__main__":
    main()
