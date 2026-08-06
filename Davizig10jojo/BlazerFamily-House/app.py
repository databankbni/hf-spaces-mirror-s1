import os
import gc
import traceback
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from huggingface_hub import hf_hub_download
from llama_cpp import Llama
from fastapi.middleware.cors import CORSMiddleware

# =====================================================================
# 1. CONFIGURAÇÃO E DOWNLOAD DOS MODELOS (VALIDAÇÃO DE TAMANHO)
# =====================================================================

MODELS_DIR = "/code/models"
os.makedirs(MODELS_DIR, exist_ok=True)

def garantir_modelos():
    modelos = [
        {"repo": "Davizig10jojo/BlazerStandard-4B-GGUF", "file": "blazerstandard-4b-Q6_K.gguf"},
        {"repo": "Davizig10jojo/BlazerTiny-1b-GGUF", "file": "blazertiny-1b-Q6_K.gguf"},
        {"repo": "Davizig10jojo/BlazerNano-0.6b-GGUF", "file": "blazernano-0.6b-Q6_K.gguf"}
    ]
    
    token = os.environ.get("HF_TOKEN")
    
    for m in modelos:
        caminho_final = os.path.join(MODELS_DIR, m["file"])
        
        # Se o arquivo existir mas for menor que 100MB, está corrompido
        if os.path.exists(caminho_final):
            tamanho_mb = os.path.getsize(caminho_final) / (1024 * 1024)
            if tamanho_mb < 100.0:
                print(f"⚠️ Arquivo inválido {m['file']} ({tamanho_mb:.2f} MB). Removendo...")
                try: os.remove(caminho_final)
                except: pass

        if not os.path.exists(caminho_final):
            print(f"📥 Baixando {m['file']} do repositório {m['repo']}...")
            try:
                hf_hub_download(
                    repo_id=m["repo"],
                    filename=m["file"],
                    local_dir=MODELS_DIR,
                    token=token
                )
                tamanho_mb = os.path.getsize(caminho_final) / (1024 * 1024)
                print(f"✅ {m['file']} baixado! Tamanho: {tamanho_mb:.2f} MB")
            except Exception as e:
                print(f"❌ Erro ao baixar {m['file']}: {e}")
        else:
            tamanho_mb = os.path.getsize(caminho_final) / (1024 * 1024)
            print(f"✨ {m['file']} pronto: {tamanho_mb:.2f} MB")

# Garante os modelos no disco persistente do Space
garantir_modelos()

# =====================================================================
# 2. CONFIGURAÇÃO DO FASTAPI E PROTOCOLO CORS
# =====================================================================

app = FastAPI(title="Blazer Family API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_PATHS = {
    "standard": os.path.join(MODELS_DIR, "blazerstandard-4b-Q6_K.gguf"),
    "tiny": os.path.join(MODELS_DIR, "blazertiny-1b-Q6_K.gguf"),
    "nano": os.path.join(MODELS_DIR, "blazernano-0.6b-Q6_K.gguf")
}

# Controle rigoroso de alocação de memória RAM activa
llm_ativa = None
nome_llm_ativa = None

