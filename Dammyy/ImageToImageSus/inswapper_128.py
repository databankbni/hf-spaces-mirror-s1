import gradio as gr
import cv2
import insightface
from insightface.app import FaceAnalysis
import numpy as np
import os
from PIL import Image
from huggingface_hub import hf_hub_download

# Download inswapper model
def download_inswapper():
    model_dir = os.path.expanduser('~/.insightface/models')
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, 'inswapper_128.onnx')
    
    if not os.path.exists(model_path):
        print("Downloading inswapper_128.onnx...")
        hf_hub_download(
            repo_id="ezioruan/inswapper_128.onnx",
            filename="inswapper_128.onnx",
            local_dir=model_dir,
            local_dir_use_symlinks=False
        )
        print("Download complete.")
    return model_path

model_path = download_inswapper()

# Initialize models
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640, 640))

swapper = insightface.model_zoo.get_model(model_path, providers=['CPUExecutionProvider'])

def face_swap(main_image, face_image):
    if main_image is None or face_image is None:
        return None, "Please upload both images"

    main_img = cv2.cvtColor(np.array(main_image), cv2.COLOR_RGB2BGR)
    face_img = cv2.cvtColor(np.array(face_image), cv2.COLOR_RGB2BGR)
    
    main_faces = app.get(main_img)
    face_faces = app.get(face_img)
    
    if len(main_faces) == 0 or len(face_faces) == 0:
        return None, "No face detected in one or both images. Please use clearer front-facing photos."
    
    source_face = face_faces[0]
    target_face = main_faces[0]
    
    result = swapper.get(main_img, target_face, source_face, paste_back=True)
    
    result_pil = Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))
    
    return result_pil, "✅ Face swap completed successfully!"

# Gradio UI
with gr.Blocks(title="Face Swap", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🖼️ Face Swap (Deepfake Style)")
    gr.Markdown("**Main Photo** = body/target | **Face Photo** = source face")
    
    with gr.Row():
        with gr.Column():
            main_input = gr.Image(label="Main Photo (Target)", type="pil", height=400)
        with gr.Column():
            face_input = gr.Image(label="Face Photo (Source)", type="pil", height=400)
    
    btn = gr.Button("🚀 Perform Face Swap", variant="primary", size="large")
    
    output_image = gr.Image(label="Result", height=550)
    status = gr.Textbox(label="Status", interactive=False)
    
    btn.click(
        fn=face_swap,
        inputs=[main_input, face_input],
        outputs=[output_image, status]
    )

    gr.Markdown("**Tips:** Use well-lit, front-facing photos for best results.")

demo.launch()