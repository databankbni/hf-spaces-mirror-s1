import gradio as gr
from transformers import pipeline

sentiment = pipeline("sentiment-analysis", model="distilbert-base-uncased-finetuned-sst-2-english")

def analyze(text):
    return sentiment(text)

gr.Interface(fn=analyze, inputs="text", outputs="text").launch()

