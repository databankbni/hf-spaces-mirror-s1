import os
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

app = FastAPI(
    title="Radiology Report Summarisation API",
    description="Summarises radiology findings into a concise clinical impression."
)

MODEL_PATH = "graceogungbesan1809-debug/flan-t5-radiology"

tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, legacy=False)
model     = AutoModelForSeq2SeqLM.from_pretrained(
    MODEL_PATH,
    ignore_mismatched_sizes = True,
    tie_word_embeddings     = False,
)
model.eval()


class FindingsRequest(BaseModel):
    findings: str


class ImpressionResponse(BaseModel):
    impression: str


@app.get("/")
def root():
    return FileResponse("frontend/index.html")


@app.post("/summarise", response_model=ImpressionResponse)
def summarise(request: FindingsRequest):
    if not request.findings or not request.findings.strip():
        return {"impression": "Error: 'findings' field must not be empty."}

    prompt = "generate a concise clinical impression from these radiology findings: " + request.findings
    inputs = tokenizer(
        prompt,
        return_tensors = "pt",
        truncation     = True,
        max_length     = 512
    )

    output_ids = model.generate(
        **inputs,
        max_new_tokens       = 64,
        min_new_tokens       = 3,
        length_penalty       = 2.0,
        num_beams            = 4,
        no_repeat_ngram_size = 3,
        early_stopping       = True,
        forced_bos_token_id  = 0,
    )

    impression = tokenizer.decode(output_ids[0], skip_special_tokens=True)
    return {"impression": impression}
