from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import torch
import torch.nn.functional as F
import json
import os
import uuid
from google_auth import verificar_credential
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from google import genai
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Usuario, Conversa, Mensagem
from auth import (
    gerar_hash_senha,
    verificar_senha,
    criar_token
)

# Modifique a linha do app para desativar os docs públicos
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LINK_TEMPESTADE_IDEIAS = "FrontEnd/chatbot/Documentos/tempestade-de-ideias.pdf"
LINK_METODOLOGIA_CIENTIFICA = "FrontEnd/chatbot/Documentos/metodologia-cientifica.pdf"
LINK_DICAS_ORIENTACAO = "FrontEnd/chatbot/Documentos/dicas-de-orientacao.pdf"

DIRETORIO_MOSTRATEC = "./ia_mostratec_final"
DIRETORIO_FEBRACE = "./ia_febrace_final"

print("Carregando modelo Mostratec...")
tokenizer_mostratec = AutoTokenizer.from_pretrained(DIRETORIO_MOSTRATEC)
modelo_mostratec = AutoModelForSequenceClassification.from_pretrained(DIRETORIO_MOSTRATEC)
modelo_mostratec.eval()

with open(os.path.join(DIRETORIO_MOSTRATEC, "categorias.json"), "r", encoding="utf-8") as f:
    mapeamento_mostratec = json.load(f)

print("Carregando modelo Febrace...")
tokenizer_febrace = AutoTokenizer.from_pretrained(DIRETORIO_FEBRACE)
modelo_febrace = AutoModelForSequenceClassification.from_pretrained(DIRETORIO_FEBRACE)
modelo_febrace.eval()

with open(os.path.join(DIRETORIO_FEBRACE, "categorias.json"), "r", encoding="utf-8") as f:
    mapeamento_febrace = json.load(f)

client = genai.Client(
    api_key=os.environ.get("GEMINI_API_KEY")
)

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
        prompt_titulo = f"Resuma a mensagem a seguir em até 4 palavras para servir de título de um chat. Não use aspas, responda apenas o título direto: {primeira_mensagem}"
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_titulo
        )
        return response.text.strip().replace('"', '')
    except Exception:
        return "Nova conversa"


# --- ROTAS DO HISTÓRICO ---

@app.get("/conversas/{usuario_id}")
def listar_conversas(usuario_id: int, db: Session = Depends(get_db)):
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
            "atualizado_em": c.atualizado_em
        }
        for c in conversas
    ]


