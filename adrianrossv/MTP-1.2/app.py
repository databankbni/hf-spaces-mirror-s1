# ================================================================
# MTP - app.py para Hugging Face Space (Gradio, CPU)
# Carga el checkpoint MTP_MODEL.pt desde el repo TeszenAI/MTP-1
#
# OPTIMIZACIÓN DE VELOCIDAD (sin tocar arquitectura ni pesos):
#   - KV-cache en la atención: en generación autoregresiva, cada paso
#     antes recomputaba TODO el contexto desde cero (O(n^2) en total).
#     Ahora se reutiliza lo ya calculado y solo se procesa el token
#     nuevo (O(n) en total). Es el mismo cálculo matemático, solo que
#     no se repite trabajo ya hecho.
#   - F.scaled_dot_product_attention: kernel fusionado de PyTorch,
#     mismo resultado que el softmax manual pero más rápido en CPU.
#     Si la versión de PyTorch no lo trae, cae automáticamente al
#     cálculo manual (fallback), así que no se rompe en ningún entorno.
#   - repetition_penalty vectorizado (sin bucle Python + set() por token).
#
# El modelo, los pesos, el muestreo (top_k/top_p/temperature/repetition)
# y las respuestas de la API/Gradio son EXACTAMENTE los mismos que antes.
# ================================================================
import os
import math
import torch
import torch.nn as nn
import torch.nn.functional as F
import gradio as gr
from starlette.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from huggingface_hub import hf_hub_download

# ---------------- Optimización para CPU ----------------
# Limita hilos a los núcleos disponibles (evita overhead en Spaces pequeños)
torch.set_num_threads(max(1, os.cpu_count() or 1))

# set_num_interop_threads solo puede llamarse una vez y antes de cualquier
# operación paralela; lo protegemos por si el entorno ya lo fijó.
try:
    torch.set_num_interop_threads(1)
except RuntimeError:
    pass

torch.set_grad_enabled(False)  # solo inferencia, nunca necesitamos gradientes

DEVICE = "cpu"

# Disponibilidad de scaled_dot_product_attention (PyTorch >= 2.0).
# Si no está disponible, usamos el softmax manual original como fallback.
_HAS_SDPA = hasattr(F, "scaled_dot_product_attention")

REPO_ID = "TeszenAI/MTP-1.2"
FILENAME = "MTP_MODEL.pt"

# ---------------- Arquitectura (idéntica a la de entrenamiento) ----------------
class CausalSelfAttention(nn.Module):
    def __init__(self, n_embd, n_head, block_size, dropout):
        super().__init__()
        self.n_head = n_head
        self.head_dim = n_embd // n_head
        self.qkv = nn.Linear(n_embd, 3 * n_embd)
        self.proj = nn.Linear(n_embd, n_embd)
        self.attn_dropout = nn.Dropout(dropout)
        self.resid_dropout = nn.Dropout(dropout)
        mask = torch.tril(torch.ones(block_size, block_size)).view(1, 1, block_size, block_size)
        # Se mantiene el buffer para que el state_dict del checkpoint cargue
        # igual que antes (la clave "attn.mask" existe en el checkpoint).
        # Ya no se usa en el forward optimizado con SDPA; solo lo usa el
        # fallback manual si SDPA no está disponible.
        self.register_buffer("mask", mask)

    def forward(self, x, past_kv=None, use_cache=False):
        B, T, C = x.shape
        qkv = self.qkv(x)
        q, k, v = qkv.split(C, dim=2)
        q = q.view(B, T, self.n_head, self.head_dim).transpose(1, 2)
        k = k.view(B, T, self.n_head, self.head_dim).transpose(1, 2)
        v = v.view(B, T, self.n_head, self.head_dim).transpose(1, 2)

        if past_kv is not None:
            past_k, past_v = past_kv
            k = torch.cat([past_k, k], dim=2)
            v = torch.cat([past_v, v], dim=2)

        present_kv = (k, v) if use_cache else None

        # Causal solo hace falta cuando hay varias queries nuevas sin pasado
        # (prefill del prompt). En un paso de decodificación (T=1 con caché)
        # el único token nuevo ya puede ver todo el pasado sin máscara.
        is_causal = (past_kv is None) and (T > 1)

        if _HAS_SDPA:
            out = F.scaled_dot_product_attention(
                q, k, v,
                attn_mask=None,
                dropout_p=0.0,  # en eval() el dropout original no hace nada
                is_causal=is_causal,
            )
        else:
            att = (q @ k.transpose(-2, -1)) / math.sqrt(self.head_dim)
            if is_causal:
                Tk = k.size(-2)
                causal_mask = torch.tril(torch.ones(T, Tk, device=x.device, dtype=torch.bool))
                att = att.masked_fill(~causal_mask, float("-inf"))
            att = F.softmax(att, dim=-1)
            att = self.attn_dropout(att)
            out = att @ v

        out = out.transpose(1, 2).contiguous().view(B, T, C)
        out = self.resid_dropout(self.proj(out))
        return out, present_kv


