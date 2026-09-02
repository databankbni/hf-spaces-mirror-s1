from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr
import torch
import torch.nn.functional as F
import json
import os
import uuid
import hashlib
import re
import math
import shutil
import time
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

from google_auth import verificar_credential
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from google import genai
from google.genai import types
from sqlalchemy.orm import Session
from sqlalchemy import text as texto_sql
from database import SessionLocal
from models import Usuario, Conversa, Mensagem
from auth import gerar_hash_senha, verificar_senha, criar_token

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


def garantir_coluna_fontes():
    """Adiciona a coluna 'fontes' na tabela mensagens, se ainda não existir."""
    try:
        with SessionLocal() as db:
            db.execute(
                texto_sql(
                    "ALTER TABLE mensagens "
                    "ADD COLUMN IF NOT EXISTS fontes JSON"
                )
            )
            db.commit()
    except Exception as erro:
        print(f"[DB] Não foi possível garantir a coluna 'fontes': {erro}")


garantir_coluna_fontes()


# ============================================================
# CONFIGURAÇÃO
# ============================================================

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DIRETORIO_MOSTRATEC = "./ia_mostratec_final"
DIRETORIO_FEBRACE = "./ia_febrace_final"

# Coloque os PDFs de conhecimento nesta pasta.
# Pode misturar PDFs de slides e PDFs normais.
DIRETORIO_RAG = os.environ.get(
    "RAG_DOCUMENTOS_DIR",
    "./Documentos"
)
DIRETORIO_RAG_INDICE = os.environ.get(
    "RAG_INDEX_DIR",
    "./rag_index"
)
ARQUIVO_RAG_INDICE = os.path.join(DIRETORIO_RAG_INDICE, "indice.json")
ARQUIVO_OCR_CACHE = os.path.join(DIRETORIO_RAG_INDICE, "ocr_cache.json")

HF_TOKEN = os.environ.get("HF_TOKEN", "")
HF_RAG_DATASET = os.environ.get("HF_RAG_DATASET", "")
RAG_PUSH_PDF = os.environ.get("RAG_PUSH_PDF", "false").lower() == "true"

RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "6"))
RAG_CHUNK_CHARS = int(os.environ.get("RAG_CHUNK_CHARS", "1800"))
RAG_CHUNK_OVERLAP = int(os.environ.get("RAG_CHUNK_OVERLAP", "250"))
RAG_MIN_TEXT_CHARS = int(os.environ.get("RAG_MIN_TEXT_CHARS", "80"))

MODELO_GEMINI = "gemini-2.5-flash"
MODELO_EMBEDDING = "gemini-embedding-001"

# Para páginas que são imagens, usamos a capacidade de visão do Gemini
# para extrair o conteúdo textual da página.
RAG_USAR_VISAO_PARA_PAGINAS_IMAGEM = (
    os.environ.get("RAG_USAR_VISAO", "true").lower() == "true"
)

print("Carregando modelos Mostratec...")
tokenizer_mostratec = AutoTokenizer.from_pretrained(DIRETORIO_MOSTRATEC)
modelo_mostratec = AutoModelForSequenceClassification.from_pretrained(
    DIRETORIO_MOSTRATEC
)
modelo_mostratec.eval()

with open(
    os.path.join(DIRETORIO_MOSTRATEC, "categorias.json"),
    "r",
    encoding="utf-8",
) as f:
    mapeamento_mostratec = json.load(f)

print("Carregando modelo Febrace...")
tokenizer_febrace = AutoTokenizer.from_pretrained(DIRETORIO_FEBRACE)
modelo_febrace = AutoModelForSequenceClassification.from_pretrained(
    DIRETORIO_FEBRACE
)
modelo_febrace.eval()

with open(
    os.path.join(DIRETORIO_FEBRACE, "categorias.json"),
    "r",
    encoding="utf-8",
) as f:
    mapeamento_febrace = json.load(f)

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


# ============================================================
# GERAÇÃO DE TEXTO (GEMINI)
# ============================================================

def gerar_texto(prompt: str, max_tokens: int = 700) -> str:
    """Gera texto usando o Gemini."""
    resposta = client.models.generate_content(
        model=MODELO_GEMINI,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=0.2,
        ),
    )

    texto = resposta.text
    if not texto:
        raise RuntimeError("O Gemini retornou uma resposta vazia.")

    return texto.strip()


# ============================================================
# RAG
# ============================================================

rag_indice = {
    "versao": 1,
    "arquivos": {},
    "chunks": [],
}

ocr_cache = {
    "versao": 1,
    "pdfs": {},
}


def _extrair_retry_delay(mensagem: str):
    """Extrai o 'retry in Xs' sugerido pela API do Gemini, se existir."""
    if not mensagem:
        return None

    resultado = re.search(r"retry in ([\d.]+)s", mensagem)

    if resultado:
        try:
            return float(resultado.group(1))
        except ValueError:
            return None

    return None


def _quota_diaria_exaurida(mensagem: str) -> bool:
    """
    True quando o 429 é de cota DIÁRIA do Gemini.

    Cota diária não recupera em segundos/minutos — re-tentar só queima
    tempo de startup. Nesses casos a chamada deve falhar imediatamente.
    """
    if not mensagem:
        return False

    texto = mensagem.lower()

    if "perminute" in texto:
        return False

    marcadores = [
        "perday",
        "limit: 20",
    ]

    return any(marca in texto for marca in marcadores)


