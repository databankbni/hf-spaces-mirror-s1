import os
import wave
import tempfile
from pathlib import Path
import gradio as gr
from piper.voice import PiperVoice

# Nạp mô hình Ngọc Huyền vào RAM 1 lần duy nhất khi khởi chạy server
model_path = Path("ngoc_huyen.onnx")
if not model_path.exists():
    raise FileNotFoundError("Không tìm thấy file ngoc_huyen.onnx trong thư mục!")

print("Đang nạp mô hình Ngọc Huyền...")
voice = PiperVoice.load(str(model_path))
print("Nạp mô hình thành công!")

import inspect
try:
    print("DEBUG - voice.synthesize_wav signature:", inspect.signature(voice.synthesize_wav))
except Exception as e:
    print("DEBUG - Failed to get signature:", e)

from piper.config import SynthesisConfig

def thuyet_minh(text, speed):
    # Piper sử dụng length_scale (tỉ lệ nghịch với tốc độ đọc)
    length_scale = 1.0 / speed if speed > 0 else 1.0
    
    # Khởi tạo config của Piper
    syn_config = SynthesisConfig(length_scale=length_scale)
    
    # Tạo tệp âm thanh tạm thời dạng .wav
    temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_file.close()
    
    # Thực hiện thuyết minh trực tiếp từ RAM ra file tạm bằng đối tượng config
    with wave.open(temp_file.name, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file, syn_config=syn_config)
        
    return temp_file.name

# Thiết lập giao diện Web Gradio
demo = gr.Interface(
    fn=thuyet_minh,
    inputs=[
        gr.Textbox(label="Nhập văn bản cần thuyết minh", placeholder="Ví dụ: Xin chào các bạn..."),
        gr.Slider(minimum=0.5, maximum=2.5, value=1.6, step=0.1, label="Tốc độ giọng đọc")
    ],
    outputs=gr.Audio(label="Kết quả giọng đọc Ngọc Huyền", type="filepath"),
    title="Ngọc Huyền TTS Server (Piper)",
    description="Giao diện Web và API thuyết minh giọng Ngọc Huyền chạy hoàn toàn miễn phí trên Hugging Face."
)

if __name__ == "__main__":
    demo.launch()