class FeedForward(nn.Module):
    def __init__(self, n_embd, dropout):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_embd, 4 * n_embd), nn.GELU(),
            nn.Linear(4 * n_embd, n_embd), nn.Dropout(dropout),
        )

    def forward(self, x):
        return self.net(x)


class Block(nn.Module):
    def __init__(self, n_embd, n_head, block_size, dropout):
        super().__init__()
        self.ln1 = nn.LayerNorm(n_embd)
        self.attn = CausalSelfAttention(n_embd, n_head, block_size, dropout)
        self.ln2 = nn.LayerNorm(n_embd)
        self.ff = FeedForward(n_embd, dropout)

    def forward(self, x, past_kv=None, use_cache=False):
        attn_out, present_kv = self.attn(self.ln1(x), past_kv=past_kv, use_cache=use_cache)
        x = x + attn_out
        x = x + self.ff(self.ln2(x))
        return x, present_kv


class MTP(nn.Module):
    def __init__(self, vocab_size, block_size, n_layer, n_head, n_embd, dropout):
        super().__init__()
        self.block_size = block_size
        self.tok_emb = nn.Embedding(vocab_size, n_embd)
        self.pos_emb = nn.Embedding(block_size, n_embd)
        self.drop = nn.Dropout(dropout)
        self.blocks = nn.ModuleList([Block(n_embd, n_head, block_size, dropout) for _ in range(n_layer)])
        self.ln_f = nn.LayerNorm(n_embd)
        self.lm_head = nn.Linear(n_embd, vocab_size, bias=False)
        self.lm_head.weight = self.tok_emb.weight

    def forward(self, idx, past_key_values=None, use_cache=False, pos_offset=0):
        B, T = idx.shape
        pos = torch.arange(pos_offset, pos_offset + T, device=idx.device)
        x = self.tok_emb(idx) + self.pos_emb(pos)
        x = self.drop(x)

        new_past = [] if use_cache else None
        for i, block in enumerate(self.blocks):
            past_kv = past_key_values[i] if past_key_values is not None else None
            x, present_kv = block(x, past_kv=past_kv, use_cache=use_cache)
            if use_cache:
                new_past.append(present_kv)

        x = self.ln_f(x)
        logits = self.lm_head(x)
        return logits, new_past


# ---------------- Carga del checkpoint (una sola vez, al iniciar el Space) ----------------
print("Descargando checkpoint desde el Hub...")
ckpt_path = hf_hub_download(repo_id=REPO_ID, filename=FILENAME)
checkpoint = torch.load(ckpt_path, map_location=DEVICE)

cfg = checkpoint["config"]
stoi = checkpoint["stoi"]
itos = {int(k): v for k, v in checkpoint["itos"].items()}
special = checkpoint["special_tokens"]
gen_defaults = checkpoint["generation_defaults"]

PAD_ID, BOS_ID, EOS_ID, UNK_ID = special["pad_id"], special["bos_id"], special["eos_id"], special["unk_id"]

model = MTP(
    vocab_size=cfg["vocab_size"], block_size=cfg["block_size"],
    n_layer=cfg["n_layer"], n_head=cfg["n_head"],
    n_embd=cfg["n_embd"], dropout=cfg["dropout"],
).to(DEVICE)
model.load_state_dict(checkpoint["model_state_dict"])
model.eval()

BLOCK_SIZE = cfg["block_size"]

print(f"MTP cargado ({checkpoint['meta']['model_name']}, "
      f"entrenado con {checkpoint['meta']['trained_examples']} ejemplos)"
      f" | SDPA={'sí' if _HAS_SDPA else 'no (fallback manual)'}")