def _com_retry(funcao, max_tentativas=4):
    """
    Executa funcao() com backoff exponencial em erros 429/RESOURCE_EXHAUSTED.

    Só reexecuta em rate-limit de curto prazo (ex.: 100/min de embedding),
    que recupera em segundos/minutos. Erros de cota DIÁRIA são propagados
    imediatamente, pois re-tentar não adianta. Qualquer outro erro também é
    propagado imediatamente.
    """
    for tentativa in range(max_tentativas):
        try:
            return funcao()

        except Exception as erro:
            mensagem = str(erro)

            if "429" not in mensagem and "RESOURCE_EXHAUSTED" not in mensagem:
                raise

            if _quota_diaria_exaurida(mensagem):
                print(
                    "[RAG] 429 de cota diária do Gemini, "
                    "pulando sem re-tentar."
                )
                raise

            if tentativa >= max_tentativas - 1:
                raise

            espera = _extrair_retry_delay(mensagem)

            if not espera:
                espera = min(2 ** (tentativa + 1), 30)

            print(
                f"[RAG] 429 detectado, tentativa {tentativa + 1}/"
                f"{max_tentativas}, aguardando {espera:.1f}s..."
            )
            time.sleep(espera)


def normalizar_texto(texto: str) -> str:
    """Limpa espaços sem destruir a estrutura útil do texto."""
    if not texto:
        return ""

    texto = texto.replace("\x00", " ")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def dividir_em_chunks(texto: str, tamanho=RAG_CHUNK_CHARS, overlap=RAG_CHUNK_OVERLAP):
    """
    Divide texto mantendo alguma sobreposição entre os pedaços.
    Tenta respeitar parágrafos antes de cortar por caracteres.
    """
    texto = normalizar_texto(texto)

    if not texto:
        return []

    if len(texto) <= tamanho:
        return [texto]

    paragrafos = [
        p.strip()
        for p in re.split(r"\n\s*\n", texto)
        if p.strip()
    ]

    chunks = []
    atual = ""

    for paragrafo in paragrafos:
        candidato = f"{atual}\n\n{paragrafo}".strip()

        if len(candidato) <= tamanho:
            atual = candidato
            continue

        if atual:
            chunks.append(atual)

        if len(paragrafo) <= tamanho:
            # Mantém o final do chunk anterior como contexto.
            prefixo = ""
            if chunks and overlap > 0:
                prefixo = chunks[-1][-overlap:]

            atual = f"{prefixo}\n\n{paragrafo}".strip()
        else:
            # Parágrafo muito grande: corta em blocos.
            inicio = 0
            while inicio < len(paragrafo):
                fim = inicio + tamanho
                pedaço = paragrafo[inicio:fim].strip()
                if pedaço:
                    chunks.append(pedaço)
                inicio = max(fim - overlap, inicio + 1)

            atual = ""

    if atual:
        chunks.append(atual)

    return chunks


def assinatura_arquivo(caminho: str) -> dict:
    stat = os.stat(caminho)
    hash_sha256 = hashlib.sha256()

    with open(caminho, "rb") as f:
        for pedaco in iter(lambda: f.read(65536), b""):
            hash_sha256.update(pedaco)

    return {
        "tamanho": stat.st_size,
        "modificado_em": stat.st_mtime,
        "sha256": hash_sha256.hexdigest(),
    }


def listar_pdfs_rag():
    pasta = Path(DIRETORIO_RAG)

    if not pasta.exists():
        return []

    return sorted(
        [str(p) for p in pasta.rglob("*.pdf") if p.is_file()]
    )


