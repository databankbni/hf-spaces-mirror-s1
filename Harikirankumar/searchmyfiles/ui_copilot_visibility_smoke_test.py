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

        page.wait_for_selector("#copilotBtn", timeout=10000)
        page.wait_for_selector("#copilotToggleBtn", timeout=10000)
        page.wait_for_selector("#copilotPanel", timeout=10000)

        page.click("#copilotBtn")
        page.wait_for_timeout(300)

        panel_classes = page.eval_on_selector("#copilotPanel", "el => el.className")
        assert "open" in panel_classes, f"Copilot panel did not open. classes={panel_classes!r}"
        assert not page_errors, f"Unexpected JS errors: {page_errors!r}"

        print("PASS: Copilot UI is visible and opens from toolbar button.")
        browser.close()


if __name__ == "__main__":
    run_test()
