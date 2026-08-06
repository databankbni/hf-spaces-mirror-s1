from playwright.sync_api import sync_playwright


def run_test() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page_errors = []

        def on_page_error(err):
            page_errors.append(str(err))
            print(f"PAGEERROR: {err}")

        page.on("pageerror", on_page_error)
        page.goto("http://127.0.0.1:7860", wait_until="domcontentloaded", timeout=30000)

        page.wait_for_selector("#takePhotoBtn", timeout=10000)
        page.click("#takePhotoBtn")
        page.wait_for_timeout(800)

        modal_display = page.eval_on_selector("#cameraModal", "el => getComputedStyle(el).display")
        assert modal_display != "none", f"Camera modal did not open. display={modal_display!r}"
        assert not page_errors, f"Unexpected page errors after clicking Take Photo: {page_errors!r}"

        print("PASS: take photo button opens camera modal without JS runtime errors.")
        browser.close()


if __name__ == "__main__":
    run_test()