def extrair_texto_das_paginas(caminho_pdf: str):
    """
    Extrai texto página por página.

    Usa um cache persistente (ocr_cache.json) para não refazer o OCR de
    páginas que já foram lidas em execuções anteriores. Páginas cujo texto
    nativo é curto podem ser enviadas ao Gemini Vision para transformar o
    conteúdo visual em texto.
    """
    if fitz is None:
        raise RuntimeError(
            "PyMuPDF não está instalado. Adicione 'pymupdf' ao requirements.txt."
        )

    assinatura = assinatura_arquivo(caminho_pdf)
    chave_pdf = assinatura["sha256"]

    entrada_cache = ocr_cache.get("pdfs", {}).get(chave_pdf)
    paginas_cache = {}
    if entrada_cache:
        paginas_cache = entrada_cache.get("paginas", {}) or {}

    documento = fitz.open(caminho_pdf)
    paginas = []
    alterado = False

    try:
        for numero_pagina, pagina in enumerate(documento, start=1):
            chave_pagina = str(numero_pagina)

            if chave_pagina in paginas_cache:
                dados_cached = paginas_cache[chave_pagina]
                paginas.append(
                    {
                        "pagina": numero_pagina,
                        "texto": dados_cached.get("texto", ""),
                        "metodo": dados_cached.get("metodo", "texto_pdf"),
                    }
                )
                continue

            texto = normalizar_texto(pagina.get_text("text"))

            # PDF normal: usamos o texto nativo.
            if len(texto) >= RAG_MIN_TEXT_CHARS:
                paginas.append(
                    {
                        "pagina": numero_pagina,
                        "texto": texto,
                        "metodo": "texto_pdf",
                    }
                )
                paginas_cache[chave_pagina] = {
                    "texto": texto,
                    "metodo": "texto_pdf",
                }
                alterado = True
                continue

            # PDF/imagem: usa Gemini Vision como fallback.
            if RAG_USAR_VISAO_PARA_PAGINAS_IMAGEM:
                try:
                    pix = pagina.get_pixmap(
                        matrix=fitz.Matrix(1.8, 1.8),
                        alpha=False,
                    )
                    imagem_bytes = pix.tobytes("png")

                    prompt = """
Transcreva e organize o conteúdo textual desta página de um documento.
Preserve títulos, subtítulos, listas, tabelas e informações importantes.
Não invente conteúdo.
Se houver gráficos ou diagramas com texto legível, inclua os textos e,
quando necessário para compreender a informação, descreva brevemente
o que o elemento visual mostra.
Retorne somente o conteúdo útil para indexação em uma base de conhecimento.
"""

                    resposta = _com_retry(
                        lambda: client.models.generate_content(
                            model=MODELO_GEMINI,
                            contents=[
                                types.Part.from_bytes(
                                    data=imagem_bytes,
                                    mime_type="image/png",
                                ),
                                prompt,
                            ],
                        )
                    )

                    texto_visual = normalizar_texto(resposta.text or "")

                    if texto_visual:
                        paginas.append(
                            {
                                "pagina": numero_pagina,
                                "texto": texto_visual,
                                "metodo": "gemini_vision",
                            }
                        )
                        paginas_cache[chave_pagina] = {
                            "texto": texto_visual,
                            "metodo": "gemini_vision",
                        }
                        alterado = True

                except Exception as erro:
                    print(
                        f"[RAG] Falha ao processar página {numero_pagina} "
                        f"com visão em '{caminho_pdf}': {erro}"
                    )

    finally:
        documento.close()

    if alterado:
        if "pdfs" not in ocr_cache:
            ocr_cache["pdfs"] = {}

        ocr_cache["pdfs"][chave_pdf] = {
            "assinatura": {
                "tamanho": assinatura["tamanho"],
                "modificado_em": assinatura["modificado_em"],
                "sha256": assinatura["sha256"],
            },
            "paginas": paginas_cache,
        }
        salvar_cache_ocr()

    return paginas


def gerar_embeddings(textos, task_type):
    """
    Gera embeddings em lotes para evitar uma chamada por chunk.
    """
    if not textos:
        return []

    embeddings = []
    tamanho_lote = 32

    for inicio in range(0, len(textos), tamanho_lote):
        lote = textos[inicio:inicio + tamanho_lote]

        resultado = _com_retry(
            lambda: client.models.embed_content(
                model=MODELO_EMBEDDING,
                contents=lote,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                ),
            )
        )

        for embedding in resultado.embeddings:
            embeddings.append(list(embedding.values))

    return embeddings


def normalizar_vetor(vetor):
    norma = math.sqrt(sum(float(x) * float(x) for x in vetor))

    if norma == 0:
        return vetor

    return [float(x) / norma for x in vetor]