def encode_text(s):
    return [stoi.get(ch, UNK_ID) for ch in s]


def decode_ids(ids):
    return "".join(itos.get(i, "") for i in ids if i not in (PAD_ID, BOS_ID, EOS_ID))


# ---------------- Generación (con KV-cache) ----------------
@torch.inference_mode()
def generate(idx, max_new_tokens, temperature, top_k, top_p, repetition_penalty):
    past_key_values = None
    cache_len = 0  # cuántos tokens del extremo derecho de `idx` ya están en la caché

    for _ in range(max_new_tokens):
        total_len = idx.shape[1]

        if total_len <= BLOCK_SIZE:
            if past_key_values is None:
                # Primer paso: una sola pasada ("prefill") sobre todo el prompt.
                logits, past_key_values = model(idx, use_cache=True)
                cache_len = total_len
            else:
                # Pasos siguientes: solo se procesa el último token generado,
                # reutilizando la caché de todo lo anterior.
                last_token = idx[:, -1:]
                logits, past_key_values = model(
                    last_token,
                    past_key_values=past_key_values,
                    use_cache=True,
                    pos_offset=cache_len,
                )
                cache_len += 1
            logits = logits[:, -1, :]
        else:
            # Se superó block_size: mismo comportamiento que el modelo original
            # (ventana deslizante recalculada por completo). Solo ocurre en
            # respuestas muy largas; la caché se reinicia para esa ventana.
            idx_cond = idx[:, -BLOCK_SIZE:]
            logits, past_key_values = model(idx_cond, use_cache=True)
            cache_len = BLOCK_SIZE
            logits = logits[:, -1, :]

        logits = logits / max(temperature, 1e-5)

        if repetition_penalty and repetition_penalty != 1.0:
            # Vectorizado: antes era `for token_id in set(idx[0].tolist())`,
            # un bucle Python nuevo por cada token generado.
            unique_ids = torch.unique(idx[0])
            logits[0, unique_ids] /= repetition_penalty

        if top_k is not None and top_k > 0:
            v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
            logits[logits < v[:, [-1]]] = float("-inf")

        probs = F.softmax(logits, dim=-1)

        if top_p is not None and 0 < top_p < 1:
            sorted_probs, sorted_idx = torch.sort(probs, descending=True)
            cum_probs = torch.cumsum(sorted_probs, dim=-1)
            cutoff = cum_probs > top_p
            cutoff[:, 1:] = cutoff[:, :-1].clone()
            cutoff[:, 0] = False
            sorted_probs[cutoff] = 0.0
            sorted_probs = sorted_probs / sorted_probs.sum(dim=-1, keepdim=True)
            next_id = sorted_idx.gather(-1, torch.multinomial(sorted_probs, 1))
        else:
            next_id = torch.multinomial(probs, num_samples=1)

        idx = torch.cat([idx, next_id], dim=1)
        if next_id.item() == EOS_ID:
            break

    return idx


def run_inference(text, max_new_tokens=None, temperature=None, top_k=None, top_p=None, repetition_penalty=None):
    """Núcleo de generación, reutilizado por la UI de Gradio y por la API /generate.
    No reduce calidad por estar en CPU: usa exactamente el mismo muestreo
    (top_k + top_p + repetition_penalty) que en la Celda 2 de entrenamiento,
    solo que ahora con KV-cache es notablemente más rápido en respuestas largas."""
    max_new_tokens = int(max_new_tokens) if max_new_tokens else gen_defaults["max_new_tokens"]
    temperature = float(temperature) if temperature is not None else gen_defaults["temperature"]
    top_k = int(top_k) if top_k is not None else gen_defaults["top_k"]
    top_p = float(top_p) if top_p is not None else gen_defaults["top_p"]
    repetition_penalty = float(repetition_penalty) if repetition_penalty is not None else gen_defaults["repetition_penalty"]

    # Techo máximo de generación: no obliga a generar siempre esto, es solo
    # el límite superior disponible cuando la respuesta realmente lo amerite
    # (el modelo igual corta antes solo con el token <eos> en respuestas cortas).
    # 4000 caracteres ronda el tamaño de una respuesta larga tipo ChatGPT.
    MAX_TOKENS_HARD_LIMIT = 4000
    max_new_tokens = max(1, min(max_new_tokens, MAX_TOKENS_HARD_LIMIT))

    prefix = f"Usuario: {text}\nMTP: "
    ids = [BOS_ID] + encode_text(prefix)
    idx = torch.tensor([ids], dtype=torch.long, device=DEVICE)

    out = generate(idx, max_new_tokens, temperature, top_k, top_p, repetition_penalty)
    new_ids = out[0].tolist()[len(ids):]
    return decode_ids(new_ids).strip()


