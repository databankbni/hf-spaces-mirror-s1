from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

app = FastAPI()

model = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen2.5-0.5B-Instruct",
    device_map="auto"
)
tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-0.5B-Instruct")

class Item(BaseModel):
    prompt: str

@app.post("/chat")
def chat(item: Item):
    inputs = tokenizer(item.prompt, return_tensors="pt")
    outputs = model.generate(**inputs, max_new_tokens=200)
    reply = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return {"reply": reply}