def similaridade_cosseno(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0

    return sum(x * y for x, y in zip(a, b))


def salvar_indice_rag():
    os.makedirs(DIRETORIO_RAG_INDICE, exist_ok=True)

    temporario = ARQUIVO_RAG_INDICE + ".tmp"

    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(rag_indice, f, ensure_ascii=False)

    os.replace(temporario, ARQUIVO_RAG_INDICE)


def hf_sync_disponivel():
    """True quando o Space tem token e dataset configurados."""
    return bool(HF_TOKEN and HF_RAG_DATASET)


def baixar_indice_do_dataset():
    """Baixa indice.json do dataset privado para o caminho local padrão."""
    try:
        caminho_cache = hf_hub_download(
            repo_id=HF_RAG_DATASET,
            filename="indice.json",
            repo_type="dataset",
            token=HF_TOKEN,
        )
    except Exception as erro:
        print(f"[HF] indice.json não disponível no dataset: {erro}")
        return False

    os.makedirs(DIRETORIO_RAG_INDICE, exist_ok=True)
    shutil.copyfile(caminho_cache, ARQUIVO_RAG_INDICE)
    print("[HF] indice.json carregado do dataset privado.")
    return True


def baixar_pdfs_do_dataset():
    """Baixa todos os PDFs do dataset privado para DIRETORIO_RAG."""
    try:
        arquivos = HfApi(token=HF_TOKEN).list_repo_files(
            HF_RAG_DATASET,
            repo_type="dataset",
        )
    except Exception as erro:
        print(f"[HF] Falha ao listar arquivos do dataset: {erro}")
        return

    baixados = 0

    for nome in arquivos:
        if not nome.lower().endswith(".pdf"):
            continue

        try:
            caminho_cache = hf_hub_download(
                repo_id=HF_RAG_DATASET,
                filename=nome,
                repo_type="dataset",
                token=HF_TOKEN,
            )

            destino = Path(DIRETORIO_RAG) / nome
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(caminho_cache, destino)
            baixados += 1

        except Exception as erro:
            print(f"[HF] Falha ao baixar '{nome}': {erro}")

    if baixados:
        print(f"[HF] {baixados} PDF(s) baixado(s) do dataset.")


def enviar_pdfs_para_dataset():
    """
    Envia PDFs locais que ainda não existem no dataset.

    Serve apenas para a primeira sincronização/semeadura (RAG_PUSH_PDF=true).
    Depois de desligar a flag, o dataset passa a ser a fonte oficial dos PDFs.
    """
    if not RAG_PUSH_PDF or not hf_sync_disponivel():
        return

    try:
        api = HfApi(token=HF_TOKEN)
        existentes = set(
            api.list_repo_files(
                HF_RAG_DATASET,
                repo_type="dataset",
            )
        )
    except Exception as erro:
        print(f"[HF] Falha ao listar arquivos para envio: {erro}")
        return

    enviados = 0

    for caminho in listar_pdfs_rag():
        rel = os.path.relpath(caminho, DIRETORIO_RAG).replace("\\", "/")

        if rel in existentes:
            continue

        try:
            api.upload_file(
                path_or_fileobj=caminho,
                path_in_repo=rel,
                repo_id=HF_RAG_DATASET,
                repo_type="dataset",
            )
            existentes.add(rel)
            enviados += 1

        except Exception as erro:
            print(f"[HF] Falha ao enviar '{rel}': {erro}")

    if enviados:
        print(f"[HF] {enviados} PDF(s) enviado(s) ao dataset.")


def enviar_indice_para_dataset():
    """Envia o indice.json para o dataset somente após a construção completa."""
    if not hf_sync_disponivel():
        return

    try:
        HfApi(token=HF_TOKEN).upload_file(
            path_or_fileobj=ARQUIVO_RAG_INDICE,
            path_in_repo="indice.json",
            repo_id=HF_RAG_DATASET,
            repo_type="dataset",
        )
        print("[HF] indice.json enviado ao dataset privado.")

    except Exception as erro:
        print(f"[HF] Falha ao enviar indice.json ao dataset: {erro}")


def carregar_cache_ocr():
    """Carrega o cache de OCR do arquivo local para a memória."""
    global ocr_cache

    if not os.path.exists(ARQUIVO_OCR_CACHE):
        return

    try:
        with open(ARQUIVO_OCR_CACHE, "r", encoding="utf-8") as f:
            dados = json.load(f)

        if dados.get("versao") == 1:
            ocr_cache = dados

        print(
            f"[RAG] Cache de OCR carregado: "
            f"{len(ocr_cache.get('pdfs', {}))} PDF(s)."
        )

    except Exception as erro:
        print(f"[RAG] Não foi possível carregar o cache de OCR: {erro}")


def salvar_cache_ocr():
    """Grava o cache de OCR localmente de forma atômica."""
    os.makedirs(DIRETORIO_RAG_INDICE, exist_ok=True)

    temporario = ARQUIVO_OCR_CACHE + ".tmp"

    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(ocr_cache, f, ensure_ascii=False)

    os.replace(temporario, ARQUIVO_OCR_CACHE)


def baixar_cache_ocr_do_dataset():
    """Baixa ocr_cache.json do dataset privado para o caminho local padrão."""
    try:
        caminho_cache = hf_hub_download(
            repo_id=HF_RAG_DATASET,
            filename="ocr_cache.json",
            repo_type="dataset",
            token=HF_TOKEN,
        )
    except Exception as erro:
        print(f"[HF] ocr_cache.json não disponível no dataset: {erro}")
        return False

    os.makedirs(DIRETORIO_RAG_INDICE, exist_ok=True)
    shutil.copyfile(caminho_cache, ARQUIVO_OCR_CACHE)
    print("[HF] ocr_cache.json carregado do dataset privado.")
    return True


def enviar_cache_ocr_para_dataset():
    """Envia o cache de OCR (parcial ou completo) para o dataset privado."""
    if not hf_sync_disponivel():
        return

    try:
        HfApi(token=HF_TOKEN).upload_file(
            path_or_fileobj=ARQUIVO_OCR_CACHE,
            path_in_repo="ocr_cache.json",
            repo_id=HF_RAG_DATASET,
            repo_type="dataset",
        )
        print("[HF] ocr_cache.json enviado ao dataset privado.")

    except Exception as erro:
        print(f"[HF] Falha ao enviar ocr_cache.json ao dataset: {erro}")


def podar_cache_ocr(pdfs):
    """Remove do cache entradas de PDFs que não existem mais em DIRETORIO_RAG."""
    chaves_atuais = set()

    for caminho in pdfs:
        try:
            chaves_atuais.add(assinatura_arquivo(caminho)["sha256"])
        except Exception:
            pass

    cache_pdfs = ocr_cache.get("pdfs", {})
    removidas = [chave for chave in cache_pdfs if chave not in chaves_atuais]

    for chave in removidas:
        del cache_pdfs[chave]

    if removidas:
        print(
            f"[RAG] Cache de OCR: {len(removidas)} entrada(s) removida(s)."
        )
        salvar_cache_ocr()


def sincronizar_rag_com_dataset():
    if not hf_sync_disponivel():
        return

    baixar_pdfs_do_dataset()
    enviar_pdfs_para_dataset()
    baixar_indice_do_dataset()
    baixar_cache_ocr_do_dataset()


def carregar_indice_rag():
    global rag_indice

    if not os.path.exists(ARQUIVO_RAG_INDICE):
        return False

    try:
        with open(ARQUIVO_RAG_INDICE, "r", encoding="utf-8") as f:
            dados = json.load(f)

        if dados.get("versao") != 1:
            return False

        rag_indice = dados

        arquivos_atuais = {
            caminho: assinatura_arquivo(caminho)
            for caminho in listar_pdfs_rag()
        }

        arquivos_indexados = rag_indice.get("arquivos", {})

        if set(arquivos_atuais.keys()) != set(arquivos_indexados.keys()):
            return False

        for caminho, assinatura in arquivos_atuais.items():
            anterior = arquivos_indexados.get(caminho)

            if anterior is None:
                return False

            if anterior.get("sha256"):
                if anterior.get("sha256") != assinatura["sha256"]:
                    return False
            elif (
                anterior.get("tamanho") != assinatura["tamanho"]
                or anterior.get("modificado_em") != assinatura["modificado_em"]
            ):
                return False

        print(
            f"[RAG] Índice carregado do cache: "
            f"{len(rag_indice.get('chunks', []))} chunks."
        )
        return True

    except Exception as erro:
        print(f"[RAG] Não foi possível carregar o índice: {erro}")
        return False


def construir_indice_rag():
    """
    Processa todos os PDFs e cria o índice vetorial.

    Essa função é chamada somente quando o índice não existe ou
    quando algum PDF foi adicionado/modificado/removido.
    """
    global rag_indice

    pdfs = listar_pdfs_rag()

    if not pdfs:
        print(f"[RAG] Nenhum PDF encontrado em: {DIRETORIO_RAG}")
        rag_indice = {
            "versao": 1,
            "arquivos": {},
            "chunks": [],
        }
        salvar_indice_rag()
        return

    carregar_cache_ocr()

    print(f"[RAG] Encontrados {len(pdfs)} PDFs.")

    novos_chunks = []
    arquivos = {}

    for numero, caminho_pdf in enumerate(pdfs, start=1):
        print(
            f"[RAG] Processando PDF {numero}/{len(pdfs)}: {caminho_pdf}"
        )

        try:
            paginas = extrair_texto_das_paginas(caminho_pdf)

            arquivos[caminho_pdf] = assinatura_arquivo(caminho_pdf)

            for pagina in paginas:
                chunks = dividir_em_chunks(pagina["texto"])

                for indice_chunk, chunk in enumerate(chunks):
                    novos_chunks.append(
                        {
                            "id": str(uuid.uuid4()),
                            "arquivo": os.path.basename(caminho_pdf),
                            "caminho": caminho_pdf,
                            "pagina": pagina["pagina"],
                            "metodo_extracao": pagina["metodo"],
                            "chunk": indice_chunk,
                            "texto": chunk,
                        }
                    )

        except Exception as erro:
            print(f"[RAG] Erro no PDF '{caminho_pdf}': {erro}")

    podar_cache_ocr(pdfs)

    if not novos_chunks:
        print("[RAG] Nenhum texto foi extraído dos PDFs.")
        rag_indice = {
            "versao": 1,
            "arquivos": arquivos,
            "chunks": [],
        }
        salvar_indice_rag()
        return

    salvar_cache_ocr()
    enviar_cache_ocr_para_dataset()

    print(
        f"[RAG] Gerando embeddings para "
        f"{len(novos_chunks)} chunks..."
    )

    textos = [item["texto"] for item in novos_chunks]
    embeddings = gerar_embeddings(
        textos,
        task_type="RETRIEVAL_DOCUMENT",
    )

    if len(embeddings) != len(novos_chunks):
        raise RuntimeError(
            "Quantidade de embeddings diferente da quantidade de chunks."
        )

    for item, embedding in zip(novos_chunks, embeddings):
        item["embedding"] = normalizar_vetor(embedding)

    rag_indice = {
        "versao": 1,
        "arquivos": arquivos,
        "chunks": novos_chunks,
    }

    salvar_indice_rag()
    enviar_indice_para_dataset()

    print(
        f"[RAG] Índice criado com {len(novos_chunks)} chunks."
    )


def inicializar_rag():
    if hf_sync_disponivel():
        try:
            sincronizar_rag_com_dataset()
        except Exception as erro:
            print(f"[HF] Falha na sincronização com o dataset: {erro}")

    if carregar_indice_rag():
        return

    print("[RAG] Cache inexistente ou desatualizado.")
    construir_indice_rag()


def buscar_no_rag(pergunta: str, top_k=RAG_TOP_K):
    if not rag_indice.get("chunks"):
        return []

    resultado = client.models.embed_content(
        model=MODELO_EMBEDDING,
        contents=pergunta,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
        ),
    )

    vetor_pergunta = normalizar_vetor(
        list(resultado.embeddings[0].values)
    )

    resultados = []

    for item in rag_indice["chunks"]:
        similaridade = similaridade_cosseno(
            vetor_pergunta,
            item.get("embedding", []),
        )

        resultados.append(
            {
                "similaridade": similaridade,
                "arquivo": item["arquivo"],
                "pagina": item["pagina"],
                "metodo_extracao": item.get(
                    "metodo_extracao",
                    "texto_pdf",
                ),
                "texto": item["texto"],
            }
        )

    resultados.sort(
        key=lambda item: item["similaridade"],
        reverse=True,
    )

    return resultados[:top_k]


