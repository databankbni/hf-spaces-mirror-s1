from pathlib import Path
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT / "_ui_upload_sample.png"


def make_sample_image() -> None:
    img = Image.new("RGB", (900, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((40, 60), "SearchMyFiles UI upload smoke test", fill=(20, 20, 20))
    draw.text((40, 110), "If this uploads, picker + upload pipeline is working.", fill=(20, 20, 20))
    img.save(SAMPLE)


def run_test() -> None:
    make_sample_image()

    def on_page_error(err):
        print(f"PAGEERROR: {err}")
        print(f"PAGEERROR_REPR: {err!r}")
        name = getattr(err, "name", None)
        message = getattr(err, "message", None)
        if name or message:
            print(f"PAGEERROR_NAME: {name}")
            print(f"PAGEERROR_MESSAGE: {message}")
        stack = getattr(err, "stack", None)
        if stack:
            print(f"PAGEERROR_STACK: {stack}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("pageerror", on_page_error)
        page.on("console", lambda m: print(f"CONSOLE[{m.type}]: {m.text}"))
        page.on("request", lambda r: print(f"REQ: {r.method} {r.url}"))
        page.on("response", lambda r: print(f"RES: {r.status} {r.url}"))
        page.goto("http://127.0.0.1:7860", wait_until="domcontentloaded", timeout=30000)

        page.wait_for_selector("#chooseBtn", timeout=10000)
        print("chooseBtn visible")
        print("fileInput exists:", page.locator("#fileInput").count())
        page.set_input_files("#fileInput", str(SAMPLE))
        print("set_input_files done")

        page.wait_for_function(
            "() => { const w = document.getElementById('workspace'); return w && getComputedStyle(w).display !== 'none'; }",
            timeout=30000,
        )

        status = page.locator("#statusPersistent").inner_text(timeout=10000)
        chip = page.locator("#fileChip").inner_text(timeout=10000)

        assert chip and chip.strip() != "No file", f"Upload failed, file chip not updated: {chip!r}"
        assert status and status.strip(), "Status should not be empty after upload"

        print("PASS: local upload workflow is functioning.")
        print(f"Status: {status}")
        print(f"File chip: {chip}")
        browser.close()


if __name__ == "__main__":
    run_test()
