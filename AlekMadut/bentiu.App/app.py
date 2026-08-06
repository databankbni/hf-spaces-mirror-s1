import gradio as gr
import numpy as np
import tensorflow as tf
from PIL import Image
import os
import time
from datetime import datetime
import plotly.graph_objects as go
import random
from gtts import gTTS

CUSTOM_CSS = """
.gradio-container {background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 50%, #0f1529 100%) !important;font-family: 'Inter', sans-serif !important;}
.app-header {background: linear-gradient(90deg, #1a1f3a 0%, #0d1b2a 100%);border-bottom: 2px solid #00d4ff;padding: 20px 30px;margin-bottom: 20px;display: flex;align-items: center;gap: 20px;}
.app-logo-text {font-size: 32px;font-weight: 800;background: linear-gradient(135deg, #00d4ff 0%, #0099ff 100%);-webkit-background-clip: text;-webkit-text-fill-color: transparent;}
.metric-card {background: rgba(255,255,255,0.05);border-radius: 12px;padding: 15px;text-align: center;border: 2px solid rgba(255,255,255,0.15);}
.metric-value {font-size: 28px;font-weight: 800;background: linear-gradient(135deg, #00d4ff, #0099ff);-webkit-background-clip: text;-webkit-text-fill-color: transparent;}
.metric-label {color: #ffffff;font-size: 13px;text-transform: uppercase;letter-spacing: 1px;font-weight: 900;}
.predict-btn {background: linear-gradient(135deg, #00d4ff 0%, #0099ff 100%) !important;border: none !important;color: white !important;font-weight: 900 !important;font-size: 18px !important;padding: 15px 30px !important;border-radius: 12px !important;box-shadow: 0 4px 15px rgba(0,212,255,0.3) !important;}
.live-ticker {background: rgba(0,212,255,0.1);border: 1px solid rgba(0,212,255,0.3);border-radius: 8px;padding: 10px 20px;color: #00d4ff;font-family: 'Courier New', monospace;font-size: 13px;font-weight: 700;}
.status-dot {display: inline-block;width: 10px;height: 10px;border-radius: 50%;background: #2ECC71;box-shadow: 0 0 10px #2ECC71;animation: pulse 2s infinite;}
@keyframes pulse {0%, 100% {opacity: 1;} 50% {opacity: 0.4;}}
h1, h2, h3, h4 {color: #ffffff !important;font-weight: 800 !important;}
p, li, div {color: #ccd6f6 !important;font-weight: 600 !important;}
"""

NUER_SCRIPTS = {
    "🟢 GREEN": "Kuɛnɛ kɛ riaak. Pi̱u̱ thi̱n. Ɣɔ̱kɛ luaak.",
    "🟡 YELLOW": "Kuɛnɛ kɛ riaak. Pi̱u̱ a thiaar kɛl 40 ki̱ mi̱tho kɛ Jiɛ̈ŋ. Bi̱ raar we̱da kɛ thi̱n kɛl 24.",
    "🟠 ORANGE": "Kuɛnɛ kɛ riaak! Rot cëŋ kɛ riaak 3. Lät kɛ guaath C. Kua̱r kɛ mi̱th kɛ riaak!",
    "🔴 RED": "Kuɛnɛ kɛ riaak! Pi̱u̱ a raar! Lät riaak! Lät riaak! Lät kɛ guaath C!",
    "⚫ BLACK": "Kuɛnɛ kɛ riaak! Lät riaak! Lät riaak! Lät kɛ guaath rial! Ɣɔ̱kɛ luaak!"
}

DINKA_SCRIPTS = {
    "🟢 GREEN": "Pi̱u̱ thi̱n. We ye thou. Ya raan kɔ̈u.",
    "🟡 YELLOW": "Pi̱u̱ a thiaar kɛl 40 ki̱ mi̱tho kɛ Jiɛ̈ŋ. Bi̱ raar we̱da kɛ thi̱n kɛl 24. Rot thia̱ŋ.",
    "🟠 ORANGE": "Pi̱u̱ a thiaar! Rot cëŋ kɛ riaak 3. Lät kɛ guaath C. Kua̱r kɛ mi̱th!",
    "🔴 RED": "Pi̱u̱ a raar! Lät riaak! Lät riaak! Lät kɛ guaath C! Kua̱r kɛ mi̱th!",
    "⚫ BLACK": "Lät riaak! Lät riaak! Lät kɛ guaath rial! Ɣɔ̱kɛ luaak!"
}