def formatar_contexto_rag(resultados):
    if not resultados:
        return (
            "Nenhuma fonte relevante foi encontrada na base de "
            "conhecimento."
        )

    blocos = []

    for i, item in enumerate(resultados, start=1):
        blocos.append(
            f"""[FONTE {i}]
Arquivo: {item['arquivo']}
Página: {item['pagina']}
Trecho:
{item['texto']}
"""
        )

    return "\n\n".join(blocos)


def montar_prompt_com_rag(
    contexto_feira,
    historico_formatado,
    mensagem,
    resultados_rag,
):
    contexto_rag = formatar_contexto_rag(resultados_rag)

    return f"""
{contexto_feira}

Você está respondendo a um usuário do SFAI.

REGRAS IMPORTANTES:
- Quando a pergunta estiver relacionada aos documentos da base de conhecimento,
  use prioritariamente as fontes recuperadas abaixo.
- Não invente uma informação e apresente-a como se estivesse nos documentos.
- Se as fontes não forem suficientes para responder, diga claramente que os
  materiais recuperados não são suficientes e, somente quando apropriado,
  complemente com conhecimento geral.
- Preserve o sentido das fontes e não distorça suas orientações.
- Quando uma informação importante vier dos documentos, cite o arquivo e a
  página de forma natural, por exemplo: "(Fonte: nome.pdf, p. 3)".
- Não diga que você "consultou um banco vetorial" ou revele detalhes internos
  do sistema ao usuário.

=== FONTES RECUPERADAS PELO RAG ===
{contexto_rag}

=== HISTÓRICO ===
{historico_formatado}

=== NOVA MENSAGEM ===
Usuário: {mensagem}

Responda naturalmente considerando o contexto anterior e as fontes recuperadas.
"""


