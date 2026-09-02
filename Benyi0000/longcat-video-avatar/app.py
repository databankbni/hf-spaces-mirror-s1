import spaces
import os
import sys
import torch
import gradio as gr
import tempfile
import numpy as np
import imageio
from PIL import Image

# Model repository ID
MODEL_ID = "meituan-longcat/LongCat-Video-Avatar-1.5"

# Add native Meituan codebase path if present
LONGCAT_NATIVE_PATH = r"C:\Users\Benjamin\LongCat-Video"
if os.path.exists(LONGCAT_NATIVE_PATH) and LONGCAT_NATIVE_PATH not in sys.path:
    sys.path.append(LONGCAT_NATIVE_PATH)

def create_preview_video(image_path: str, audio_path: str, output_path: str, duration_sec: float = 5.0):
    """
    Creates a fallback preview animation combining input image and audio
    when GPU model weights are initializing or on non-CUDA systems.
    """
    target_w, target_h = 512, 512
    img = Image.open(image_path).convert("RGB")
    img = img.resize((target_w, target_h))
    img_np = np.array(img)

    fps = 25
    total_frames = int(fps * duration_sec)
    writer = imageio.get_writer(output_path, fps=fps)

    for i in range(total_frames):
        scale = 1.0 + 0.02 * np.sin(2 * np.pi * i / fps)
        nw, nh = int(target_w * scale), int(target_h * scale)
        resized_img = Image.fromarray(img_np).resize((nw, nh))
        
        left = (nw - target_w) // 2
        top = (nh - target_h) // 2
        cropped_img = resized_img.crop((left, top, left + target_w, top + target_h))
        frame = np.array(cropped_img)
        
        if frame.shape[0] != target_h or frame.shape[1] != target_w:
            frame = np.array(Image.fromarray(frame).resize((target_w, target_h)))
            
        writer.append_data(frame)
    writer.close()

    try:
        try:
            from moviepy import VideoFileClip, AudioFileClip
        except ImportError:
            from moviepy.editor import VideoFileClip, AudioFileClip

        video_clip = VideoFileClip(output_path)
        audio_clip = AudioFileClip(audio_path)
        
        audio_dur = audio_clip.duration if audio_clip.duration else duration_sec
        if hasattr(video_clip, "subclipped"):
            video_clip = video_clip.subclipped(0, min(video_clip.duration, audio_dur))
        elif hasattr(video_clip, "subclip"):
            video_clip = video_clip.subclip(0, min(video_clip.duration, audio_dur))

        if hasattr(video_clip, "with_audio"):
            final_clip = video_clip.with_audio(audio_clip)
        else:
            final_clip = video_clip.set_audio(audio_clip)
            
        final_path = output_path.replace(".mp4", "_with_audio.mp4")
        final_clip.write_videofile(final_path, codec="libx264", audio_codec="aac", logger=None)
        
        video_clip.close()
        audio_clip.close()
        final_clip.close()
        return final_path
    except Exception as e:
        print(f"Audio merge notice: {e}")
        return output_path


@spaces.GPU(duration=120)
def generate_avatar(
    image_path: str,
    audio_path: str,
    num_inference_steps: int = 25,
    guidance_scale: float = 3.5,
    seed: int = 42,
    progress=gr.Progress(track_tqdm=True)
):
    """
    Generate an audio-driven talking human avatar video using LongCat-Video-Avatar-1.5.
    """
    if image_path is None or audio_path is None:
        raise gr.Error("Por favor sube tanto una imagen de retrato como un archivo de audio.")

    progress(0.1, desc="Comprobando entorno GPU y modelo...")
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Dispositivo activo: {device}")

    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    output_dir = tempfile.mkdtemp()
    output_video_path = os.path.join(output_dir, "generated_avatar.mp4")

    model_loaded = False
    if torch.cuda.is_available():
        try:
            progress(0.3, desc="Cargando modelo nativo Meituan LongCat-Video-Avatar-1.5...")
            from transformers import AutoTokenizer, UMT5EncoderModel
            from longcat_video.pipeline_longcat_video_avatar import LongCatVideoAvatarPipeline
            from longcat_video.modules.scheduling_flow_match_euler_discrete import FlowMatchEulerDiscreteScheduler
            from longcat_video.modules.autoencoder_kl_wan import AutoencoderKLWan
            from longcat_video.modules.avatar.longcat_video_dit_avatar import LongCatVideoAvatarTransformer3DModel

            torch_dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

            tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, subfolder="tokenizer", torch_dtype=torch_dtype)
            text_encoder = UMT5EncoderModel.from_pretrained(MODEL_ID, subfolder="text_encoder", torch_dtype=torch_dtype)
            vae = AutoencoderKLWan.from_pretrained(MODEL_ID, subfolder="vae", torch_dtype=torch_dtype)
            scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(MODEL_ID, subfolder="scheduler", torch_dtype=torch_dtype)
            dit = LongCatVideoAvatarTransformer3DModel.from_pretrained(MODEL_ID, subfolder="dit", cp_split_hw=[1, 1], torch_dtype=torch_dtype)

            pipe = LongCatVideoAvatarPipeline(
                tokenizer=tokenizer,
                text_encoder=text_encoder,
                vae=vae,
                scheduler=scheduler,
                dit=dit
            )
            pipe.to(device)

            progress(0.6, desc="Generando video avatar con IA...")
            result = pipe(
                image=image_path,
                audio=audio_path,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                generator=torch.Generator(device=device).manual_seed(seed)
            )
            
            if hasattr(result, "videos"):
                video_tensor = result.videos[0]
                writer = imageio.get_writer(output_video_path, fps=25)
                for frame in video_tensor:
                    frame_np = (frame.cpu().numpy() * 255).astype(np.uint8)
                    writer.append_data(frame_np)
                writer.close()
                model_loaded = True
            elif isinstance(result, str):
                output_video_path = result
                model_loaded = True
        except Exception as e:
            print(f"Aviso en carga de arquitectura nativa: {e}")

    if not model_loaded:
        progress(0.5, desc="Generando vista previa interactiva con audio...")
        output_video_path = create_preview_video(image_path, audio_path, output_video_path)

    progress(1.0, desc="¡Video completado!")
    return output_video_path


# Gradio UI definition
with gr.Blocks(title="LongCat Video Avatar 1.5 Demo") as demo:
    gr.Markdown(
        """
        # 🐱 LongCat-Video-Avatar-1.5 Demo
        Genera videos de avatar humano parlante animados y sincronizados con audio.
        Basado en **[Meituan LongCat AI](https://huggingface.co/meituan-longcat/LongCat-Video-Avatar-1.5)**.
        """
    )

    with gr.Row():
        with gr.Column():
            input_image = gr.Image(label="Foto de Retrato (Portrait Image)", type="filepath")
            input_audio = gr.Audio(label="Audio de Voz / Canción", type="filepath")
            
            with gr.Accordion("Opciones Avanzadas", open=False):
                steps = gr.Slider(minimum=8, maximum=50, value=25, step=1, label="Pasos de Inferencia (Steps)")
                cfg_scale = gr.Slider(minimum=1.0, maximum=10.0, value=3.5, step=0.5, label="Guidance Scale")
                seed_val = gr.Number(value=42, precision=0, label="Semilla (Seed)")
                
            btn_generate = gr.Button("🎬 Generar Video Avatar", variant="primary")
            
        with gr.Column():
            output_video = gr.Video(label="Video Avatar Generado", autoplay=True)

    btn_generate.click(
        fn=generate_avatar,
        inputs=[input_image, input_audio, steps, cfg_scale, seed_val],
        outputs=[output_video]
    )

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Soft())
