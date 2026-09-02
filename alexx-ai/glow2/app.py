# pip install gradio requests

import os
import time
import threading
import requests
import gradio as gr
from concurrent.futures import ThreadPoolExecutor
import json


API_URL = "https://app.scrapingbee.com/api/v1"

JS_SCENARIO = {
    "strict": False,
    "instructions": [
        {"wait": 8000},

        {"click": "h2"},
        {"click": ".ub-button-container"},

        {"wait": 1000},

        {
            "evaluate": """
                const host = document.querySelector('div[doskip="1"][prclck="1"]');
                const modal = host?.shadowRoot?.querySelector('#modal');
                const buttonContainer = modal?.querySelector('#buttonContainer');
                const goToButton = buttonContainer?.querySelector('#goToButton');

                if (goToButton) {
                    goToButton.click();
                } else {
                    console.log("goToButton not found");
                }
            """
        },

        {
            "evaluate": """
                const x = Math.floor(window.innerWidth / 2);
                const y = Math.floor(window.innerHeight / 2);
                const target = document.elementFromPoint(x, y);

                if (target) {
                    target.dispatchEvent(new MouseEvent("mousemove", {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y
                    }));

                    target.dispatchEvent(new MouseEvent("mousedown", {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y,
                        button: 0,
                        buttons: 1
                    }));

                    target.dispatchEvent(new MouseEvent("mouseup", {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y,
                        button: 0
                    }));

                    target.dispatchEvent(new MouseEvent("click", {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        clientX: x,
                        clientY: y,
                        button: 0
                    }));
                } else {
                    console.log("No element found at viewport center");
                }
            """
        },

        {"click": "h2"},
        {"click": ".ub-button-container"},

        {"wait": 1000},

        {"click": "a"},
        {"click": "#goToButton"},

        {"wait": 10000},

        {"click": "#button_id121"},
        {"wait": 9000},
        {"wait": 19000},

        {"click": "#button_id1"},
        {"wait": 9000},
        {"wait": 19000},

        {"click": "#nices"}
    ]
}

PARAMS = {
    "url": "https://biturl.in/Home/Index/7514A4B9",
    "premium_proxy": "true",
    "country_code": "us",
    "js_scenario": json.dumps(JS_SCENARIO),
    "wait": "4000",
    "block_resources": "false",
    "screenshot": "true",
    "json_response": "true",
}

# Put your NEW key in an environment variable:
# Windows:
#   set SCRAPINGBEE_API_KEY=your_key
#
# Linux/macOS:
#   export SCRAPINGBEE_API_KEY=your_key

API_KEY = "LGZR9RF9UI0Q6YNSPKH13GMCIY0LAS4UHRBUHQ1KJHJN99OLT2IF7V0JUYGC304S7GXX2IYJ253F7XSO"


# ---------------------------------------------------------
# Global state
# ---------------------------------------------------------

stop_event = threading.Event()
worker_thread = None

state_lock = threading.Lock()

logs = []
current_batch = 0
completed_requests = 0
total_requests = 0
running = False


def add_log(message):
    """Thread-safe logging."""
    global logs

    timestamp = time.strftime("%H:%M:%S")

    with state_lock:
        logs.append(f"[{timestamp}] {message}")

        # Keep only the latest 500 lines
        logs = logs[-500:]


# ---------------------------------------------------------
# ScrapingBee request
# ---------------------------------------------------------

def send_request(request_id, batch_number):
    global completed_requests

    if stop_event.is_set():
        return

    try:
        add_log(
            f"Batch {batch_number} - "
            f"Request {request_id}: starting..."
        )

        response = requests.get(
            API_URL,
            params=PARAMS,
            headers={
                "authorization": f"Bearer {API_KEY}"
            },
            timeout=180,
        )

        with state_lock:
            completed_requests += 1

        add_log(
            f"Batch {batch_number} - "
            f"Request {request_id}: "
            f"Status={response.status_code}, "
            f"Size={len(response.content)} bytes"
        )

    except Exception as e:

        with state_lock:
            completed_requests += 1

        add_log(
            f"Batch {batch_number} - "
            f"Request {request_id}: ERROR - {e}"
        )


# ---------------------------------------------------------
# One batch
# ---------------------------------------------------------

