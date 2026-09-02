import gradio as gr

def calculate_tax(income, status):
    if income is None or income < 0:
        return 0.0

    rates = {
        "Single": 0.30,
        "Married": 0.20,
        "Student": 0.10
    }

    rate = rates.get(status, 0.0)
    return income * rate

with gr.Blocks(theme=gr.themes.Default()) as demo:
    income = gr.Number(label="Income", value=100)
    status = gr.Radio(
        choices=["Single", "Married", "Student"], 
        label="Status", 
        value="Student"
    )
    
    with gr.Row():
        clear_btn = gr.Button("Clear")
        submit_btn = gr.Button("Submit", variant="primary")
        
    taxes = gr.Number(label="Taxes", value=10)

    submit_btn.click(
        fn=calculate_tax, 
        inputs=[income, status], 
        outputs=taxes
    )
    
    clear_btn.click(
        fn=lambda: (None, "Single", None), 
        inputs=None, 
        outputs=[income, status, taxes]
    )

demo.launch()