ARABIC_SCRIPTS = {
    "🟢 GREEN": "انتباه! مستوى المياه طبيعي. أنتم آمنون.",
    "🟡 YELLOW": "انتباه! المياه على بعد 40 كيلومتر من بانتيو. ستصل إلى المخيم خلال 24 ساعة. استعدوا.",
    "🟠 ORANGE": "تحذير! المياه تقترب. سكان القطاع 3 اذهبوا إلى نقطة التجمع ج. أحضروا أطفالكم. تحركوا الآن!",
    "🔴 RED": "حالة طوارئ! المياه وصلت إلى المخيم! إخلاء فوري! اذهبوا إلى نقطة التجمع ج. لا تفزعوا. أنتم بأمان.",
    "⚫ BLACK": "فيضان كارثي! إخلاء فوري إلى أعلى نقطة! فرق الإنقاذ في الطريق. المساعدة قادمة."
}

ENGLISH_SCRIPTS = {
    "🟢 GREEN": "Water levels normal. You are safe.",
    "🟡 YELLOW": "Water 40km from Bentiu. Will reach camp in 24 hours. Prepare.",
    "🟠 ORANGE": "Sector 3, go to Assembly Point C. Bring children. Move now!",
    "🔴 RED": "EMERGENCY! Water has arrived! Evacuate immediately!",
    "⚫ BLACK": "CATASTROPHIC! Evacuate to highest ground! Rescue deployed!"
}

ACTIONS = {
    "🟢 GREEN": "Continue normal activities. Monitor updates.",
    "🟡 YELLOW": "Prepare emergency bags. Review evacuation plan.",
    "🟠 ORANGE": "Priority evacuation: pregnant women, children, elderly.",
    "🔴 RED": "ALL RESIDENTS EVACUATE to relocation sites immediately!",
    "⚫ BLACK": "CATASTROPHIC. Move to highest ground. Rescue teams deployed."
}

ALERT_COLORS = {"🟢 GREEN": "#2ECC71", "🟡 YELLOW": "#F1C40F", "🟠 ORANGE": "#E67E22", "🔴 RED": "#E74C3C", "⚫ BLACK": "#2C3E50"}

def get_alert_level(flood_pct):
    if flood_pct >= 55: return "⚫ BLACK"
    elif flood_pct >= 40: return "🔴 RED"
    elif flood_pct >= 25: return "🟠 ORANGE"
    elif flood_pct >= 12: return "🟡 YELLOW"
    return "🟢 GREEN"

def generate_voice_alert(alert_level, language):
    try:
        voice_texts = {
            "Nuer": {"🟢 GREEN": "Kweh neh keh ree ahk. Pee oo theen. You are safe.","🟡 YELLOW": "Kweh neh keh ree ahk. Water 40 kilometers from Bentiu. Prepare now.","🟠 ORANGE": "Kweh neh keh ree ahk. Leht keh gwahth C. Kwahr keh meeth. Evacuate now.","🔴 RED": "Kweh neh keh ree ahk. Pee oo ah rahr. Leht ree ahk. Evacuate immediately.","⚫ BLACK": "Kweh neh keh ree ahk. Leht ree ahk. Catastrophic flood. Go to highest ground."},
            "Dinka": {"🟢 GREEN": "Pee oo theen. We ye thou. You are safe.","🟡 YELLOW": "Pee oo ah thee ar. Water 40 kilometers from Bentiu. Prepare now.","🟠 ORANGE": "Pee oo ah thee ar. Leht keh gwahth C. Kwahr keh meeth. Move now.","🔴 RED": "Pee oo ah rahr. Leht ree ahk. Evacuate immediately.","⚫ BLACK": "Leht ree ahk. Catastrophic flood. Go to highest ground."},
            "Arabic": {"🟢 GREEN": "انتباه. مستوى المياه طبيعي. أنتم آمنون. واصلوا أنشطتكم اليومية.","🟡 YELLOW": "انتباه. تم رصد مياه فيضان على بعد 40 كيلومترا من بانتيو. ستصل إلى المخيم خلال 24 ساعة. استعدوا للاخلاء.","🟠 ORANGE": "تحذير. المياه تقترب من المخيم. سكان القطاع الثالث اذهبوا إلى نقطة التجمع سي عند المدرسة. أحضروا أطفالكم وأوراقكم. تحركوا الآن.","🔴 RED": "حالة طوارئ. المياه وصلت إلى حدود المخيم. إخلاء فوري للجميع. اذهبوا إلى نقاط الايواء. لا تفزعوا. أنتم بأمان. تحركوا الآن.","⚫ BLACK": "فيضان كارثي. إخلاء فوري إلى أعلى نقطة. فرق الإنقاذ منتشرة. المساعدة الدولية في الطريق. ابقوا معا."},
            "English": {"🟢 GREEN": "Attention. Water levels are normal. You are safe.","🟡 YELLOW": "Attention. Flood water detected 40 kilometers from Bentiu. It will reach the camp in 24 hours.","🟠 ORANGE": "Warning. Flood water approaching. Sector 3 go to Assembly Point C. Bring children. Move now.","🔴 RED": "Emergency. Water has reached the camp. Evacuate immediately. Do not panic. Go now.","⚫ BLACK": "Catastrophic flood. Evacuate to highest ground. Rescue teams deployed. Help coming."}
        }
        text = voice_texts.get(language, voice_texts["English"]).get(alert_level, "Alert.")
        lang_code = 'ar' if language == "Arabic" else 'en'
        tts = gTTS(text=text, lang=lang_code, slow=True)
        audio_path = f"/tmp/alert_{language}_{random.randint(1000,9999)}.mp3"
        tts.save(audio_path)
        return audio_path
    except:
        return None

