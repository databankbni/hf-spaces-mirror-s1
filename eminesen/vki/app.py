import gradio as gr

def calculate_bmi(weight, height_cm):
    if weight is None or height_cm is None or weight <= 0 or height_cm <= 0:
        return 0.0, "Lütfen boy ve kilo alanlarını eksiksiz ve 0'dan büyük giriniz."
    height_m = float(height_cm) / 100.0
    bmi = float(weight) / (height_m**2)
    bmi = round(bmi, 2)
    if bmi < 18.5:
        category = "🔵 Zayıf"
    elif 18.5 <= bmi < 25.0:
        category = "🟢 Normal Kilolu"
    elif 25.0 <= bmi < 30.0:
        category = "🟡 Fazla Kilolu"
    else:
        category = "🔴 Obez"
    result_text = f"Vücut Kitle Endeksiniz: {bmi}\nDurum: {category}"
    return bmi, result_text

# Özel CSS ile renklendirme
custom_css = """
#title {
    text-align: center;
    color: #4A00E0;
}
#subtitle {
    text-align: center;
    color: #555555;
}
.gradio-container {
    background: linear-gradient(135deg, #f5f7ff 0%, #ffffff 100%);
}
#submit_btn {
    background: linear-gradient(90deg, #8E2DE2, #4A00E0) !important;
    color: white !important;
    font-weight: bold;
    border: none;
}
"""

with gr.Blocks(theme=gr.themes.Soft(primary_hue="purple", secondary_hue="pink"), css=custom_css) as demo:
    gr.Markdown("# 🧮 Vücut Kitle Endeksi (VKE) Hesaplayıcı", elem_id="title")
    gr.Markdown(
        "Kilonuzu ve boyunuzu girerek Vücut Kitle Endeksinizi anlık olarak hesaplayabilirsiniz.",
        elem_id="subtitle"
    )
    with gr.Row():
        with gr.Column():
            weight_input = gr.Number(
                label="⚖️ Kilo (kg)", value=70.0, minimum=1, maximum=300
            )
            height_input = gr.Number(
                label="📏 Boy (cm)", value=170.0, minimum=1, maximum=250
            )
            submit_btn = gr.Button("Hesapla 🚀", variant="primary", elem_id="submit_btn")
        with gr.Column():
            bmi_output = gr.Number(label="📊 Hesaplanan VKE")
            text_output = gr.Textbox(label="📝 Değerlendirme Sonucu", interactive=False)

    submit_btn.click(
        fn=calculate_bmi,
        inputs=[weight_input, height_input],
        outputs=[bmi_output, text_output],
    )

if __name__ == "__main__":
    demo.launch()