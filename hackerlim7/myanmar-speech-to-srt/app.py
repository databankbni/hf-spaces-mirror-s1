import gradio as gr
import edge_tts
import asyncio
import os

# အသံစာရင်း (Search လုပ်နိုင်ရန်အတွက် စနစ်တကျ ပြင်ဆင်ထားသည်)
VOICE_OPTIONS = {
    "သီဟ (အမျိုးသား - ပုံမှန်)": "my-MM-TunTunNeural",
    "နီလာ (အမျိုးသမီး - ပုံမှန်)": "my-MM-NilarNeural",
    "မောင်မောင် (လူငယ်သံစဉ်)": "en-US-ChristopherNeural",
    "ကြည်ဖြူ (ချိုသာသံစဉ်)": "en-US-JennyNeural",
    "ဖိုးသက် (ကလေးသံစဉ်)": "en-US-AnaNeural",
    "ဦးမင်းဟန် (အဘိုးအိုသံစဉ်)": "en-US-GuyNeural",
    "ဇာတ်လမ်းပြောသူ (Storyteller)": "en-GB-RyanNeural"
}

# အသံဖိုင်နှင့် SRT ဖိုင် ထုတ်ပေးသည့် Function
def generate_audio(text, voice_name, filename):
    voice = VOICE_OPTIONS[voice_name]
    audio_path = f"{filename}.mp3"
    srt_path = f"{filename}.srt"
    
    # Async လုပ်ဆောင်ချက်များကို ဤနေရာတွင် စနစ်တကျ Run သည်
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(edge_tts.Communicate(text, voice).save(audio_path))
    loop.close()
    
    # SRT ဖိုင် ဖန်တီးခြင်း
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,000 --> 00:00:10,000\n" + text)
        
    return audio_path, srt_path

# UI အသုံးပြုသူမျက်နှာပြင် ဒီဇိုင်း
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🎙️ Myanmar Audio & SRT Studio")
    
    with gr.Column():
        filename = gr.Textbox(label="သိမ်းဆည်းမည့် ဖိုင်အမည်", value="My_Audio")
        
        # Search လုပ်နိုင်သော Dropdown
        voice_dropdown = gr.Dropdown(
            choices=list(VOICE_OPTIONS.keys()), 
            label="အသံ ရွေးချယ်ရန် (အမည်ရိုက်၍ ရှာနိုင်သည်)", 
            value="သီဟ (အမျိုးသား - ပုံမှန်)",
            filterable=True
        )
        
        text_input = gr.Textbox(label="စာသားရိုက်ထည့်ရန်", lines=10)
        
        btn = gr.Button("🚀 အသံဖိုင် ဖန်တီးမည်", variant="primary")
        
        with gr.Row():
            audio_out = gr.Audio(label="ထွက်လာသော အသံဖိုင်", type="filepath")
            file_out = gr.File(label="SRT ဖိုင် ဒေါင်းလုဒ်")
            
    btn.click(
        fn=generate_audio, 
        inputs=[text_input, voice_dropdown, filename], 
        outputs=[audio_out, file_out]
    )

# Password စနစ် (Username: user, Password: password123)
# ဤနေရာတွင် Password ကို စိတ်ကြိုက် ပြင်နိုင်သည်
demo.launch(auth=("user", "password123"))
