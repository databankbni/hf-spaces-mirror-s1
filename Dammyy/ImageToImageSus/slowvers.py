import os
import random
import tempfile
from typing import Any, List, Optional, Tuple

import gradio as gr
import numpy as np
from PIL import Image
from gradio_client import Client, handle_file

SPACE_ID = "hemil124/virtual-tryon"
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()

MAX_SEED = 2147483647


def make_client() -> Client:
    params = Client.__init__.__code__.co_varnames
    if HF_TOKEN:
        try:
            if "token" in params:
                return Client(SPACE_ID, token=HF_TOKEN)
            if "hf_token" in params:
                return Client(SPACE_ID, hf_token=HF_TOKEN)
        except TypeError:
            pass
    return Client(SPACE_ID)


client = make_client()


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def save_image(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Image.Image):
        img = value.convert("RGBA") if value.mode not in ("RGB", "RGBA") else value
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        path = tmp.name
        tmp.close()
        img.save(path)
        return path
    try:
        img = Image.fromarray(np.array(value))
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        path = tmp.name
        tmp.close()
        img.save(path)
        return path
    except Exception:
        return None


def cleanup(paths: List[str]) -> None:
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass


def to_pil(value: Any) -> Optional[Image.Image]:
    if value is None:
        return None
    if isinstance(value, Image.Image):
        return value
    if isinstance(value, str) and os.path.exists(value):
        try:
            return Image.open(value)
        except Exception:
            return None
    if isinstance(value, np.ndarray):
        try:
            return Image.fromarray(value)
        except Exception:
            return None
    if isinstance(value, (list, tuple)) and len(value) > 0:
        for item in value:
            img = to_pil(item)
            if img is not None:
                return img
    if isinstance(value, dict):
        for key in ("image", "result", "output", "data", "value"):
            if key in value:
                img = to_pil(value[key])
                if img is not None:
                    return img
    return None


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("status", "message", "text", "info", "caption", "response"):
            if key in value and isinstance(value[key], str):
                return value[key]
    if isinstance(value, (list, tuple)):
        for item in value:
            text = extract_text(item)
            if text:
                return text
    return ""


def normalize_response(result: Any) -> Tuple[Optional[Image.Image], str]:
    image = to_pil(result)
    text = extract_text(result)
    if image is not None and not text:
        text = "Success"
    return image, text


def try_remote_call(args: Tuple[Any, ...]) -> Any:
    api_names = ["/tryon", "/predict", None]
    last_error = None

    for api_name in api_names:
        try:
            if api_name is None:
                return client.predict(*args)
            return client.predict(*args, api_name=api_name)
        except Exception as e:
            last_error = e

    raise last_error if last_error else RuntimeError("Remote call failed")


def try_on(person_image, garment_image, garment_category, sampling_steps, seed, randomize_seed):
    if person_image is None:
        raise gr.Error("Please upload a person image.")
    if garment_image is None:
        raise gr.Error("Please upload a garment image.")

    steps_value = safe_int(sampling_steps, 20)
    seed_value = safe_int(seed, 42)
    if randomize_seed:
        seed_value = random.randint(0, MAX_SEED)

    person_path = save_image(person_image)
    garment_path = save_image(garment_image)

    if not person_path or not garment_path:
        cleanup([p for p in [person_path, garment_path] if p])
        raise gr.Error("Could not read one of the images.")

    temp_files = [person_path, garment_path]

    try:
        person_file = handle_file(person_path)
        garment_file = handle_file(garment_path)

        arg_variants = [
            (person_file, garment_file, garment_category, steps_value, seed_value, randomize_seed),
            (person_file, garment_file, garment_category, steps_value, seed_value),
            (person_file, garment_file, steps_value, seed_value, randomize_seed),
            (person_file, garment_file, steps_value, seed_value),
            (person_file, garment_file, garment_category),
            (person_file, garment_file),
        ]

        last_error = None
        for args in arg_variants:
            try:
                result = try_remote_call(args)
                image, text = normalize_response(result)
                if image is None and not text:
                    raise gr.Error("Unexpected response from the remote Space.")
                return image, text or "Success"
            except Exception as e:
                last_error = e

        raise gr.Error(f"Remote Space error: {last_error}")
    finally:
        cleanup(temp_files)


with gr.Blocks(title="CPU Basic Virtual Try-On") as demo:
    gr.Markdown("# CPU Basic Virtual Try-On")

    with gr.Row():
        with gr.Column(scale=1):
            person = gr.Image(type="pil", label="Person Image", sources=["upload"])
            garment = gr.Image(type="pil", label="Garment Image", sources=["upload"])
            garment_category = gr.Dropdown(
                label="Garment Category",
                choices=["upper_body", "lower_body", "dresses"],
                value="upper_body",
            )
            sampling_steps = gr.Slider(
                label="Sampling Steps",
                minimum=1,
                maximum=50,
                value=20,
                step=1,
            )
            seed = gr.Number(label="Seed", value=42, precision=0)
            randomize_seed = gr.Checkbox(label="Randomize Seed", value=True)
            run_btn = gr.Button("Try On")

        with gr.Column(scale=1):
            output_image = gr.Image(label="Result", type="pil")
            status = gr.Textbox(label="Status", value="", interactive=False)

    run_btn.click(
        fn=try_on,
        inputs=[person, garment, garment_category, sampling_steps, seed, randomize_seed],
        outputs=[output_image, status],
    )

demo.queue()
demo.launch()