# Inicializa o índice depois das funções existirem.
# Se você quiser impedir a indexação durante testes, defina RAG_AUTO_INDEX=false.
if os.environ.get("RAG_AUTO_INDEX", "true").lower() == "true":
    try:
        inicializar_rag()
    except Exception as erro:
        print(f"[RAG] Falha ao inicializar: {erro}")
        print("[RAG] O restante da API continuará funcionando.")


# ============================================================
# BANCO / MODELOS
# ============================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class RequisicaoProjeto(BaseModel):
    usuario_id: int
    conversa_id: str | None = None
    resumo: str = ""
    feira: str = ""
    modo: str = "conversa"
    mensagem: str = ""


class RequisicaoCadastro(BaseModel):
    nome: str
    email: EmailStr
    senha: str


class RequisicaoLogin(BaseModel):
    email: EmailStr
    senha: str


class RequisicaoGoogle(BaseModel):
    credential: str


def formatar_historico_db(mensagens_db):
    if not mensagens_db:
        return "Nenhum histórico disponível."

    linhas = []

    for msg in mensagens_db:
        if msg.remetente == "user":
            linhas.append(f"Usuário: {msg.conteudo}")
        elif msg.remetente == "assistant":
            linhas.append(f"Assistente: {msg.conteudo}")

    return "\n".join(linhas)


def gerar_titulo_conversa(primeira_mensagem: str) -> str:
    try:
        prompt_titulo = (
            "Resuma a mensagem a seguir em até 4 palavras para servir "
            "de título de um chat. Não use aspas, responda apenas o título "
            f"direto: {primeira_mensagem}"
        )

        return gerar_texto(prompt_titulo, max_tokens=30).replace('"', "")

    except Exception:
        return "Nova conversa"


# ============================================================
# ROTAS DO HISTÓRICO
# ============================================================

@app.get("/conversas/{usuario_id}")
def listar_conversas(
    usuario_id: int,
    db: Session = Depends(get_db),
):
    conversas = (
        db.query(Conversa)
        .filter(Conversa.usuario_id == usuario_id)
        .order_by(Conversa.atualizado_em.desc())
        .all()
    )

    return [
        {
            "id": str(c.id),
            "titulo": c.titulo or "Nova conversa",
            "atualizado_em": c.atualizado_em,
        }
        for c in conversas
    ]


@app.get("/conversas/{conversa_id}/mensagens")
def obter_mensagens_conversa(
    conversa_id: str,
    db: Session = Depends(get_db),
):
    try:
        id_validado = uuid.UUID(conversa_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="ID de conversa inválido.",
        )

    conversa = (
        db.query(Conversa)
        .filter(Conversa.id == id_validado)
        .first()
    )

    if not conversa:
        raise HTTPException(
            status_code=404,
            detail="Conversa não encontrada",
        )

    return [
        {
            "remetente": m.remetente,
            "conteudo": m.conteudo,
            "fontes": m.fontes or [],
            "horario": m.horario,
        }
        for m in conversa.mensagens
    ]


# ============================================================
# ROTAS DO RAG
# ============================================================

@app.get("/rag/status")
def status_rag():
    return {
        "ativo": True,
        "diretorio": DIRETORIO_RAG,
        "pdfs": len(rag_indice.get("arquivos", {})),
        "chunks": len(rag_indice.get("chunks", [])),
    }


@app.post("/rag/reindexar")
def reindexar_rag():
    try:
        construir_indice_rag()

        return {
            "sucesso": True,
            "pdfs": len(rag_indice.get("arquivos", {})),
            "chunks": len(rag_indice.get("chunks", [])),
        }

    except Exception as erro:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao reindexar RAG: {erro}",
        )