def run_batch(batch_number):
    global completed_requests

    with state_lock:
        completed_requests = 0

    add_log(f"========== Batch {batch_number} ==========")

    with ThreadPoolExecutor(max_workers=5) as executor:

        futures = [
            executor.submit(
                send_request,
                request_id,
                batch_number
            )
            for request_id in range(1, 6)
        ]

        # Wait for all 5 requests
        for future in futures:
            try:
                future.result()
            except Exception as e:
                add_log(f"Worker error: {e}")

            if stop_event.is_set():
                break

    add_log(f"Batch {batch_number} completed.")


# ---------------------------------------------------------
# Background worker
# ---------------------------------------------------------

def background_worker():
    global current_batch
    global running

    batch = 1

    try:
        while not stop_event.is_set():

            with state_lock:
                current_batch = batch

            run_batch(batch)

            if stop_event.is_set():
                break

            add_log("Waiting 10 seconds before next batch...")

            # This is better than time.sleep(10)
            # because Stop can interrupt the wait.
            if stop_event.wait(10):
                break

            batch += 1

    except Exception as e:
        add_log(f"BACKGROUND WORKER ERROR: {e}")

    finally:
        with state_lock:
            running = False

        add_log("Worker stopped.")


# ---------------------------------------------------------
# Start
# ---------------------------------------------------------

def start_worker():
    global worker_thread
    global running
    global logs
    global completed_requests
    global current_batch

    if not API_KEY:
        return (
            "ERROR: SCRAPINGBEE_API_KEY environment variable is not set.",
            gr.update(interactive=True),
            gr.update(interactive=False),
        )

    with state_lock:
        if running:
            return (
                "Already running.",
                gr.update(interactive=False),
                gr.update(interactive=True),
            )

        logs = []
        completed_requests = 0
        current_batch = 0
        running = True

    stop_event.clear()

    add_log("Starting background worker...")

    worker_thread = threading.Thread(
        target=background_worker,
        daemon=True,
    )

    worker_thread.start()

    return (
        "Started.",
        gr.update(interactive=False),
        gr.update(interactive=True),
    )


# ---------------------------------------------------------
# Stop
# ---------------------------------------------------------

def stop_worker():
    if not running:
        return (
            "Worker is not running.",
            gr.update(interactive=True),
            gr.update(interactive=False),
        )

    add_log("Stopping worker...")

    stop_event.set()

    return (
        "Stop requested.",
        gr.update(interactive=True),
        gr.update(interactive=False),
    )


# ---------------------------------------------------------
# UI update
# ---------------------------------------------------------

def update_ui():
    with state_lock:
        is_running = running
        batch = current_batch
        completed = completed_requests
        log_text = "\n".join(logs)

    if is_running:
        status = (
            f"🟢 Running\n\n"
            f"Batch: {batch}\n"
            f"Requests completed: {completed}/5"
        )
    else:
        status = "🔴 Stopped"

    return status, log_text


# ---------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------

with gr.Blocks(title="ScrapingBee Batch Runner") as demo:

    gr.Markdown(
        """
        # ScrapingBee Batch Runner

        Runs **5 requests concurrently per batch** in the background.
        After each batch, waits **10 seconds** and starts the next batch.
        """
    )

    with gr.Row():

        start_button = gr.Button(
            "▶ Start",
            variant="primary",
        )

        stop_button = gr.Button(
            "■ Stop",
            variant="stop",
            interactive=False,
        )

    status = gr.Markdown(
        "🔴 Stopped"
    )

    log_output = gr.Textbox(
        label="Live Logs",
        lines=25,
        max_lines=40,
        autoscroll=True,
    )

    # Start button
    start_button.click(
        fn=start_worker,
        inputs=[],
        outputs=[
            status,
            start_button,
            stop_button,
        ],
    )

    # Stop button
    stop_button.click(
        fn=stop_worker,
        inputs=[],
        outputs=[
            status,
            start_button,
            stop_button,
        ],
    )

    # Poll every second for updated logs/status
    timer = gr.Timer(1)

    timer.tick(
        fn=update_ui,
        inputs=[],
        outputs=[
            status,
            log_output,
        ],
    )


if __name__ == "__main__":
    demo.launch()