def obter_instancia_modelo(modelo_nome: str) -> Llama:
    """Carrega o modelo na RAM liberando estritamente a memória anterior"""
    global llm_ativa, nome_llm_ativa
    nome_limpo = modelo_nome.lower().strip()
    
    if nome_limpo not in MODEL_PATHS:
        raise HTTPException(status_code=400, detail="Modelo inválido.")
        
    caminho = MODEL_PATHS[nome_limpo]
    if not os.path.exists(caminho):
        raise HTTPException(status_code=500, detail=f"Arquivo do modelo '{nome_limpo}' ausente no disco.")
        
    if nome_llm_ativa == nome_limpo and llm_ativa is not None:
        return llm_ativa
        
    if llm_ativa is not None:
        print(f"🧹 Liberando {nome_llm_ativa} da memória RAM...")
        del llm_ativa
        llm_ativa = None
        gc.collect()

    print(f"🧠 Inicializando {nome_limpo} no motor C++...")
    try:
        # Configuração minimalista para evitar estouro de memória no runtime do Space
        llm_ativa = Llama(
            model_path=caminho,
            n_ctx=512,          # Buffer de contexto curto para respostas rápidas
            n_threads=1,        # Previne sobrecarga na CPU compartilhada do Hugging Face
            n_gpu_layers=0,     # Força o processamento exclusivo por CPU
            use_mmap=False,     # Desativa memória virtual para evitar queda do container
            use_mlock=False,
            verbose=False
        )
        nome_llm_ativa = nome_limpo
        return llm_ativa
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"💥 ERRO AO INICIALIZAR O MODELO {nome_limpo}:\n{error_trace}")
        llm_ativa = None
        nome_llm_ativa = None
        gc.collect()
        raise HTTPException(status_code=500, detail=f"Falha na carga do motor: {str(e)}")

# =====================================================================
# 3. MODELOS DE ENTRADA E SAÍDA (Pydantic)
# =====================================================================

class ChatRequest(BaseModel):
    model: str
    prompt: str
    temperature: Optional[float] = 0.2
    max_tokens: Optional[int] = 120

class ChatResponse(BaseModel):
    model: str
    response: str

# =====================================================================
# 4. ROTAS DE COMUNICAÇÃO DA API
# =====================================================================

@app.get("/")
def home():
    status_modelos = {}
    for k, v in MODEL_PATHS.items():
        if os.path.exists(v):
            size_mb = os.path.getsize(v) / (1024 * 1024)
            status_modelos[k] = f"Pronto e Ativo ({size_mb:.2f} MB)"
        else:
            status_modelos[k] = "Ausente"
            
    return {
        "status": "online",
        "message": "Blazer Family Gateway operacional e seguro.",
        "modelos": status_modelos
    }

@app.post("/v1/chat", response_model=ChatResponse)
def enviar_mensagem(req: ChatRequest):
    nome_modelo = req.model.lower().strip()
    try:
        llm = obter_instancia_modelo(nome_modelo)
        
        # ⚡ CALIBRAÇÃO ESTRETA DO CHAT TEMPLATE (Evita alucinações e textos confusos)
        prompt_formatado = (
            f"<|im_start|>system\n"
            f"Você é o BlazerIA, um assistente inteligente e prestativo. "
            f"Responda estritamente em português (pt-BR), de forma curta, clara e direta. "
            f"Não alucine e não repita o texto do usuário.<|im_end|>\n"
            f"<|im_start|>user\n"
            f"{req.prompt}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )
        
        # Temperatura baixa (0.1 a 0.2) mantém a precisão lógica e elimina gibberish
        temp_segura = req.temperature if req.temperature is not None and req.temperature < 0.3 else 0.15
        
        tokens_seguros = req.max_tokens if req.max_tokens and req.max_tokens < 100 else 60
        if nome_modelo == "standard":
            tokens_seguros = 512

        print(f"Processando resposta no modelo: {nome_modelo}...")
        output = llm(
            prompt=prompt_formatado,
            max_tokens=tokens_seguros,
            temperature=temp_segura,
            stop=["<|im_end|>", "<|im_start|>", "user:", "assistant:", "User:", "Assistant:", "\n\n"]
        )
        
        texto_resposta = output["choices"][0]["text"].strip()
        
        if not texto_resposta:
            texto_resposta = "Não consegui formatar a resposta curta no momento. Pergunte novamente por favor."
            
        return ChatResponse(model=req.model, response=texto_resposta)
        
    except HTTPException as http_err:
        raise http_err
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"💥 ERRO DURANTE A INFERÊNCIA DO MODELO {nome_modelo}:\n{error_trace}")
        raise HTTPException(status_code=500, detail=f"Erro interno no processador local: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=7860, reload=False)