@app.get("/conversas/{conversa_id}/mensagens")
def obter_mensagens_conversa(conversa_id: str, db: Session = Depends(get_db)):
    try:
        id_validado = uuid.UUID(conversa_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de conversa inválido.")

    conversa = db.query(Conversa).filter(Conversa.id == id_validado).first()
    if not conversa:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")
    
    return [
        {
            "remetente": m.remetente,
            "conteudo": m.conteudo,
            "horario": m.horario
        }
        for m in conversa.mensagens
    ]


# --- ROTA DE INTELIGÊNCIA ARTIFICIAL E CHAT ---

@app.post("/classificar")
def classificar_resumo_api(dados: RequisicaoProjeto, db: Session = Depends(get_db)):
    modo = dados.modo
    feira_selecionada = dados.feira.strip().upper()
    mensagem = dados.mensagem
    texto = dados.resumo
    usuario_id = dados.usuario_id
    conversa_id_str = dados.conversa_id

    if conversa_id_str:
        id_conversa_uuid = uuid.UUID(conversa_id_str)
        conversa = db.query(Conversa).filter(Conversa.id == id_conversa_uuid).first()
        if not conversa:
            raise HTTPException(status_code=404, detail="Conversa informada não encontrada.")
    else:
        titulo_gerado = gerar_titulo_conversa(mensagem if modo == "conversa" else texto)
        conversa = Conversa(usuario_id=usuario_id, titulo=titulo_gerado)
        db.add(conversa)
        db.commit()
        db.refresh(conversa)
        id_conversa_uuid = conversa.id

    conteudo_usuario = mensagem if modo == "conversa" else f"Classificar resumo: {texto}"
    nova_msg_user = Mensagem(
        conversa_id=id_conversa_uuid,
        remetente="user",
        conteudo=conteudo_usuario
    )
    db.add(nova_msg_user)
    db.commit()

    # MODO CONVERSA
    if modo == "conversa":
        historico_formatado = formatar_historico_db(conversa.mensagens)
        
        regras_links = ""
        if LINK_TEMPESTADE_IDEIAS:
            regras_links += f"- Se o assunto principal for Tempestade de ideias (Brainstorming), adicione obrigatoriamente no final da resposta a tag: `[DRIVE_LINK: {LINK_TEMPESTADE_IDEIAS} | Material de Apoio - Tempestade de Ideias]`\n"
        if LINK_METODOLOGIA_CIENTIFICA:
            regras_links += f"- Se o assunto principal for Metodologia científica, adicione obrigatoriamente no final da resposta a tag: `[DRIVE_LINK: {LINK_METODOLOGIA_CIENTIFICA} | Guia de Metodologia Científica]`\n"
        if LINK_DICAS_ORIENTACAO:
            regras_links += f"- Se o assunto principal for Dicas de orientação (ou como orientar/ser orientado), adicione obrigatoriamente no final da resposta a tag: `[DRIVE_LINK: {LINK_DICAS_ORIENTACAO} | Manual de Dicas de Orientação]`\n"

        if feira_selecionada == "FEBRACE":
            contexto_feira = "Você é um assistente virtual prestativo para a feira de ciências FEBRACE (Feira Brasileira de Ciências e Engenharia). Você conhece as regras da USP, o processo de submissão nacional e os critérios da Febrace."
        elif feira_selecionada == "MOSTRATEC":
            contexto_feira = "Você é um assistente virtual prestativo para a feira de ciências MOSTRATEC. Você conhece as regras da Fundação Liberato, critérios de avaliação locais e categorias específicas da Mostratec."
        else:
            contexto_feira = "Você é um assistente virtual de inteligência artificial geral. Ajude o usuário respondendo suas dúvidas de forma prestativa, clara e objetiva."

        prompt_conversa = f"{contexto_feira}\nREGRAS ESPECIAIS DE LINKS:\n{regras_links}\n=== HISTÓRICO ===\n{historico_formatado}\n=== NOVA MENSAGEM ===\nUsuário: {mensagem}\nResponda naturalmente considerando o contexto anterior e as regras de links."
        
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_conversa
        )
        
        resposta_ia = response.text

        nova_msg_assistant = Mensagem(
            conversa_id=id_conversa_uuid,
            remetente="assistant",
            conteudo=resposta_ia
        )
        db.add(nova_msg_assistant)
        db.commit()

        return {
            "conversa_id": str(id_conversa_uuid),
            "titulo": conversa.titulo,
            "resultado": resposta_ia
        }

    # MODO CLASSIFICAÇÃO
    if feira_selecionada == "FEBRACE":
        tokenizer_ativo = tokenizer_febrace
        modelo_ativo = modelo_febrace
        mapeamento_ativo = mapeamento_febrace
        instrucao_avaliador = "Você é um avaliador técnico especializado na FEBRACE (Feira Brasileira de Ciências e Engenharia)."
    elif feira_selecionada == "MOSTRATEC":
        tokenizer_ativo = tokenizer_mostratec
        modelo_ativo = modelo_mostratec
        mapeamento_ativo = mapeamento_mostratec
        instrucao_avaliador = "Você é um avaliador técnico especializado na feira de ciências Mostratec."
    else:
        return {"erro": "Para classificação de projetos, selecione FEBRACE ou MOSTRATEC."}

    inputs = tokenizer_ativo(
        texto,
        return_tensors="pt",
        truncation=True,
        padding=True,
        max_length=512
    )

    with torch.no_grad():
        outputs = modelo_ativo(**inputs)

    probabilidades = F.softmax(outputs.logits, dim=-1)
    top_3 = torch.topk(probabilidades, k=3)
    indices_top_3 = top_3.indices.squeeze(0).tolist()
    categorias_top3 = [mapeamento_ativo[str(idx)] for idx in indices_top_3]

    cat_1 = categorias_top3[0]
    cat_2 = categorias_top3[1]
    cat_3 = categorias_top3[2]

    # String concatenada de forma limpa para mitigar erros com aspas triplas
    prompt_instrucao = (
        f"{instrucao_avaliador}\n"
        "Sua única tarefa é analisar o resumo de um projeto e fornecer a classificação correta com base nas previsões geradas pelo nosso modelo estatístico.\n"
        f"DADOS DA CLASSIFICAÇÃO ENVIADOS PELO MODELO DE IA:\n- 1º Lugar (Classificação Principal): {cat_1}\n- 2º Lugar (Alternativa sugerida pelo algoritmo): {cat_2}\n- 3º Lugar (Alternativa sugerida pelo algoritmo): {cat_3}\n"
        f"RESUMO DO PROJETO ANALISADO:\n{texto}\n"
        "REGRAS DE CONSTRUÇÃO DA RESPOSTA (SIGA ESTRITAMENTE):\n"
        "1. ESTRUTURA CRÍTICA: A PRIMEIRA PALAVRA do texto completo deve ser obrigatoriamente o nome da categoria de 1º Lugar em negrito. Exemplo: \"**Ciências da Computação**: O projeto apresenta...\".\n"
        "2. SEM ENROLAÇÃO: Proibido incluir saudações, mensagens de boas-vindas, elogios ou textos introdutórios vazios. Vá direto ao ponto técnico.\n"
        "3. JUSTIFICATIVA PRINCIPAL: Logo após a primeira palavra, apresente a explicação clara, lógica e objetiva de por que o resumo se enquadra nessa categoria principal.\n"
        "4. FILTRO DE COERÊNCIA DO TOP 3: Avalie criticamente se as categorias de 2º e 3º lugar guardam alguma relação coerente e lógica com o resumo do projeto.\n"
        "5. Adicione apenas as alternativas que forem estritamente coerentes de fato.\n"
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt_instrucao
    )

    resposta_ia = response.text

    nova_msg_assistant = Mensagem(
        conversa_id=id_conversa_uuid,
        remetente="assistant",
        conteudo=resposta_ia
    )
    db.add(nova_msg_assistant)
    db.commit()

    return {
        "conversa_id": str(id_conversa_uuid),
        "titulo": conversa.titulo,
        "resultado": resposta_ia,
        "metadados_top3": [cat_1, cat_2, cat_3]
    }