@app.get("/documentos/{nome_arquivo}")
def servir_documento(nome_arquivo: str):
    nome_seguro = Path(nome_arquivo).name
    raiz = Path(DIRETORIO_RAG).resolve()
    caminho = (raiz / nome_seguro).resolve()

    if caminho.parent != raiz or not caminho.is_file():
        raise HTTPException(
            status_code=404,
            detail="Documento não encontrado.",
        )

    return FileResponse(caminho, media_type="application/pdf")


# ============================================================
# ROTA DE INTELIGÊNCIA ARTIFICIAL E CHAT
# ============================================================

@app.post("/classificar")
def classificar_resumo_api(
    dados: RequisicaoProjeto,
    db: Session = Depends(get_db),
):
    modo = dados.modo
    feira_selecionada = dados.feira.strip().upper()
    mensagem = dados.mensagem
    texto = dados.resumo
    usuario_id = dados.usuario_id
    conversa_id_str = dados.conversa_id

    if conversa_id_str:
        try:
            id_conversa_uuid = uuid.UUID(conversa_id_str)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="ID de conversa inválido.",
            )

        conversa = (
            db.query(Conversa)
            .filter(Conversa.id == id_conversa_uuid)
            .first()
        )

        if not conversa:
            raise HTTPException(
                status_code=404,
                detail="Conversa informada não encontrada.",
            )

    else:
        titulo_gerado = gerar_titulo_conversa(
            mensagem if modo == "conversa" else texto
        )

        conversa = Conversa(
            usuario_id=usuario_id,
            titulo=titulo_gerado,
        )

        db.add(conversa)
        db.commit()
        db.refresh(conversa)

        id_conversa_uuid = conversa.id

    conteudo_usuario = (
        mensagem
        if modo == "conversa"
        else f"Classificar resumo: {texto}"
    )

    nova_msg_user = Mensagem(
        conversa_id=id_conversa_uuid,
        remetente="user",
        conteudo=conteudo_usuario,
    )

    db.add(nova_msg_user)
    db.commit()

    # ========================================================
    # MODO CONVERSA + RAG
    # ========================================================

    if modo == "conversa":
        historico_formatado = formatar_historico_db(
            conversa.mensagens
        )

        if feira_selecionada == "FEBRACE":
            contexto_feira = (
                "Você é um assistente virtual prestativo para a feira "
                "de ciências FEBRACE (Feira Brasileira de Ciências e "
                "Engenharia). Você conhece as regras da USP, o processo "
                "de submissão nacional e os critérios da Febrace."
            )

        elif feira_selecionada == "MOSTRATEC":
            contexto_feira = (
                "Você é um assistente virtual prestativo para a feira "
                "de ciências MOSTRATEC. Você conhece as regras da "
                "Fundação Liberato, critérios de avaliação locais e "
                "categorias específicas da Mostratec."
            )

        else:
            contexto_feira = (
                "Você é um assistente virtual de inteligência artificial "
                "geral. Ajude o usuário respondendo suas dúvidas de forma "
                "prestativa, clara e objetiva."
            )

        # O RAG é consultado ANTES do Gemini.
        try:
            resultados_rag = buscar_no_rag(mensagem)

        except Exception as erro:
            print(f"[RAG] Erro na busca: {erro}")
            resultados_rag = []

        prompt_conversa = montar_prompt_com_rag(
            contexto_feira=contexto_feira,
            historico_formatado=historico_formatado,
            mensagem=mensagem,
            resultados_rag=resultados_rag,
        )

        resposta_ia = gerar_texto(
            prompt_conversa,
            max_tokens=900,
        )

        nova_msg_assistant = Mensagem(
            conversa_id=id_conversa_uuid,
            remetente="assistant",
            conteudo=resposta_ia,
        )

        db.add(nova_msg_assistant)
        db.commit()

        return {
            "conversa_id": str(id_conversa_uuid),
            "titulo": conversa.titulo,
            "resultado": resposta_ia,
            "fontes_rag": [
                {
                    "arquivo": item["arquivo"],
                    "pagina": item["pagina"],
                    "similaridade": round(
                        item["similaridade"],
                        4,
                    ),
                }
                for item in resultados_rag
            ],
        }

    # ========================================================
    # MODO CLASSIFICAÇÃO
    # ========================================================

    if feira_selecionada == "FEBRACE":
        tokenizer_ativo = tokenizer_febrace
        modelo_ativo = modelo_febrace
        mapeamento_ativo = mapeamento_febrace
        instrucao_avaliador = (
            "Você é um avaliador técnico especializado na FEBRACE "
            "(Feira Brasileira de Ciências e Engenharia)."
        )

    elif feira_selecionada == "MOSTRATEC":
        tokenizer_ativo = tokenizer_mostratec
        modelo_ativo = modelo_mostratec
        mapeamento_ativo = mapeamento_mostratec
        instrucao_avaliador = (
            "Você é um avaliador técnico especializado na feira "
            "de ciências Mostratec."
        )

    else:
        return {
            "erro": (
                "Para classificação de projetos, selecione "
                "FEBRACE ou MOSTRATEC."
            )
        }

    inputs = tokenizer_ativo(
        texto,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=512,
    )

    with torch.no_grad():
        outputs = modelo_ativo(**inputs)

    probabilidades = F.softmax(outputs.logits, dim=-1)
    top_3 = torch.topk(probabilidades, k=3)

    indices_top_3 = top_3.indices.squeeze(0).tolist()

    categorias_top3 = [
        mapeamento_ativo[str(idx)]
        for idx in indices_top_3
    ]

    cat_1 = categorias_top3[0]
    cat_2 = categorias_top3[1]
    cat_3 = categorias_top3[2]

    prompt_instrucao = (
        f"{instrucao_avaliador}\n"
        "Sua única tarefa é analisar o resumo de um projeto e "
        "fornecer a classificação correta com base nas previsões "
        "geradas pelo nosso modelo estatístico.\n"
        "DADOS DA CLASSIFICAÇÃO ENVIADOS PELO MODELO DE IA:\n"
        f"- 1º Lugar (Classificação Principal): {cat_1}\n"
        f"- 2º Lugar (Alternativa sugerida pelo algoritmo): {cat_2}\n"
        f"- 3º Lugar (Alternativa sugerida pelo algoritmo): {cat_3}\n"
        f"RESUMO DO PROJETO ANALISADO:\n{texto}\n"
        "REGRAS DE CONSTRUÇÃO DA RESPOSTA (SIGA ESTRITAMENTE):\n"
        "1. ESTRUTURA CRÍTICA: A PRIMEIRA PALAVRA do texto completo "
        "deve ser obrigatoriamente o nome da categoria de 1º Lugar "
        "em negrito. Exemplo: \"**Ciências da Computação**: "
        "O projeto apresenta...\".\n"
        "2. SEM ENROLAÇÃO: Proibido incluir saudações, mensagens "
        "de boas-vindas, elogios ou textos introdutórios vazios. "
        "Vá direto ao ponto técnico.\n"
        "3. JUSTIFICATIVA PRINCIPAL: Logo após a primeira palavra, "
        "apresente a explicação clara, lógica e objetiva de por que "
        "o resumo se enquadra nessa categoria principal.\n"
        "4. FILTRO DE COERÊNCIA DO TOP 3: Avalie criticamente se "
        "as categorias de 2º e 3º lugar guardam alguma relação "
        "coerente e lógica com o resumo do projeto.\n"
        "5. Adicione apenas as alternativas que forem estritamente "
        "coerentes de fato.\n"
    )

    resposta_ia = gerar_texto(
        prompt_instrucao,
        max_tokens=700,
    )

    nova_msg_assistant = Mensagem(
        conversa_id=id_conversa_uuid,
        remetente="assistant",
        conteudo=resposta_ia,
    )

    db.add(nova_msg_assistant)
    db.commit()

    return {
        "conversa_id": str(id_conversa_uuid),
        "titulo": conversa.titulo,
        "resultado": resposta_ia,
        "metadados_top3": [cat_1, cat_2, cat_3],
    }


