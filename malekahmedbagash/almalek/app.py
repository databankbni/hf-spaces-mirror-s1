import gradio as gr
import torch
from transformers import pipeline
from TTS.api import TTS
import os
import tempfile
import numpy as np
from PIL import Image
import imageio

# تحديد الجهاز (GPU إذا كان متاحاً)
device = "cuda" if torch.cuda.is_available() else "cpu"

# ==========================================
# 1. تحميل نموذج اللغة (خفيف وسريع)
# ==========================================
llm_pipe = pipeline(
    "text-generation", 
    model="Qwen/Qwen1.5-0.5B-Chat", 
    device_map="auto"
)

# ==========================================
# 2. تحميل نموذج الصوت (XTTS-v2)
# ==========================================
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

# ==========================================
# دالة المعالجة الرئيسية
# ==========================================
def digital_twin_interface(user_text, user_image, voice_sample):
    try:
        # أ. توليد النص
        prompt = f"User: {user_text}\nAssistant:"
        output = llm_pipe(prompt, max_new_tokens=100, do_sample=True, temperature=0.7)
        response_text = output[0]['generated_text'].split("Assistant:")[-1].strip()
        
        # ب. توليد الصوت (بصوتك)
        audio_path = os.path.join(tempfile.gettempdir(), "response.wav")
        tts.tts_to_file(
            text=response_text,
            speaker_wav=voice_sample,
            language="ar",
            file_path=audio_path
        )
        
        # ج. دمج الصورة مع الصوت في فيديو
        video_path = os.path.join(tempfile.gettempdir(), "talking_video.mp4")
        img = Image.open(user_image).resize((512, 512))
        frames = [np.array(img) for _ in range(15)]
        
        imageio.mimsave(video_path, frames, duration=0.5, fps=15, audio=audio_path, codec='libx264', audio_fps=44100, audio_codec='aac')
        
        return response_text, audio_path, video_path

    except Exception as e:
        return f"حدث خطأ أثناء المعالجة: {str(e)}", None, None

# ==========================================
# واجهة المستخدم
# ==========================================
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🌟 النسخة الرقمية الاحترافية")
    gr.Markdown("ارفع عينة من صوتك (10 ثوانٍ)، وصورة وجهك، ثم اكتب لي وسأرد عليك بصوتك!")
    
    with gr.Row():
        with gr.Column(scale=1):
            voice_input = gr.Audio(type="filepath", label="🎙️ ارفع عينة صوتك")
            image_input = gr.Image(type="filepath", label="🖼️ ارفع صورتك الشخصية")
            text_input = gr.Textbox(label="💬 اكتب رسالتك هنا")
            submit_btn = gr.Button("🚀 تفاعل", variant="primary")
            
        with gr.Column(scale=1):
            text_output = gr.Textbox(label="🧠 الرد النصي")
            audio_output = gr.Audio(label="🔊 الرد الصوتي")
            video_output = gr.Video(label="🎥 الفيديو المتحرك")
    
    submit_btn.click(
        fn=digital_twin_interface,
        inputs=[text_input, image_input, voice_input],
        outputs=[text_output, audio_output, video_output]
    )

if __name__ == "__main__":
    demo.launch()