"""
Instruction-based Image-to-Image editor for Hugging Face Spaces (CPU only).

Model: timbrooks/instruct-pix2pix
Why this model: unlike generic img2img (which just restyles an image toward a
descriptive prompt), InstructPix2Pix is trained specifically to follow an
*instruction* ("change the clothes to professional", "make it winter", etc.)
while preserving the rest of the image. It's built on SD1.5, which is the
lightest diffusion backbone that still gives good instruction-following
quality, making it the most practical choice for CPU-only inference.

CPU performance notes:
- No GPU is used or required (torch_dtype=float32, device="cpu").
- Default image size is capped at 512px and steps at 15 to keep inference
  time reasonable (roughly 1-3 minutes per image on a typical CPU Space).
- Attention slicing + VAE slicing are enabled to reduce peak memory, which
  also helps avoid OOM kills on small CPU Spaces (e.g. the free 2vCPU tier).
"""

import gradio as gr
import torch
from PIL import Image
from diffusers import StableDiffusionInstructPix2PixPipeline, EulerAncestralDiscreteScheduler

MODEL_ID = "timbrooks/instruct-pix2pix"
MAX_SIDE = 512  # cap image size for CPU speed

print("Loading model (this happens once at startup)...")
pipe = StableDiffusionInstructPix2PixPipeline.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.float32,   # CPU does not support float16
    safety_checker=None,
)
pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
pipe.to("cpu")
pipe.enable_attention_slicing()
try:
    pipe.enable_vae_slicing()
except Exception:
    pass
print("Model loaded. Ready.")


def resize_for_speed(img: Image.Image, max_side: int = MAX_SIDE) -> Image.Image:
    img = img.convert("RGB")
    w, h = img.size
    scale = max_side / max(w, h)
    if scale < 1:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    # dimensions must be multiples of 8 for the VAE
    w, h = img.size
    w -= w % 8
    h -= h % 8
    return img.resize((w, h), Image.LANCZOS)


def edit_image(
    input_image: Image.Image,
    prompt: str,
    steps: int,
    text_guidance: float,
    image_guidance: float,
    seed: int,
):
    if input_image is None:
        raise gr.Error("Please upload an image first.")
    if not prompt or not prompt.strip():
        raise gr.Error("Please enter an instruction prompt.")

    image = resize_for_speed(input_image)
    generator = torch.manual_seed(int(seed)) if seed is not None else None

    result = pipe(
        prompt=prompt.strip(),
        image=image,
        num_inference_steps=int(steps),
        guidance_scale=float(text_guidance),
        image_guidance_scale=float(image_guidance),
        generator=generator,
    )
    return result.images[0]


DEFAULT_PROMPT = "Change the clothes to professional"

with gr.Blocks(title="Instruction Image Editor (CPU)") as demo:
    gr.Markdown(
        """
        # 🖼️ Instruction-Based Image Editor (CPU only)
        Upload an image and describe the change as an instruction
        (e.g. *"Change the clothes to professional"*).
        Powered by **InstructPix2Pix**, running on CPU — no GPU required.

        ⏱️ Expect roughly **1-3 minutes** per generation on CPU.
        """
    )

    with gr.Row():
        with gr.Column():
            input_image = gr.Image(type="pil", label="Input Image")
            prompt = gr.Textbox(
                label="Instruction Prompt",
                value=DEFAULT_PROMPT,
                placeholder="e.g. Change the clothes to professional",
            )
            with gr.Accordion("Advanced settings", open=False):
                steps = gr.Slider(5, 30, value=15, step=1, label="Inference Steps (fewer = faster)")
                text_guidance = gr.Slider(1.0, 15.0, value=7.5, step=0.5, label="Text Guidance Scale")
                image_guidance = gr.Slider(1.0, 3.0, value=1.5, step=0.1, label="Image Guidance Scale (higher = closer to original)")
                seed = gr.Slider(0, 2**31 - 1, value=42, step=1, label="Seed")
            run_btn = gr.Button("Generate", variant="primary")
        with gr.Column():
            output_image = gr.Image(type="pil", label="Result")

    run_btn.click(
        fn=edit_image,
        inputs=[input_image, prompt, steps, text_guidance, image_guidance, seed],
        outputs=output_image,
        api_name="edit_image",
    )

    gr.Examples(
        examples=[
            ["Change the clothes to professional"],
            ["Turn the background into a beach at sunset"],
            ["Make it look like a black and white photo"],
        ],
        inputs=[prompt],
    )

if __name__ == "__main__":
    demo.queue(max_size=10).launch(show_api=False)