# ============================================================
# ROTAS DE AUTENTICAÇÃO
# ============================================================

@app.post("/cadastro")
def cadastrar_usuario(dados: RequisicaoCadastro):
    db: Session = SessionLocal()

    try:
        usuario_existente = (
            db.query(Usuario)
            .filter(Usuario.email == dados.email)
            .first()
        )

        if usuario_existente:
            return {
                "sucesso": False,
                "mensagem": "Este e-mail já está cadastrado.",
            }

        senha_hash = gerar_hash_senha(dados.senha)

        usuario = Usuario(
            nome=dados.nome,
            email=dados.email,
            senha_hash=senha_hash,
        )

        db.add(usuario)
        db.commit()
        db.refresh(usuario)

        token = criar_token(usuario.id)

        return {
            "sucesso": True,
            "token": token,
            "usuario": {
                "id": usuario.id,
                "nome": usuario.nome,
                "email": usuario.email,
            },
        }

    finally:
        db.close()


@app.post("/login")
def login(dados: RequisicaoLogin):
    db: Session = SessionLocal()

    try:
        usuario = (
            db.query(Usuario)
            .filter(Usuario.email == dados.email)
            .first()
        )

        if (
            usuario is None
            or not verificar_senha(
                dados.senha,
                usuario.senha_hash,
            )
        ):
            return {
                "sucesso": False,
                "mensagem": "E-mail ou senha inválidos.",
            }

        token = criar_token(usuario.id)

        return {
            "sucesso": True,
            "token": token,
            "usuario": {
                "id": usuario.id,
                "nome": usuario.nome,
                "email": usuario.email,
                "foto": usuario.foto,
            },
        }

    finally:
        db.close()


@app.post("/login/google")
def login_google(dados: RequisicaoGoogle):
    db: Session = SessionLocal()

    try:
        info = verificar_credential(dados.credential)

        usuario = (
            db.query(Usuario)
            .filter(Usuario.email == info["email"])
            .first()
        )

        if usuario is None:
            usuario = Usuario(
                nome=info["nome"],
                email=info["email"],
                google_id=info["google_id"],
                foto=info["foto"],
            )

            db.add(usuario)
            db.commit()
            db.refresh(usuario)

        token = criar_token(usuario.id)

        return {
            "sucesso": True,
            "token": token,
            "usuario": {
                "id": usuario.id,
                "nome": info["nome"],
                "email": info["email"],
                "foto": info["foto"],
            },
        }

    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )