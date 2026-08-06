import gradio as gr

def hello(name):
    return f"Xin chào {name}!"

demo = gr.Interface(
    fn=hello,
    inputs="text",
    outputs="text",
    title="Ứng dụng đồ họa trên Google Colab"
)

demo.launch()