def chat_fn(message, history, max_new_tokens, temperature, top_k, top_p, repetition_penalty):
    return run_inference(message, max_new_tokens, temperature, top_k, top_p, repetition_penalty)


# ---------------- Interfaz Gradio (para probar el modelo desde el navegador) ----------------
with gr.Blocks(title="MTP Chat") as demo:
    gr.Markdown("# MTP\nModelo GPT entrenado desde cero (char-level). Ejecutándose en CPU.")

    with gr.Accordion("Parámetros de generación", open=False):
        max_new_tokens_ui = gr.Slider(16, 4000, value=gen_defaults["max_new_tokens"], step=10, label="max_new_tokens")
        temperature_ui = gr.Slider(0.1, 2.0, value=gen_defaults["temperature"], step=0.05, label="temperature")
        top_k_ui = gr.Slider(0, 100, value=gen_defaults["top_k"], step=1, label="top_k")
        top_p_ui = gr.Slider(0.1, 1.0, value=gen_defaults["top_p"], step=0.05, label="top_p")
        repetition_penalty_ui = gr.Slider(1.0, 2.0, value=gen_defaults["repetition_penalty"], step=0.05,
                                           label="repetition_penalty")

    chatbot = gr.ChatInterface(
        fn=chat_fn,
        additional_inputs=[max_new_tokens_ui, temperature_ui, top_k_ui, top_p_ui, repetition_penalty_ui],
        title=None,
        examples=[
            ["Hola, ¿cómo estás?"],
            ["¿Cuánto es 8 + 5?"],
            ["Explícame qué es un algoritmo."],
        ],
        cache_examples=False,
    )

demo.queue(max_size=16)

# ---------------- API REST /generate (la que consume el PHP) ----------------
# El PHP hace: fetch(url, { method:'POST', body: JSON.stringify({text, max_tokens, temperature}) })
# y espera de vuelta: { "reply": "..." }
#
# IMPORTANTE:
# - ssr_mode=False: Gradio 6 usa un servidor Node.js aparte para SSR, que
#   intentaba levantarse en el puerto 7861 y chocaba. Lo desactivamos porque
#   no lo necesitamos para servir la API.
# - El middleware CORS se pasa vía app_kwargs ANTES de llamar a launch(),
#   porque una vez que la app arranca, Starlette ya no permite añadir
#   middleware (por eso fallaba con app.add_middleware() después).

class GenerateRequest(BaseModel):
    text: str
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_k: Optional[int] = None
    top_p: Optional[float] = None
    repetition_penalty: Optional[float] = None


PORT = int(os.environ.get("PORT", 7860))
demo.launch(
    server_name="0.0.0.0",
    server_port=PORT,
    prevent_thread_lock=True,
    ssr_mode=False,
    app_kwargs={
        "middleware": [
            Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
        ]
    },
)

app = demo.app


@app.post("/generate")
def generate_endpoint(req: GenerateRequest):
    if not req.text or not req.text.strip():
        return {"reply": "Escribe algo para que pueda responder."}
    try:
        reply = run_inference(
            req.text,
            max_new_tokens=req.max_tokens,
            temperature=req.temperature,
            top_k=req.top_k,
            top_p=req.top_p,
            repetition_penalty=req.repetition_penalty,
        )
        if not reply:
            reply = "No pude generar una respuesta."
        return {"reply": reply}
    except Exception as e:
        return {"reply": f"Error del modelo: {e}"}


@app.get("/generate")
def generate_health():
    # Solo para poder comprobar en el navegador que la ruta existe (GET no genera texto)
    return {"status": "ok", "info": "Usa POST con JSON {text, max_tokens, temperature}"}


# demo.launch(prevent_thread_lock=True) ya dejó el servidor corriendo en un
# hilo en segundo plano (un solo proceso, un solo puerto). Mantenemos vivo
# el hilo principal para que el contenedor del Space no termine.
demo.block_thread()