# --- ROTAS DE AUTENTICAÇÃO ---

@app.post("/cadastro")
def cadastrar_usuario(dados: RequisicaoCadastro):
    db: Session = SessionLocal()
    try:
        usuario_existente = db.query(Usuario).filter(Usuario.email == dados.email).first()
        if usuario_existente:
            return {"sucesso": False, "mensagem": "Este e-mail já está cadastrado."}

        senha_hash = gerar_hash_senha(dados.senha)
        usuario = Usuario(nome=dados.nome, email=dados.email, senha_hash=senha_hash)

        db.add(usuario)
        db.commit()
        db.refresh(usuario)

        token = criar_token(usuario.id)
        return {
            "sucesso": True,
            "token": token,
            "usuario": {"id": usuario.id, "nome": usuario.nome, "email": usuario.email}
        }
    finally:
        db.close()


@app.post("/login")
def login(dados: RequisicaoLogin):
    db: Session = SessionLocal()
    try:
        usuario = db.query(Usuario).filter(Usuario.email == dados.email).first()
        if usuario is None or not verificar_senha(dados.senha, usuario.senha_hash):
            return {"sucesso": False, "mensagem": "E-mail ou senha inválidos."}

        token = criar_token(usuario.id)
        return {
            "sucesso": True,
            "token": token,
            "usuario": {
                "id": usuario.id,
                "nome": usuario.nome,
                "email": usuario.email,
                "foto": usuario.foto
            }
        }
    finally:
        db.close()


@app.post("/login/google")
def login_google(dados: RequisicaoGoogle):
    db: Session = SessionLocal()
    try:
        info = verificar_credential(dados.credential)
        usuario = db.query(Usuario).filter(Usuario.email == info["email"]).first()

        if usuario is None:
            usuario = Usuario(
                nome=info["nome"],
                email=info["email"],
                google_id=info["google_id"],
                foto=info["foto"]
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
                "foto": info["foto"]
            }
        }
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