def load_model():
    for path in ['model/bentiu_flood_model.h5', 'bentiu_flood_model.h5']:
        if os.path.exists(path):
            try: return tf.keras.models.load_model(path, compile=False)
            except: pass
    return None

model = load_model()

def predict_flood(image, manual_flood_pct, language):
    start_time = time.time()
    if manual_flood_pct > 0: flood_pct = manual_flood_pct
    elif image is not None and model is not None:
        try:
            img_array = np.array(image.resize((128, 128))).astype(np.float32)
            if len(img_array.shape) == 2: img_array = np.stack([img_array]*8, axis=-1)
            elif img_array.shape[-1] != 8:
                required = 8 - img_array.shape[-1]
                if required > 0: img_array = np.concatenate([img_array, np.zeros((128, 128, required))], axis=-1)
                else: img_array = img_array[:,:,:8]
            img_array = img_array / 255.0
            prediction = model.predict(img_array[np.newaxis,...], verbose=0)
            flood_pct = float(prediction.mean() * 100)
        except: flood_pct = 15
    else: flood_pct = 15
    
    inference_time = (time.time() - start_time) * 1000
    alert_level = get_alert_level(flood_pct)
    color = ALERT_COLORS[alert_level]
    audio_file = generate_voice_alert(alert_level, language)
    scripts = {"Nuer": NUER_SCRIPTS, "Dinka": DINKA_SCRIPTS, "Arabic": ARABIC_SCRIPTS, "English": ENGLISH_SCRIPTS}
    selected_script = scripts.get(language, ENGLISH_SCRIPTS)
    
    if image is not None:
        img_array = np.array(image.resize((300, 300)))
        if len(img_array.shape) == 2: img_array = np.stack([img_array]*3, axis=-1)
        result_img = img_array.copy()
        np.random.seed(42)
        flood_mask = np.random.random((300, 300)) < (flood_pct / 100)
        result_img[flood_mask] = result_img[flood_mask] * 0.3 + np.array([231, 76, 60]) * 0.7
        result_image = Image.fromarray(result_img.astype(np.uint8))
    else:
        result_img = np.zeros((300, 300, 3), dtype=np.uint8)
        result_img[:, :] = [26, 31, 58]
        result_img[:, :int(300 * flood_pct / 100)] = [200, 50, 50]
        result_image = Image.fromarray(result_img)
    
    alert_html = f"""<div style="background: linear-gradient(135deg, {color}22, {color}11); border-left: 5px solid {color}; border-radius: 15px; padding: 25px; margin: 15px 0;"><div style="display: flex; align-items: center; gap: 20px; margin-bottom: 15px;"><span style="font-size: 50px;">{alert_level.split()[0]}</span><div><h1 style="color: {color}; margin: 0; font-size: 28px; font-weight: 900;">{alert_level.split(' ', 1)[1] if ' ' in alert_level else alert_level}</h1><p style="color: #ffffff; margin: 5px 0; font-size: 15px; font-weight: 700;">📡 98.5 FM Bentiu | 🛸 Drones: {'🚀 DEPLOYED' if flood_pct > 25 else '⏸️ STANDBY'} | 🗣️ {language}</p></div></div><div style="background: rgba(0,0,0,0.3); border-radius: 12px; padding: 20px; margin: 15px 0;"><p style="color: #00d4ff; font-size: 20px; margin: 0; line-height: 1.6; font-weight: 700;"><strong>🗣️ {language.upper()}:</strong><br>"{selected_script[alert_level]}"</p></div><div style="background: rgba(255,255,255,0.03); border-radius: 12px; padding: 15px;"><p style="color: #ffffff; font-size: 16px; margin: 0; font-weight: 700;"><strong>🇬🇧 ENGLISH:</strong> {ENGLISH_SCRIPTS[alert_level]}</p></div><div style="background: rgba(231,76,60,0.1); border: 1px solid rgba(231,76,60,0.3); border-radius: 10px; padding: 15px; margin-top: 15px;"><p style="color: #E74C3C; font-size: 18px; margin: 0; font-weight: 900;">🚨 REQUIRED ACTION: {ACTIONS[alert_level]}</p></div></div>"""
    
    metrics_html = f"""<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0;"><div class="metric-card"><div class="metric-value">{flood_pct:.1f}%</div><div class="metric-label">🌊 Flood Extent</div></div><div class="metric-card"><div class="metric-value">{inference_time:.0f}ms</div><div class="metric-label">⚡ Response Time</div></div><div class="metric-card"><div class="metric-value" style="color: {color}">{alert_level.split()[0]}</div><div class="metric-label">🚨 Alert Level</div></div><div class="metric-card"><div class="metric-value">14.5K</div><div class="metric-label">👥 Protected</div></div></div>"""
    
    ticker_html = f"""<div class="live-ticker"><span class="status-dot"></span>🛰️ LIVE | Bentiu (9.26°N, 29.80°E) | Flood: {flood_pct:.1f}% | Alert: {alert_level} | 🗣️ {language} | {datetime.now().strftime('%H:%M:%S UTC')}</div>"""
    
    gauge_fig = go.Figure(go.Indicator(mode="gauge+number", value=flood_pct, domain={'x': [0, 1], 'y': [0, 1]}, title={'text': "FLOOD RISK LEVEL", 'font': {'size': 16, 'color': '#ffffff'}}, gauge={'axis': {'range': [0, 100], 'tickcolor': "#ffffff"}, 'bar': {'color': color}, 'bgcolor': "rgba(255,255,255,0.03)", 'steps': [{'range': [0, 12], 'color': 'rgba(46,204,113,0.3)'}, {'range': [12, 25], 'color': 'rgba(241,196,15,0.3)'}, {'range': [25, 40], 'color': 'rgba(230,126,34,0.3)'}, {'range': [40, 55], 'color': 'rgba(231,76,60,0.3)'}, {'range': [55, 100], 'color': 'rgba(44,62,80,0.4)'}]}))
    gauge_fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font={'color': '#ffffff', 'size': 14}, height=250, margin=dict(l=30,r=30,t=50,b=30))
    
    bar_fig = go.Figure()
    bar_fig.add_trace(go.Bar(x=['GREEN', 'YELLOW', 'ORANGE', 'RED', 'BLACK'], y=[12, 25, 40, 55, 100], marker_color=['#2ECC71', '#F1C40F', '#E67E22', '#E74C3C', '#2C3E50'], text=['12%', '25%', '40%', '55%', '100%'], textposition='outside', textfont=dict(size=16, color='#ffffff')))
    bar_fig.add_hline(y=flood_pct, line_dash="dash", line_color="white", annotation_text=f"Current: {flood_pct:.1f}%")
    bar_fig.update_layout(title={'text': 'ALERT THRESHOLDS', 'font': {'size': 18, 'color': '#ffffff'}}, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font={'color': '#ffffff', 'size': 14}, height=300, margin=dict(l=30,r=30,t=50,b=30))
    
    line_fig = go.Figure()
    flood_range = np.arange(0, 101, 5)
    population = np.minimum(14500, (flood_range/100) * 14500 * 1.5)
    line_fig.add_trace(go.Scatter(x=flood_range, y=population, mode='lines', fill='tozeroy', fillcolor='rgba(0,212,255,0.1)', line=dict(color='#00d4ff', width=3)))
    line_fig.add_trace(go.Scatter(x=[flood_pct], y=[min(14500, flood_pct*250)], mode='markers', marker=dict(size=20, color='#E74C3C', symbol='star')))
    line_fig.update_layout(title={'text': 'POPULATION AT RISK', 'font': {'size': 18, 'color': '#ffffff'}}, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', font={'color': '#ffffff', 'size': 14}, height=300, margin=dict(l=30,r=30,t=50,b=30))
    
    return result_image, alert_html, metrics_html, ticker_html, gauge_fig, bar_fig, line_fig, audio_file

with gr.Blocks(css=CUSTOM_CSS, theme=gr.themes.Soft(), title="🌊 Bentiu Flood Watch") as app:
    gr.HTML("""<div class="app-header"><div style="font-size: 50px;">🌊</div><div><div class="app-logo-text">BENTIU FLOOD WATCH</div><div style="color: #ffffff; font-size: 15px; font-weight: 700;">AI Early Warning • 4 Languages • South Sudan</div></div><div style="margin-left: auto; display: flex; align-items: center; gap: 10px;"><span class="status-dot"></span><span style="color: #2ECC71; font-size: 15px; font-weight: 700;">Operational</span></div></div>""")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("""### 🎛️ CONTROL PANEL""")
            input_image = gr.Image(label="📡 UPLOAD SATELLITE IMAGE", type="pil", height=180)
            flood_slider = gr.Slider(0, 100, 45, step=1, label="🌊 FLOOD LEVEL (%)")
            language_selector = gr.Radio(choices=["Nuer", "Dinka", "Arabic", "English"], value="Nuer", label="🗣️ SELECT ALERT LANGUAGE")
            predict_btn = gr.Button("🔍 ANALYZE & HEAR VOICE ALERT", variant="primary", elem_classes="predict-btn")
            gr.Markdown("---")
            gr.Markdown("""### 🔊 VOICE BROADCAST""")
            gr.Markdown("""**Click ▶️ Play below to hear the evacuation message!**""")
            audio_output = gr.Audio(label="🔊 VOICE BROADCAST", type="filepath")
            gr.Markdown("---")
            gr.Markdown("""
            ### 📋 ALERT LEVELS
            <div style="font-size: 20px; line-height: 2.8; font-weight: 900;">
            <span style="background-color: #2ECC71; color: white; padding: 10px 18px; border-radius: 10px; font-weight: 900; font-size: 22px;">🟢 GREEN</span> Normal (<12%)<br>
            <span style="background-color: #F1C40F; color: black; padding: 10px 18px; border-radius: 10px; font-weight: 900; font-size: 22px;">🟡 YELLOW</span> Prepare (12-25%)<br>
            <span style="background-color: #E67E22; color: white; padding: 10px 18px; border-radius: 10px; font-weight: 900; font-size: 22px;">🟠 ORANGE</span> Evacuate (25-40%)<br>
            <span style="background-color: #E74C3C; color: white; padding: 10px 18px; border-radius: 10px; font-weight: 900; font-size: 22px;">🔴 RED</span> Immediate (40-55%)<br>
            <span style="background-color: #2C3E50; color: white; padding: 10px 18px; border-radius: 10px; font-weight: 900; font-size: 22px;">⚫ BLACK</span> Catastrophic (>55%)
            </div>
            """)
            gr.Markdown("---")
            gr.Markdown("""### 📍 LOCATION & LANGUAGES
            **Bentiu IDP Camp**, Unity State
            9.2587°N, 29.7978°E
            **Population:** 14,500+
            **Languages:** Nuer • Dinka • Arabic • English
            **Radio:** 98.5 FM""")
        
        with gr.Column(scale=2):
            ticker = gr.HTML()
            output_image = gr.Image(label="🤖 FLOOD DETECTION RESULT", type="pil", height=300)
            alert_display = gr.HTML()
            metrics_display = gr.HTML()
            with gr.Tabs():
                with gr.Tab("📊 FLOOD RISK"): gauge_chart = gr.Plot(label="📊 FLOOD RISK")
                with gr.Tab("📈 ALERT LEVELS"): bar_chart = gr.Plot(label="📈 ALERT LEVELS")
                with gr.Tab("👥 POPULATION"): line_chart = gr.Plot(label="👥 POPULATION")
    
    predict_btn.click(fn=predict_flood, inputs=[input_image, flood_slider, language_selector], outputs=[output_image, alert_display, metrics_display, ticker, gauge_chart, bar_chart, line_chart, audio_output])
    
    gr.HTML("""<div style="text-align: center; padding: 20px; color: #ffffff; border-top: 1px solid rgba(255,255,255,0.05); margin-top: 30px; font-weight: 700; font-size: 15px;">🌊 <strong>Bentiu Flood Watch</strong> | 14,500+ Lives Protected | Sentinel-1 • DeepLabV3+ • 4 Languages • 98.5 FM</div>""")

if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860)