from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
import torch
import tiktoken
from gpt import GPTLanguageModel

device = 'cpu'

tokenizer = tiktoken.get_encoding('gpt2')
model = GPTLanguageModel.from_pretrained('gpt2') 
model.to(device)
model.eval()

app = FastAPI()

class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    max_new_tokens: int = Field(100, gt=0, le=512)
    temperature: float = Field(1.0, gt=0)
    top_k: int | None = Field(None, gt=0)

@app.get('/')
def root():
    return RedirectResponse(url='/docs')

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.post('/generate')
def generate(req: GenerateRequest):
    input_ids = tokenizer.encode(req.prompt)
    x = torch.tensor(input_ids, dtype=torch.long, device=device).unsqueeze(0)
    with torch.no_grad():
        y = model.generate(
            x, 
            max_new_tokens=req.max_new_tokens, 
            temperature=req.temperature, 
            top_k=req.top_k
        )
    out_tokens = y[0].tolist()
    generated_tokens = out_tokens[len(input_ids):]
    completion_text = tokenizer.decode(generated_tokens)
    return {'text': completion_text}
