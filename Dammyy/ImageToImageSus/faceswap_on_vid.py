import gradio as gr
import cv2
import insightface
from insightface.app import FaceAnalysis
import numpy as np
import os
from PIL import Image
from huggingface_hub import hf_hub_download
import tempfile
import shutil
import subprocess

def download_inswapper():
    model_dir = os.path.expanduser('~/.insightface/models')
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, 'inswapper_128.onnx')
    if not os.path.exists(model_path):
        hf_hub_download(repo_id="ezioruan/inswapper_128.onnx", filename="inswapper_128.onnx", local_dir=model_dir, local_dir_use_symlinks=False)
    return model_path

model_path = download_inswapper()

app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))

swapper = insightface.model_zoo.get_model(model_path, providers=['CPUExecutionProvider'])

def is_gif(file_path):
    return str(file_path).lower().endswith('.gif')

def has_audio(video_path):
    try:
        result = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json', 
                               '-show_streams', video_path], 
                              capture_output=True, text=True)
        return 'audio' in result.stdout.lower()
    except:
        return False

def process_media(media_path, face_image, swap_mode, progress=gr.Progress()):
    if media_path is None or face_image is None:
        return None, None, "Please upload both media and face image"

    face_img = cv2.cvtColor(np.array(face_image), cv2.COLOR_RGB2BGR)
    face_faces = app.get(face_img)
    if len(face_faces) == 0:
        return None, None, "No face detected in source face image"

    source_face = face_faces[0]
    is_gif_file = is_gif(media_path)
    is_image = not str(media_path).lower().endswith(('.mp4', '.mov', '.avi', '.webm', '.gif'))

    if is_image:
        main_img = cv2.cvtColor(np.array(Image.open(media_path)), cv2.COLOR_RGB2BGR)
        faces = app.get(main_img)
        if len(faces) == 0:
            return None, None, "No face detected in main image"
        
        result = swapper.get(main_img, faces[0], source_face, paste_back=True)
        result_pil = Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))
        return None, result_pil, f"✅ Image completed ({swap_mode})"

    # Video / GIF
    cap = cv2.VideoCapture(media_path)
    fps = cap.get(cv2.CAP_PROP_FPS) if not is_gif_file else 15.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    processed_frames = []
    temp_no_audio = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4').name

    progress(0, desc="Processing...")

    for i in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            break

        faces = app.get(frame)
        if len(faces) > 0:
            frame = swapper.get(frame, faces[0], source_face, paste_back=True)

        processed_frames.append(frame)
        progress((i + 1) / total_frames)

    cap.release()

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_no_audio, fourcc, fps, (width, height))
    for f in processed_frames:
        out.write(f)
    out.release()

    final_output = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4').name

    if has_audio(media_path):
        try:
            subprocess.run(['ffmpeg', '-y', '-i', temp_no_audio, '-i', media_path,
                            '-c:v', 'libx264', '-c:a', 'aac', '-map', '0:v:0', '-map', '1:a:0?',
                            '-shortest', final_output], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except:
            shutil.copy(temp_no_audio, final_output)
    else:
        shutil.copy(temp_no_audio, final_output)

    try:
        os.remove(temp_no_audio)
    except:
        pass

    preview_img = Image.fromarray(cv2.cvtColor(processed_frames[0], cv2.COLOR_BGR2RGB))

    return final_output, preview_img, f"✅ Done! {total_frames} frames ({swap_mode})"

with gr.Blocks(title="Face Swap Tool", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# Face & Hair Swap Tool")
    gr.Markdown("**Note:** `inswapper` is good for **Face Only**. Hair transfer needs different models (HairFastGAN / Stable-Hair).")

    with gr.Row():
        with gr.Column():
            media_input = gr.File(label="Upload Image / Video / GIF", file_types=["image", "video"], height=400)
            face_input = gr.Image(label="Source Face Image", type="pil", height=400)
            swap_mode = gr.Dropdown(
                choices=["Face Only", "Hair Only (Limited)", "Both (Face + Hair)"], 
                value="Face Only", 
                label="Swap Mode"
            )
        
        with gr.Column():
            output_media = gr.Video(label="Output Video", height=400)
            output_image = gr.Image(label="Result / Preview", height=400)

    btn = gr.Button("🚀 Start Swap", variant="primary", size="large")
    status = gr.Textbox(label="Status", interactive=False)

    btn.click(
        fn=process_media,
        inputs=[media_input, face_input, swap_mode],
        outputs=[output_media, output_image, status]
    )

    gr.Markdown("**Hair mode is currently limited** because we are using inswapper. For real hair transfer, we need HairFastGAN or Stable-Hair.")

demo.launch()