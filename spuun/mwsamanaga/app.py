import gradio as gr
import torch
import json
from safetensors.torch import load_model, safe_open
import requests
from pathlib import Path
import base64
import os
import random
import torch.nn as nn
import numpy as np

MODEL_URL = "https://files.catbox.moe/6yulot.safetensors"
MODEL_PATH = Path("rajaKripto.safetensors")
SECRET_KEY = os.environ.get("SECRET_KEY", "placeholder_key")
HMMM = os.environ.get("HMMM", "hmmmm?")

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

class RajaKripto(nn.Module):
    def __init__(self, vocab_size, hidden_dim=256, char_to_idx=None, idx_to_char=None):
        super().__init__()
        self._e = nn.Embedding(vocab_size, hidden_dim)
        self._f1 = nn.Linear(hidden_dim, hidden_dim)
        self._f2 = nn.Linear(hidden_dim, hidden_dim)
        self._f3 = nn.Linear(hidden_dim, vocab_size)
        self._dim = hidden_dim

        if char_to_idx and idx_to_char:
            self.init_dicts(char_to_idx, idx_to_char)

    def init_dicts(self, char_to_idx, idx_to_char):
        self.register_buffer('_char_to_idx_keys', torch.tensor([ord(c) for c in char_to_idx.keys()], dtype=torch.long))
        self.register_buffer('_char_to_idx_values', torch.tensor(list(char_to_idx.values()), dtype=torch.long))
        self.register_buffer('_idx_to_char_keys', torch.tensor(list(idx_to_char.keys()), dtype=torch.long))
        self.register_buffer('_idx_to_char_values', torch.tensor([ord(c) for c in idx_to_char.values()], dtype=torch.long))

    @property
    def char_to_idx(self):
        return {chr(k.item()): v.item() for k, v in zip(self._char_to_idx_keys, self._char_to_idx_values)}

    @property
    def idx_to_char(self):
        return {k.item(): chr(v.item()) for k, v in zip(self._idx_to_char_keys, self._idx_to_char_values)}

    def _scramble(self, x, k):
        _m = 0.5 * (torch.tanh(10 * (x - 0.5)) + 1)
        _n = k.round()
        return (_m - _n).abs().clamp(0, 1)

    def encode(self, x, k):
        _t = self._e(x)
        _v = self._f1(_t)
        _p = torch.sigmoid(_v)
        _k = k.unsqueeze(1).repeat(1, _p.size(1), 1)
        return self._scramble(_p, _k)

    def decode(self, x, k):
        _k = k.unsqueeze(1).repeat(1, x.size(1), 1)
        _d = self._scramble(x, _k)
        _h = torch.relu(self._f2(_d))
        return self._f3(_h)

    def forward(self, x, k, decrypt=False):
        return self.decode(x, k) if decrypt else self.encode(x, k)

