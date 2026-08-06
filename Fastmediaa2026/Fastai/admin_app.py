import gradio as gr
from admin_enhanced import create_enhanced_admin_ui

with gr.Blocks(theme=gr.themes.Soft(primary_hue="orange")) as demo:
    create_enhanced_admin_ui()

demo.launch()