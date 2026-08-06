import gradio as gr


def calculate_bmi(weight: float, height_cm: float) -> tuple[float, str]:
    if weight <= 0 or height_cm <= 0:
        return 0.0, "Hatalı Giriş: Değerler 0'dan büyük olmalıdır."

    # Boyu metreye çevir ve BMI hesapla: BMI = kg / m^2
    height_m = height_cm / 100.0
    bmi = weight / (height_m**2)
    bmi = round(bmi, 2)

    # Kategorizasyon
    if bmi < 18.5:
        category = "Zayıf"
    elif 18.5 <= bmi < 24.9:
        category = "Normal Kilolu"
    elif 25.0 <= bmi < 29.9:
        category = "Fazla Kilolu"
    else:
        category = "Obez"

    result_text = f"Vücut Kitle Endeksiniz: {bmi}\nDurum: {category}"
    return bmi, result_text


# Gradio Arayüz Tasarımı
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# Vücut Kitle Endeksi (VKE) Hesaplayıcı")
    gr.Markdown(
        "Kilonuzu ve boyunuzu girerek Vücut Kitle Endeksinizi anlık olarak hesaplayabilirsiniz."
    )

    with gr.Row():
        with gr.Column():
            weight_input = gr.Number(
                label="Kilo (kg)", value=70.0, minimum=1, maximum=300
            )
            height_input = gr.Number(
                label="Boy (cm)", value=170.0, minimum=1, maximum=250
            )
            submit_btn = gr.Button("Hesapla", variant="primary")

        with gr.Column():
            bmi_output = gr.Number(label="Hesaplanan VKE")
            text_output = gr.Textbox(label="Değerlendirme Sonucu", interactive=False)

    # Tetikleyiciler (Aksiyonlar)
    submit_btn.click(
        fn=calculate_bmi,
        inputs=[weight_input, height_input],
        outputs=[bmi_output, text_output],
    )

if __name__ == "__main__":
    demo.launch()
    