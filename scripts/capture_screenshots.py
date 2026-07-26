"""Capture dashboard screenshots for the submission package.

Uses a real browser at 2x device scale so the images stand up to being placed on
a slide. Requires the backend to be running:

    python scripts/run_server.py --policy llm
    python scripts/capture_screenshots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

URL = "http://localhost:8000"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"

# Wait long enough for the WebSocket to seed history and at least one decision to
# land, otherwise the panels capture in their "awaiting data" state.
SETTLE_MS = 9000


def capture() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1250}, device_scale_factor=2)
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(SETTLE_MS)

        page.screenshot(path=OUTPUT_DIR / "dashboard-full.png", full_page=True)
        print("dashboard-full.png")

        panels = {
            "Decision impact": "decision-impact.png",
            "Safety layer": "safety-layer.png",
            "Digital twin": "digital-twin.png",
            "Validated performance": "benchmark.png",
            "System pipeline": "system-pipeline.png",
            "Decision audit trail": "audit-trail.png",
        }
        for title, filename in panels.items():
            panel = page.locator("section").filter(has=page.get_by_text(title, exact=True)).first
            if panel.count() == 0:
                print(f"  skipped {filename}: no panel titled {title!r}")
                continue
            panel.screenshot(path=OUTPUT_DIR / filename)
            print(f"  {filename}")

        # The safety layer is most convincing mid-intervention, so trigger a real
        # clamped command and capture the result.
        page.get_by_role("button", name="Request 4 °C").click()
        page.wait_for_timeout(2500)
        safety = page.locator("section").filter(
            has=page.get_by_text("Safety layer", exact=True)
        ).first
        safety.screenshot(path=OUTPUT_DIR / "safety-layer-clamped.png")
        print("  safety-layer-clamped.png")

        # Architecture overlay, opened the way a presenter would.
        page.keyboard.press("?")
        page.wait_for_timeout(900)
        page.screenshot(path=OUTPUT_DIR / "architecture-overlay.png")
        print("  architecture-overlay.png")

        browser.close()

    print(f"\nWrote to {OUTPUT_DIR}")


if __name__ == "__main__":
    capture()
