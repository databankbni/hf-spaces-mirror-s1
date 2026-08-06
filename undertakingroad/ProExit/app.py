import gradio as gr
from transformers import pipeline

model = pipeline(
    "text-classification",
    model="distilbert-base-uncased"
)

def predict(text):
    return model(text)

demo = gr.Interface(
    fn=predict,
    inputs="text",
    outputs="text"
)

demo.launch()