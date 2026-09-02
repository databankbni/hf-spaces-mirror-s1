import os
import time
import random
import tempfile
import inspect
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr
from PIL import Image
from gradio_client import Client, handle_file

SPACE_ID = "yisol/IDM-VTON"
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()

def make_client():
    params = inspect.signature(Client).parameters
    if HF_TOKEN:
        if "token" in params:
            try:
                return Client(SPACE_ID, token=HF_TOKEN)
            except TypeError:
                pass
        if "hf_token" in params:
            try:
                return Client(SPACE_ID, hf_token=HF_TOKEN)
            except TypeError:
                pass
    return Client(SPACE_ID)

client = make_client()

def save_image(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Image.Image):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        path = tmp.name
        tmp.close()
        img = value.convert("RGBA") if value.mode not in ("RGB", "RGBA") else value
        img.save(path)
        return path
    try:
        img = Image.fromarray(value)
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

def build_editor_payload(editor_value: Any) -> Tuple[Dict[str, Any], List[str]]:
    payload = {"background": None, "layers": [], "composite": None}
    files: List[str] = []

    if not editor_value:
        return payload, files

    if isinstance(editor_value, dict):
        background = editor_value.get("background")
        layers = editor_value.get("layers") or []
        composite = editor_value.get("composite")
    else:
        background = editor_value
        layers = []
        composite = None

    bg_path = save_image(background)
    if bg_path:
        payload["background"] = handle_file(bg_path)
        files.append(bg_path)

    for layer in layers:
        layer_path = save_image(layer)
        if layer_path:
            payload["layers"].append(handle_file(layer_path))
            files.append(layer_path)

    comp_path = save_image(composite)
    if comp_path:
        payload["composite"] = handle_file(comp_path)
        files.append(comp_path)

    return payload, files

def call_remote(editor_payload, garment_path, garment_description, use_auto_mask, use_auto_crop, denoise_steps, seed_value):
    return client.predict(
        editor_payload,
        handle_file(garment_path),
        garment_description,
        bool(use_auto_mask),
        bool(use_auto_crop),
        int(denoise_steps),
        int(seed_value),
        api_name="/tryon",
    )

def try_on(editor_value, garment_image, garment_description, use_auto_mask, use_auto_crop, denoise_steps, seed):
    if garment_image is None:
        raise gr.Error("Please upload a garment image.")

    garment_description = str(garment_description).strip() if garment_description else "garment"

    try:
        seed_value = int(seed)
    except Exception:
        seed_value = 42

    try:
        steps_value = int(denoise_steps)
    except Exception:
        steps_value = 30

    editor_payload, temp_files = build_editor_payload(editor_value)
    garment_path = save_image(garment_image)

    if not garment_path:
        cleanup(temp_files)
        raise gr.Error("Could not read the garment image.")

    temp_files.append(garment_path)

    max_retries = 5
    last_error = None

    try:
        for attempt in range(max_retries):
            try:
                result = call_remote(
                    editor_payload,
                    garment_path,
                    garment_description,
                    use_auto_mask,
                    use_auto_crop,
                    steps_value,
                    seed_value,
                )
                if isinstance(result, (list, tuple)) and len(result) >= 2:
                    return result[0], result[1]
                raise gr.Error("Unexpected response from the remote Space.")
            except Exception as e:
                last_error = e
                message = str(e)
                if "429" in message or "Too Many Requests" in message:
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt + random.random())
                        continue
                raise gr.Error(f"Remote Space error: {message}")
    finally:
        cleanup(temp_files)

    raise gr.Error(f"Remote Space error: {last_error}")

with gr.Blocks(title="IDM-VTON Remote Wrapper") as demo:
    gr.Markdown("# IDM-VTON Remote Wrapper")

    with gr.Row():
        with gr.Column(scale=1):
            person = gr.ImageEditor(
                sources=["upload"],
                type="pil",
                label="Human. Mask with pen or use auto-masking",
                interactive=True,
            )
            garment = gr.Image(
                type="pil",
                label="Garment",
                sources=["upload"],
            )
            garment_description = gr.Textbox(
                label="Garment Description",
                value="Short Sleeve Round Neck T-shirt",
                placeholder="Short Sleeve Round Neck T-shirt",
            )
            use_auto_mask = gr.Checkbox(label="Use auto-generated mask", value=True)
            use_auto_crop = gr.Checkbox(label="Use auto-crop & resizing", value=False)
            denoise_steps = gr.Number(label="Denoising Steps", value=30, precision=0, minimum=20, maximum=40)
            seed = gr.Number(label="Seed", value=42, precision=0, minimum=-1, maximum=2147483647)
            run_btn = gr.Button("Try-on")

        with gr.Column(scale=1):
            output_image = gr.Image(label="Output", type="pil")
            masked_image = gr.Image(label="Masked image output", type="pil")

    run_btn.click(
        fn=try_on,
        inputs=[
            person,
            garment,
            garment_description,
            use_auto_mask,
            use_auto_crop,
            denoise_steps,
            seed,
        ],
        outputs=[output_image, masked_image],
    )

demo.queue()
demo.launch()