import os
import gradio as gr
from transformers import pipeline
from huggingface_hub import login


hf_token = os.getenv("SCA")
if hf_token:
    login(token=hf_token)
else:
    print("Warning: SCA token environment variable is empty!")

# Pass the token explicitly into the pipeline configuration
pipe = pipeline(
    "text-generation", 
    model="meta-llama/Llama-3.2-1B-Instruct",
    token=hf_token
)

def predict(user_input):
    messages = [
        {
            "role": "system", 
            "content": "You are a strict text-summarization bot. Output ONLY the concise summary."
        },
        {
            "role": "user", 
            "content": f"Summarize this text in one or two sentences: {user_input}"
        }
    ]
    
    outputs = pipe(messages, max_new_tokens=150)
    
    conversation = outputs[0]['generated_text']
    assistant_reply = conversation[-1]['content']
    
    return assistant_reply.strip()

textbox = gr.Textbox(placeholder="Enter text to summarize...", lines=4)

gr.Interface(fn=predict, inputs=textbox, outputs="text").launch()