def set_seed(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

set_seed(69)

def download_model():
    if not MODEL_PATH.exists():
        print("Downloading model...")
        response = requests.get(MODEL_URL)
        MODEL_PATH.write_bytes(response.content)
        print("Model downloaded successfully!")

def load_encryption_model():
    if not MODEL_PATH.exists():
        download_model()

    with safe_open(MODEL_PATH, framework="pt") as f:
        metadata = f.metadata()
        char_to_idx = {k: int(v) for k, v in json.loads(metadata["char_to_idx"]).items()}
        idx_to_char = {int(k): v for k, v in json.loads(metadata["idx_to_char"]).items()}

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = RajaKripto(len(char_to_idx)).to(device)
    model.init_dicts(char_to_idx, idx_to_char)
    load_model(model, str(MODEL_PATH))
    return model

def text_to_tensor(text, char_to_idx, device=None):
    if device is None:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    return torch.tensor([char_to_idx.get(c, 0) for c in text], dtype=torch.long, device=device)

def text_to_key(text_key, hidden_dim=256):
    key_bytes = text_key.encode('utf-8')
    key_bits = ''.join([format(byte, '08b') for byte in key_bytes])

    while len(key_bits) < hidden_dim:
        key_bits = key_bits + key_bits

    key_bits = key_bits[:hidden_dim]
    key_tensor = torch.tensor([[int(b) for b in key_bits]], dtype=torch.float, device=device)

    return key_tensor

def encrypt_interface(text, key):
    if not text or not key:
        return "Please provide both text and key"
    return encrypt_text(text, key, model)

def tensor_to_b64(tensor):
    shape_info = torch.tensor([tensor.size(1), tensor.size(2)], dtype=torch.int32)
    shape_bytes = shape_info.numpy().tobytes()
    quantized_tensor = (tensor > 0.5).float()
    data_bytes = np.packbits(quantized_tensor.detach().cpu().numpy().astype(bool)).tobytes()
    combined = shape_bytes + data_bytes
    return base64.b64encode(combined).decode('utf-8')

def b64_to_tensor(b64_str):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    combined = base64.b64decode(b64_str.encode('utf-8'))
    shape_bytes = combined[:8]
    data_bytes = combined[8:]
    shape_info = np.frombuffer(shape_bytes, dtype=np.int32)
    bits = np.unpackbits(np.frombuffer(data_bytes, dtype=np.uint8))
    return torch.tensor(bits, dtype=torch.float, device=device).reshape(1, shape_info[0], shape_info[1])

def gHMM():
    text_tensor = text_to_tensor(HMMM, model.char_to_idx).unsqueeze(0)
    key_tensor = text_to_key(SECRET_KEY)
    with torch.no_grad():
        encrypted = model(text_tensor, key_tensor, decrypt=False)
        return tensor_to_b64(encrypted)

def encrypt_text(text, model):
    device = next(model.parameters()).device
    text_tensor = text_to_tensor(text, model.char_to_idx).unsqueeze(0)
    key_tensor = text_to_key(SECRET_KEY)

    with torch.no_grad():
        encoded = model(text_tensor, key_tensor, decrypt=False)
        return tensor_to_b64(encoded)

def decrypt_text(b64_text, decrypt_key, model):
    device = next(model.parameters()).device
    try:
        encrypted_tensor = b64_to_tensor(b64_text)
        key_tensor = text_to_key(decrypt_key)
        
        with torch.no_grad():
            logits = model(encrypted_tensor, key_tensor, decrypt=True)
            pred_indices = torch.argmax(logits, dim=-1)
            decrypted_text = ''.join([model.idx_to_char[idx.item()] for idx in pred_indices[0]])
            return decrypted_text
    except Exception as e:
        return f"Decryption error: {str(e)}"
        
def geeHMM():
    return HEMMM

with gr.Blocks() as demo:
    gr.Markdown("# Text Encryption/Decryption Service")
    
    with gr.Tab("Encrypt"):
        with gr.Row():
            with gr.Column():
                input_text = gr.Textbox(label="Input Text", placeholder="Enter text to encrypt...")
                encrypt_btn = gr.Button("Encrypt")
            with gr.Column():
                output_encrypted = gr.Textbox(label="Encrypted Output (Base64)")
    
    with gr.Tab("Decrypt"):
        with gr.Row():
            with gr.Column():
                input_encrypted = gr.Textbox(label="Encrypted Text (Base64)", placeholder="Enter Base64 text to decrypt...")
                decrypt_key = gr.Textbox(label="Decryption Key", placeholder="Enter the key used for decryption...")
                decrypt_btn = gr.Button("Decrypt")
            with gr.Column():
                output_decrypted = gr.Textbox(label="Decrypted Output")
    
    def encrypt_interface(text):
        if not text:
            return "Please provide text to encrypt"
        try:
            return encrypt_text(text, model)
        except Exception as e:
            return f"Encryption error: {str(e)}"
    
    def decrypt_interface(b64_text, key):
        if not b64_text:
            return "Please provide encrypted text to decrypt"
        if not key:
            return "Please provide a decryption key"
        try:
            return decrypt_text(b64_text, key, model)
        except Exception as e:
            return f"Decryption error: {str(e)}"
    
    encrypt_btn.click(
        encrypt_interface,
        inputs=input_text,
        outputs=output_encrypted
    )
    
    decrypt_btn.click(
        decrypt_interface,
        inputs=[input_encrypted, decrypt_key],
        outputs=output_decrypted
    )

    demo.load(geeHMM, None, gr.Textbox())

if __name__ == "__main__":
    model = load_encryption_model()
    HEMMM = gHMM()
    demo.launch()
