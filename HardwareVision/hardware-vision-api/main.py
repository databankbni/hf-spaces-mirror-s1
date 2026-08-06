# ═══════════════════════════════════════════════════════════════════════════════
# main.py — Hardware Vision API (Render)
# Pipeline completo: YOLO + Gemini + SORT Tracking
# ═══════════════════════════════════════════════════════════════════════════════
import os, json, re, urllib.parse, time
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
import io, numpy as np
import cv2
import uvicorn

from ultralytics import YOLO  # best_v4.pt
from google import genai
from google.genai import types

# ── Configurações ────────────────────────────────────────────────────────────
GEMINI_KEY = os.environ.get("GEMINI_KEY", "")
CONFIANCA_MIN   = 0.15  # baixo — YOLO localiza, Gemini classifica
MODELOS_GEMINI  = [
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.5-flash",
]

# ── SORT Tracker leve — associa detecções entre frames via IoU ────────────────
class Track:
    """Representa um objeto rastreado com ID estável."""
    _next_id = 1

    def __init__(self, bbox, nome):
        self.id        = Track._next_id
        Track._next_id += 1
        self.bbox      = bbox          # [x1,y1,x2,y2] normalizado
        self.nome      = nome
        self.idade     = 0             # frames desde última detecção
        self.ativo     = True

    def atualizar(self, bbox, nome):
        self.bbox  = bbox
        self.nome  = nome
        self.idade = 0
        self.ativo = True

class SORTLeve:
    """
    SORT simplificado sem Kalman — usa IoU para associar detecções a tracks.
    Leve o suficiente para rodar no container gratuito do HF Spaces.
    """
    def __init__(self, iou_min=0.3, max_idade=3):
        self.tracks   = []
        self.iou_min  = iou_min   # IoU mínimo para associar
        self.max_idade = max_idade # frames sem detecção antes de remover

    @staticmethod
    def iou(a, b):
        """Calcula IoU entre dois bboxes [x1,y1,x2,y2]."""
        xi1 = max(a[0], b[0]); yi1 = max(a[1], b[1])
        xi2 = min(a[2], b[2]); yi2 = min(a[3], b[3])
        inter = max(0, xi2-xi1) * max(0, yi2-yi1)
        if inter == 0:
            return 0.0
        area_a = (a[2]-a[0]) * (a[3]-a[1])
        area_b = (b[2]-b[0]) * (b[3]-b[1])
        return inter / (area_a + area_b - inter)

    def atualizar(self, deteccoes):
        """
        deteccoes: lista de dicts com bbox [x1,y1,x2,y2] e nome
        Retorna lista de dicts com track_id adicionado
        """
        # Envelhece todos os tracks
        for t in self.tracks:
            t.idade += 1

        associados_track  = set()
        associados_det    = set()

        # Matriz de IoU entre tracks ativos e novas detecções
        tracks_ativos = [t for t in self.tracks if t.ativo or t.idade <= self.max_idade]
        for i, det in enumerate(deteccoes):
            melhor_iou   = self.iou_min
            melhor_track = None
            for j, track in enumerate(tracks_ativos):
                if j in associados_track:
                    continue
                iou_val = self.iou(det["bbox"], track.bbox)
                if iou_val > melhor_iou:
                    melhor_iou   = iou_val
                    melhor_track = j
            if melhor_track is not None:
                tracks_ativos[melhor_track].atualizar(det["bbox"], det["nome"])
                det["track_id"] = tracks_ativos[melhor_track].id
                associados_track.add(melhor_track)
                associados_det.add(i)

        # Detecções sem match → novo track
        for i, det in enumerate(deteccoes):
            if i not in associados_det:
                novo = Track(det["bbox"], det["nome"])
                self.tracks.append(novo)
                det["track_id"] = novo.id

        # Remove tracks muito antigos
        self.tracks = [t for t in self.tracks if t.idade <= self.max_idade]

        return deteccoes

# Tracker global — persiste entre requisições no mesmo processo
_tracker       = SORTLeve(iou_min=0.3, max_idade=3)
_tracker_reset = time.time()  # resetar se ficar muito tempo sem chamadas

# ── Inicializa Gemini ─────────────────────────────────────────────────────────
client = genai.Client(api_key=GEMINI_KEY, http_options={'api_version': 'v1beta'})

# ── Aliases de componentes (texto do usuário → classe do modelo) ──────────────
ALIASES = {
    # RAM → classe V4: "RAM"
    "ram": "RAM",
    "memória ram": "RAM",
    "memoria ram": "RAM",
    "memória": "RAM",
    "memoria": "RAM",
    "pente de ram": "RAM",
    "pente ram": "RAM",
    # SSD → classe V4: "SSD"
    "ssd": "SSD",
    "ssd sata": "SSD",
    "ssd nvme": "SSD",
    "ssd m.2": "SSD",
    "nvme": "SSD",
    "m.2": "SSD",
    "disco sólido": "SSD",
    "disco solido": "SSD",
    # HDD → classe V4: "HDD"
    "hd": "HDD",
    "hdd": "HDD",
    "hd sata": "HDD",
    "hdd sata": "HDD",
    "disco": "HDD",
    "disco rígido": "HDD",
    "disco rigido": "HDD",
    "armazenamento": "HDD",
    "drive": "HDD",
    # CPU → classe V4: "cpu"
    "processador": "cpu",
    "proc": "cpu",
    "processor": "cpu",
    # GPU → classe V4: "GPU"
    "placa de vídeo": "GPU",
    "placa de video": "GPU",
    "gpu": "GPU",
    "placa gráfica": "GPU",
    "placa grafica": "GPU",
    "video card": "GPU",
    # Classes V2/V3 mantidas para fallback
    "cooler": "cpu_cooler",
    "cooler cpu": "cpu_cooler",
    "ventoinha": "cpu_cooler",
    "fonte": "psu",
    "fonte de alimentação": "psu",
    "fonte de alimentacao": "psu",
    "power supply": "psu",
    "placa mãe": "motherboard",
    "placa mae": "motherboard",
    "placa-mãe": "motherboard",
    "placa-mae": "motherboard",
    "mainboard": "motherboard",
    "slot ram": "ram_slot",
    "slot de ram": "ram_slot",
    "painel frontal": "front_panel",
    "io traseiro": "rear_io",
    "rear io": "rear_io",
    "drive óptico": "optical_drive",
    "drive optico": "optical_drive",
    "dvd": "optical_drive",
    "leitor dvd": "optical_drive",
    "slot gpu": "gpu_slot",
    "slot de gpu": "gpu_slot",
    "slot pcie": "gpu_slot",
}

# ── Tradução de nomes técnicos → português ───────────────────────────────────
NOMES_PT = {
    # Classes do V4 (GPU, HDD, RAM, SSD, cpu)
    "gpu":           "Placa de Vídeo",
    "hdd":           "HD",
    "ram":           "Memória RAM",
    "ssd":           "SSD",
    "cpu":           "Processador",
    # Classes do V3/V2 (fallback)
    "ram_stick":     "Memória RAM",
    "disk_drive":    "SSD/HD",
    "cpu_cooler":    "Cooler CPU",
    "gpu_slot":      "Slot PCIe",
    "motherboard":   "Placa-Mãe",
    "optical_drive": "Drive Óptico",
    "psu":           "Fonte",
    "ram_slot":      "Slot RAM",
    "front_panel":   "Painel Frontal",
    "rear_io":       "Painel Traseiro",
}

def traduzir_nome(nome: str) -> str:
    """Converte classe técnica do YOLO para nome amigável em português."""
    return NOMES_PT.get(nome.lower().strip(), nome)

def normalizar_componente(texto: str) -> str:
    """Mapeia o texto livre do usuário para a classe do modelo YOLO."""
    t = texto.lower().strip()
    return ALIASES.get(t, t)


def normalizar_nome_exibicao(nome: str) -> str:
    """
    Normaliza o nome final que vai virar LABEL na tela (AR/popup).

    Regras:
    - Nunca exibir "SSD/HD" genérico — decidir entre SSD SATA / SSD NVMe / HD.
    - Bateria: exibir apenas "Bateria" (nunca "Bateria de notebook").
    - Se o Gemini devolver um nome COMPOSTO (ex: "Memória RAM, SSD/HD"),
      manter só o PRIMEIRO componente — evita label com dois nomes quando
      uma peça está sobreposta à outra.
    """
    if not nome:
        return nome

    # 1) Nome composto ("Memória RAM, SSD/HD" / "RAM e SSD" / "RAM / SSD")
    #    -> fica só o primeiro. A separação por vírgula é a mais comum do Gemini.
    for sep in [",", " e ", " / ", "/"]:
        # cuidado: "SSD/HD" usa "/" mas é um token único conhecido;
        # só quebramos em "/" se NÃO for exatamente o par ssd/hd ou hd/ssd
        if sep in ("/", " / "):
            teste = nome.lower().replace(" ", "")
            if teste in ("ssd/hd", "hd/ssd"):
                continue
        if sep in nome:
            nome = nome.split(sep)[0].strip()
            break

    n = nome.strip().lower()
    # versão "achatada" (sem espaços) para comparar tokens tipo "ssd / hd"
    nflat = n.replace(" ", "")

    # 2) Bateria — sempre curto
    if "bateria" in n:
        return "Bateria"

    # 3) Memória RAM — normaliza formas abreviadas
    if n in ("ram", "memoria ram", "memória ram", "dimm", "so-dimm", "sodimm"):
        return "Memória RAM"

    # 4) Armazenamento — desambiguar SSD/HD
    if "nvme" in n or "m.2" in n or "m2" in nflat:
        return "SSD NVMe"
    if "sata" in n and "ssd" in n:
        return "SSD SATA"
    if nflat in ("ssd/hd", "hd/ssd", "ssdouhd", "ssd", "discosólido", "discosolido"):
        # sem info suficiente para saber a interface -> assume o caso mais comum (2.5")
        return "SSD SATA"
    if n in ("hd", "hdd") or "mecânico" in n or "mecanico" in n or "disco rígido" in n:
        return "HD"

    return nome


# ── TARGET 2.0 — resolução de ALVO ───────────────────────────────────────────
# Diferente de ALIASES (que mapeia texto livre -> CLASSE DO YOLO, usado pelo
# /target e /raiox legados), este mapa converte o texto livre do usuário nos
# NOMES DE EXIBIÇÃO que o /detectar realmente devolve (os mesmos produzidos por
# normalizar_nome_exibicao). Sem ele, pedir "SSD NVMe" cairia em ALIASES como
# "SSD" e traria também os SATA -- justamente a distincao que queremos manter.
#
# Match HIERARQUICO: um alvo generico casa com seus filhos.
#   "SSD"      -> SSD SATA + SSD NVMe   (pai casa com os dois)
#   "SSD NVMe" -> so SSD NVMe            (filho casa so consigo)
ALVO_FAMILIAS = {
    "SSD": ["SSD SATA", "SSD NVMe"],
    "Armazenamento": ["SSD SATA", "SSD NVMe", "HD"],
    "Cabo interno": ["Cabo SATA", "Cabo Flat/FFC", "Cabo de alimentacao",
                     "Cabo de bateria", "Cabo de antena Wi-Fi",
                     "Cabo da tela", "Cabo interno"],
}

ALIASES_ALVO = {
    # ── Memoria RAM ──
    "ram": "Memória RAM", "memoria": "Memória RAM", "memória": "Memória RAM",
    "memoria ram": "Memória RAM", "memória ram": "Memória RAM",
    "pente": "Memória RAM", "pente de ram": "Memória RAM",
    "pente ram": "Memória RAM", "dimm": "Memória RAM", "so-dimm": "Memória RAM",
    "sodimm": "Memória RAM",
    # ── SSD generico (casa com SATA e NVMe) ──
    "ssd": "SSD", "disco solido": "SSD", "disco sólido": "SSD",
    "estado solido": "SSD", "estado sólido": "SSD",
    # ── SSD especifico ──
    "ssd sata": "SSD SATA", "ssd 2.5": "SSD SATA", "ssd sata 2.5": "SSD SATA",
    "ssd nvme": "SSD NVMe", "nvme": "SSD NVMe", "m.2": "SSD NVMe",
    "m2": "SSD NVMe", "ssd m.2": "SSD NVMe", "ssd m2": "SSD NVMe",
    # ── HD ──
    "hd": "HD", "hdd": "HD", "disco rigido": "HD", "disco rígido": "HD",
    "disco": "HD", "hd mecanico": "HD", "hd mecânico": "HD",
    # ── Armazenamento (generico amplo) ──
    "armazenamento": "Armazenamento", "storage": "Armazenamento",
    # ── Processador ──
    "cpu": "Processador", "processador": "Processador", "proc": "Processador",
    "processor": "Processador",
    # ── Placa de Video ──
    "gpu": "Placa de Vídeo", "placa de video": "Placa de Vídeo",
    "placa de vídeo": "Placa de Vídeo", "placa grafica": "Placa de Vídeo",
    "placa gráfica": "Placa de Vídeo", "video card": "Placa de Vídeo",
    "vga": "Placa de Vídeo",
    # ── Placa-Mae ──
    "placa mae": "Placa-Mãe", "placa mãe": "Placa-Mãe",
    "placa-mae": "Placa-Mãe", "placa-mãe": "Placa-Mãe",
    "mobo": "Placa-Mãe", "motherboard": "Placa-Mãe",
    # ── Fonte ──
    "fonte": "Fonte", "psu": "Fonte", "fonte de alimentacao": "Fonte",
    "fonte de alimentação": "Fonte",
    # ── Cooler ──
    "cooler": "Cooler CPU", "cooler cpu": "Cooler CPU",
    "cooler do processador": "Cooler CPU", "dissipador": "Cooler CPU",
    "ventoinha": "Cooler CPU", "fan": "Cooler CPU",
    # ── Bateria ──
    "bateria": "Bateria", "bateria de notebook": "Bateria",
    "bateria do notebook": "Bateria",
    # ── Drive Optico ──
    "drive optico": "Drive Óptico", "drive óptico": "Drive Óptico",
    "dvd": "Drive Óptico", "cd": "Drive Óptico", "leitor de dvd": "Drive Óptico",
    # ── Cabos ──
    "cabo": "Cabo interno", "cabos": "Cabo interno",
    "cabo interno": "Cabo interno",
    "cabo sata": "Cabo SATA",
    "cabo flat": "Cabo Flat/FFC", "flat": "Cabo Flat/FFC",
    "ffc": "Cabo Flat/FFC", "cabo ffc": "Cabo Flat/FFC",
    "cabo de alimentacao": "Cabo de alimentação",
    "cabo de alimentação": "Cabo de alimentação",
    "cabo de energia": "Cabo de alimentação",
    "cabo de bateria": "Cabo de bateria",
    "cabo da bateria": "Cabo de bateria",
    "cabo de antena": "Cabo de antena Wi-Fi",
    "cabo wifi": "Cabo de antena Wi-Fi",
    "cabo wi-fi": "Cabo de antena Wi-Fi",
    "antena": "Cabo de antena Wi-Fi",
    "cabo da tela": "Cabo da tela", "cabo do display": "Cabo da tela",
    "cabo lvds": "Cabo da tela",
}


def resolver_alvo(texto: str) -> str | None:
    """
    Converte o texto livre do usuario no NOME DE EXIBICAO canonico do alvo.
    Retorna None se o texto for vazio (= sem filtro, modo Radar normal).

    Tolera acento ausente, plural simples e ruido de fala ("procurar o ssd",
    "quero achar a memoria ram"). Se nao reconhecer, devolve o texto limpo --
    assim um alvo desconhecido simplesmente nao casa com nada, em vez de
    silenciosamente virar outro componente.
    """
    if not texto:
        return None
    t = texto.strip().lower()
    if not t:
        return None

    # Remove ruido de comando de voz mais comum
    for lixo in ("procurar ", "procure ", "localizar ", "localize ",
                 "encontrar ", "encontre ", "achar ", "ache ", "buscar ",
                 "busque ", "quero ", "o ", "a ", "os ", "as ", "um ", "uma "):
        if t.startswith(lixo):
            t = t[len(lixo):].strip()

    if t in ALIASES_ALVO:
        return ALIASES_ALVO[t]

    # plural simples
    if t.endswith("s") and t[:-1] in ALIASES_ALVO:
        return ALIASES_ALVO[t[:-1]]

    # match por substring (ex.: "pente de memoria ram ddr4")
    # do alias mais longo para o mais curto -> "ssd nvme" ganha de "ssd"
    for alias in sorted(ALIASES_ALVO, key=len, reverse=True):
        if alias in t:
            return ALIASES_ALVO[alias]

    return texto.strip()


def alvo_casa(alvo_canonico: str, nome_detectado: str) -> bool:
    """
    True se o componente detectado satisfaz o alvo pedido.

    Hierarquico: se o alvo for uma familia ("SSD"), qualquer membro casa
    ("SSD SATA", "SSD NVMe"). Se for especifico, exige igualdade.
    """
    if not alvo_canonico:
        return True
    if nome_detectado == alvo_canonico:
        return True
    filhos = ALVO_FAMILIAS.get(alvo_canonico)
    if filhos and nome_detectado in filhos:
        return True
    return False




# ── Download automático do best_v4.pt via huggingface_hub ────────────────────
try:
    from huggingface_hub import hf_hub_download
    if not os.path.exists("best_v4.pt"):
        print("📥 Baixando best_v4.pt do Hugging Face...")
        hf_hub_download(
            repo_id="HardwareVision/hardware-vision-api",
            filename="best_v4.pt",
            repo_type="space",
            local_dir="."
        )
        print("✅ best_v4.pt baixado!")
    else:
        print("✅ best_v4.pt já existe localmente!")
except Exception as e:
    print(f"⚠️ Não foi possível baixar best_v4.pt: {e}")

# ── Inicializa YOLO — v4 principal, v3 fallback, v2 último recurso ───────────
try:
    modelo_yolo = YOLO("best_v4.pt")
    print(f"✅ YOLO v4 carregado! Classes: {list(modelo_yolo.names.values())}")
except Exception as e:
    print(f"⚠️ best_v4.pt não encontrado, tentando best_v3.pt: {e}")
    try:
        modelo_yolo = YOLO("best_v3.pt")
        print(f"✅ YOLO v3 (fallback) carregado! Classes: {list(modelo_yolo.names.values())}")
    except Exception as e2:
        print(f"⚠️ best_v3.pt não encontrado, tentando best_v2.pt: {e2}")
        try:
            modelo_yolo = YOLO("best_v2.pt")
            print(f"✅ YOLO v2 (fallback) carregado! Classes: {list(modelo_yolo.names.values())}")
        except Exception as e3:
            print(f"❌ Erro YOLO: {e3}")
            modelo_yolo = None



# ── FastAPI ───────────────────────────────────────────────────────────────────
app = FastAPI(title="Hardware Vision API")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

# ── Helpers ───────────────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# ANTI-REDUNDÂNCIA DE MARCAÇÃO
#
# O YOLO frequentemente desenha DUAS OU MAIS caixas sobre o MESMO objeto físico
# (ex.: um único SSD recebendo "SSD SATA (1)" e "SSD SATA (2)"). Isso não é um
# erro da numeração — são caixas duplicadas chegando do detector.
#
# Aqui suprimimos essas caixas ANTES de chamar o Gemini, o que:
#   1) elimina os labels duplicados sobre o mesmo componente;
#   2) economiza chamadas à API (cada caixa a menos = uma chamada a menos).
#
# Dois testes complementares:
#   • IoU alto            → mesma área ocupada = mesmo objeto.
#   • Contenção (overlap) → uma caixa quase toda DENTRO da outra. Pega o caso
#     que o IoU deixa passar: caixa pequena dentro de uma bem maior tem IoU
#     baixo (a união é grande), mas obviamente é o mesmo objeto.
#
# ATENÇÃO — o que NÃO deve ser suprimido: dois componentes iguais e DISTINTOS
# (2 pentes de RAM lado a lado). Esses têm caixas separadas, com IoU ~0 e sem
# contenção — passam intactos pelos dois testes.
# ══════════════════════════════════════════════════════════════════════════════

def _iou_box(a, b):
    """IoU entre dois bboxes [x1,y1,x2,y2]."""
    xi1 = max(a[0], b[0]); yi1 = max(a[1], b[1])
    xi2 = min(a[2], b[2]); yi2 = min(a[3], b[3])
    inter = max(0, xi2 - xi1) * max(0, yi2 - yi1)
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    uniao  = area_a + area_b - inter
    return inter / uniao if uniao > 0 else 0.0

def _contencao_box(a, b):
    """Fração da MENOR caixa que está dentro da outra (0..1).

    Diferente do IoU, não é penalizada pela diferença de tamanho: uma caixa
    pequena 100% dentro de uma grande retorna 1.0.
    """
    xi1 = max(a[0], b[0]); yi1 = max(a[1], b[1])
    xi2 = min(a[2], b[2]); yi2 = min(a[3], b[3])
    inter = max(0, xi2 - xi1) * max(0, yi2 - yi1)
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    menor  = min(area_a, area_b)
    return inter / menor if menor > 0 else 0.0

def suprimir_caixas_redundantes(boxes, iou_max=0.35, contencao_max=0.70):
    """NMS: remove caixas que marcam o MESMO objeto físico.

    boxes: lista de tuplas (conf, x1, y1, x2, y2)
    Mantém sempre a caixa de MAIOR confiança de cada grupo sobreposto.
    Retorna a lista filtrada.

    Observação: aqui ainda não sabemos o NOME (o Gemini só classifica depois),
    então a supressão é puramente geométrica — o que é o correto: duas caixas
    no mesmo lugar são o mesmo objeto, seja ele qual for.
    """
    if not boxes:
        return []
    # Maior confiança primeiro — ela é a "dona" da região.
    ordenadas = sorted(boxes, key=lambda t: t[0], reverse=True)
    mantidas  = []
    for cand in ordenadas:
        c_box = cand[1:5]
        redundante = False
        for m in mantidas:
            m_box = m[1:5]
            iou   = _iou_box(c_box, m_box)
            cont  = _contencao_box(c_box, m_box)
            if iou >= iou_max or cont >= contencao_max:
                redundante = True
                print(f"   ↳ caixa conf={cand[0]:.2f} suprimida "
                      f"(IoU={iou:.2f}, contenção={cont:.2f}) — mesmo objeto")
                break
        if not redundante:
            mantidas.append(cand)
    return mantidas

def contar_componentes_na_cena(cena_bytes: bytes, nomes: list[str]) -> dict:
    """Pergunta ao Gemini QUANTOS componentes de cada tipo existem na CENA.

    Esta é a validação semântica do frame completo: o YOLO pode marcar o mesmo
    SSD duas vezes, mas quem olha a cena inteira sabe que existe apenas UM SSD
    físico ali. Usamos essa contagem como TETO para o número de labels.

    nomes: tipos únicos que o Gemini já identificou nos recortes.
    Retorna {nome: quantidade}. Em caso de falha, retorna {} (sem limite).
    """
    if not cena_bytes or not nomes:
        return {}
    lista = "\n".join(f"- {n}" for n in nomes)
    prompt = (
        "Você é especialista em hardware interno de PCs e notebooks.\n"
        "Olhe a CENA COMPLETA da imagem e conte quantas UNIDADES FÍSICAS "
        "DISTINTAS de cada componente abaixo aparecem nela.\n\n"
        f"{lista}\n\n"
        "REGRAS CRÍTICAS:\n"
        "1. Conte OBJETOS FÍSICOS SEPARADOS, não partes do mesmo objeto.\n"
        "   Ex.: um único SSD visto de cima é 1 (mesmo que tenha etiquetas,\n"
        "   parafusos ou reflexos que pareçam dividi-lo).\n"
        "2. Dois pentes de memória RAM lado a lado = 2. Um pente só = 1.\n"
        "3. Se o componente não aparece na cena, responda 0.\n"
        "4. Conte apenas o que você VÊ com clareza.\n\n"
        "Responda APENAS um JSON, sem texto extra, no formato:\n"
        '{"Memória RAM": 2, "SSD SATA": 1}'
    )
    try:
        data = gemini_json(prompt, cena_bytes)
        if not isinstance(data, dict):
            return {}
        # Sanitiza: só nomes pedidos, valores inteiros >= 0
        limpo = {}
        for n in nomes:
            v = data.get(n)
            if isinstance(v, (int, float)) and v >= 0:
                limpo[n] = int(v)
        return limpo
    except Exception as e:
        print(f"⚠️ contar_componentes_na_cena erro: {e}")
        return {}

def bytes_para_cv2(b):
    nparr = np.frombuffer(b, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

def gemini_gerar(prompt, imagem_bytes=None):
    """
    imagem_bytes pode ser:
      - None (só texto)
      - bytes (uma imagem)
      - lista de bytes (várias imagens, enviadas na ordem dada)
    """
    key = os.environ.get("GEMINI_KEY", GEMINI_KEY)
    if isinstance(imagem_bytes, (bytes, bytearray)):
        imagens = [imagem_bytes]
    elif imagem_bytes:
        imagens = list(imagem_bytes)
    else:
        imagens = []
    for modelo in MODELOS_GEMINI:
        try:
            c = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
            contents = [prompt]
            for img in imagens:
                if img:
                    contents.append(
                        types.Part.from_bytes(data=img, mime_type="image/jpeg"))
            resp = c.models.generate_content(model=modelo, contents=contents)
            return resp.text
        except Exception as e:
            print(f"⚠️ {modelo} falhou: {e}")
    raise Exception("Todos os modelos Gemini falharam")

def gemini_json(prompt, imagem_bytes=None):
    txt = gemini_gerar(prompt, imagem_bytes)
    txt = txt.replace("```json","").replace("```","").strip()
    match = re.search(r'\{[\s\S]*\}', txt)
    if match:
        return json.loads(match.group(0))
    return json.loads(txt)

def gemini_identificar_recorte(
    recorte_bytes: bytes,
    cena_bytes: bytes | None = None,
    posicao: str | None = None,
) -> str | None:
    tem_contexto = cena_bytes is not None
    prompt = (
        "Você é especialista em hardware interno de PCs e notebooks.\n"
        + (
            "Você receberá DUAS imagens:\n"
            "1) A CENA COMPLETA (a tela inteira da câmera), só para você entender o "
            "contexto e o que está ao redor.\n"
            f"2) O RECORTE a ser identificado"
            + (f", localizado em: {posicao} da cena.\n" if posicao else ".\n")
            + "IDENTIFIQUE APENAS o componente do RECORTE (imagem 2). Use a cena "
              "(imagem 1) apenas como apoio para ter CERTEZA — por exemplo, para "
              "distinguir uma memória RAM de um SSD quando o recorte está escuro ou "
              "ambíguo. NÃO descreva a cena inteira.\n\n"
            if tem_contexto else
            "Observe este recorte com MUITO CUIDADO e identifique o componente.\n\n"
        )
    ) + (
        "COMPONENTES INTERNOS VÁLIDOS — responda EXATAMENTE um destes nomes:\n"
        "Componentes principais:\n"
        "- Memória RAM: módulo DIMM/SO-DIMM, placa pequena com chips enfileirados e conector dourado\n"
        "- SSD SATA: disco de estado sólido 2.5 polegadas, caixa metálica retangular, conector SATA\n"
        "- SSD NVMe: placa fina pequena (M.2) com poucos chips, encaixe único, sem caixa metálica\n"
        "- HD: disco rígido mecânico, mais grosso/pesado, geralmente com etiqueta de RPM\n"
        "- Processador: chip CPU encaixado no socket\n"
        "- Placa de Vídeo: GPU com cooler\n"
        "- Placa-Mãe: placa principal grande com vários slots\n"
        "- Fonte: caixa metálica com ventilador e cabos de energia\n"
        "- Cooler CPU: dissipador com ventoinha sobre o processador\n"
        "- Bateria de notebook: bateria Li-Ion interna\n"
        "- Drive Óptico: leitor DVD/CD\n"
        "Cabos internos (identifique com precisão):\n"
        "- Cabo SATA: cabo fino com conector em L nas pontas\n"
        "- Cabo Flat/FFC: fita plana fina branca/bege/preta\n"
        "- Cabo de alimentação: cabo com conectores de energia\n"
        "- Cabo de bateria: cabo fino conectado à bateria do notebook\n"
        "- Cabo de antena Wi-Fi: cabo coaxial fino\n"
        "- Cabo da tela: cabo flat que conecta o display\n"
        "\n"
        "RESPONDA NENHUM para periféricos externos:\n"
        "- Teclado, mouse, monitor, webcam, caixas de som\n"
        "- Cabo USB, cabo HDMI, cabo de rede, carregador externo\n"
        "- Mãos, dedos, mesa, fundo, parafusos, suportes\n"
        "\n"
        "REGRA CRÍTICA: NUNCA confunda cabo com Memória RAM ou outro componente principal.\n"
        "Se for cabo interno mas incerto do tipo, responda: Cabo interno\n"
        "\n"
        "REGRA CRÍTICA 2: este recorte contém UM ÚNICO componente — o que ocupa\n"
        "a MAIOR ÁREA / está mais ao CENTRO do recorte. Se houver outra peça atrás\n"
        "ou sobreposta, IGNORE-A. Responda apenas UM nome. NUNCA responda dois nomes\n"
        "juntos (ex: nunca 'Memória RAM, SSD'). Escolha o componente dominante.\n"
        "\n"
        "Responda SOMENTE o nome exato ou NENHUM. Nada mais."
    )
    try:
        # Ordem das imagens: [cena completa, recorte] — o prompt referencia
        # "imagem 1 = cena" e "imagem 2 = recorte" nessa ordem.
        if tem_contexto:
            imgs = [cena_bytes, recorte_bytes]
        else:
            imgs = recorte_bytes
        txt = gemini_gerar(prompt, imgs)
        txt = txt.strip().strip('"').strip("'")
        if not txt or txt.upper() == "NENHUM":
            return None
        return normalizar_nome_exibicao(txt)
    except Exception as e:
        print(f"⚠️ gemini_identificar_recorte erro: {e}")
        return None

def recortar_box(img_cv2, x1, y1, x2, y2, padding=4) -> bytes:
    # padding pequeno (4px) evita que o recorte de uma peça invada a etiqueta
    # de uma peça vizinha colada — antes eram 10px, que com 2 RAMs empilhadas
    # capturavam a etiqueta da outra e o Gemini fundia os dados.
    h, w = img_cv2.shape[:2]
    x1c = max(0, int(x1) - padding)
    y1c = max(0, int(y1) - padding)
    x2c = min(w, int(x2) + padding)
    y2c = min(h, int(y2) + padding)
    recorte = img_cv2[y1c:y2c, x1c:x2c]
    _, buf = cv2.imencode('.jpg', recorte, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()

def descrever_com_gemini(imagem_bytes, nome):
    prompt = (
        f"Aja como especialista em hardware. Componente: {nome}.\n"
        f"IMPORTANTE: a imagem pode conter, nas BORDAS, pedaços de OUTRA peça "
        f"vizinha. Descreva SOMENTE a peça CENTRAL (a que ocupa o meio do "
        f"recorte). Se aparecer a etiqueta de outra peça na borda, IGNORE — "
        f"não misture marcas, modelos ou capacidades de peças diferentes.\n"
        f"Responda APENAS JSON puro sem markdown:\n"
        f'{{"tipo":"SSD","modelo":"SA400S37/240G","descricao":"Descrição técnica em até 25 palavras.","dica":"Dica prática curta."}}\n'
        f"- modelo: exatamente como aparece na etiqueta física da peça CENTRAL, null se não visível\n"
        f"- NUNCA invente modelos e NUNCA combine dados de duas peças (ex: 'hynix / ProMOS' ou '512MB / 1GB' está ERRADO)"
    )
    dados = gemini_json(prompt, imagem_bytes)
    dados.setdefault("modelo", None)
    return dados

# ════════════════════════════════════════════════════════════════════════════
# ROTAS
# ════════════════════════════════════════════════════════════════════════════

@app.get("/")
def health():
    classes = list(modelo_yolo.names.values()) if modelo_yolo else []
    return {"status": "online", "modelo": "Hardware Vision API", "classes": classes}

@app.get("/ping")
def ping():
    return {"status": "online", "yolo": modelo_yolo is not None}

# ── /detectar — YOLO + Gemini + SORT tracking ────────────────────────────────
@app.post("/detectar")
async def detectar(
    imagem: UploadFile = File(...),
    alvo:   str        = Form(""),   # TARGET 2.0 — vazio = Modo Radar normal
):
    global _tracker, _tracker_reset
    try:
        alvo_canonico = resolver_alvo(alvo)
        if alvo_canonico:
            print(f"🎯 Modo Target — alvo: {alvo_canonico!r}")
        b   = await imagem.read()
        img = bytes_para_cv2(b)
        h, w = img.shape[:2]

        if modelo_yolo is None:
            return {"sucesso": False, "erro": "YOLO offline"}

        if min(h, w) < 640:
            scale = 640 / min(h, w)
            img   = cv2.resize(img, (int(w*scale), int(h*scale)))
            h, w  = img.shape[:2]

        # Reset do tracker se ficar mais de 10s sem chamadas (câmera pausada)
        agora = time.time()
        if agora - _tracker_reset > 10:
            _tracker = SORTLeve(iou_min=0.3, max_idade=3)
        _tracker_reset = agora

        # ── Etapa 1: YOLO localiza bounding boxes (conf baixa) ───────────────
        results   = modelo_yolo(img, verbose=False)[0]
        boxes_raw = []
        for box in results.boxes:
            conf = float(box.conf[0])
            if conf >= CONFIANCA_MIN:
                x1,y1,x2,y2 = box.xyxy[0].tolist()
                boxes_raw.append((conf, x1, y1, x2, y2))

        if not boxes_raw:
            if alvo_canonico:
                return {"sucesso": False, "detectados": [],
                        "alvo": alvo_canonico, "alvo_encontrado": False,
                        "dica": "vazio", "outros": 0}
            return {"sucesso": False, "detectados": []}

        # ── Etapa 1.5: ANTI-REDUNDÂNCIA (NMS) ────────────────────────────────
        # O YOLO costuma desenhar várias caixas sobre o MESMO objeto físico.
        # Suprimimos aqui, ANTES do Gemini: evita labels duplicados no mesmo
        # componente (ex.: "SSD SATA (1)" e "SSD SATA (2)" no mesmo SSD) e
        # economiza uma chamada de API por caixa removida.
        # Componentes iguais mas DISTINTOS (2 RAMs lado a lado) não têm
        # sobreposição e passam intactos.
        antes = len(boxes_raw)
        boxes_raw = suprimir_caixas_redundantes(boxes_raw)
        if len(boxes_raw) < antes:
            print(f"🧹 NMS: {antes} caixas → {len(boxes_raw)} "
                  f"({antes - len(boxes_raw)} duplicadas no mesmo objeto)")

        # ── Cena completa (reduzida) como CONTEXTO para o Gemini ─────────────
        # Reduz a largura para no máx. 720px — leve para upload, suficiente
        # para o Gemini "enxergar" o entorno de cada recorte.
        cena_bytes = None
        try:
            cena_w = 720
            if w > cena_w:
                escala = cena_w / w
                cena_img = cv2.resize(img, (cena_w, int(h * escala)))
            else:
                cena_img = img
            _, cena_buf = cv2.imencode('.jpg', cena_img,
                                       [cv2.IMWRITE_JPEG_QUALITY, 70])
            cena_bytes = cena_buf.tobytes()
        except Exception as e:
            print(f"⚠️ Falha ao preparar cena de contexto: {e}")

        def _posicao_texto(cx, cy):
            vert = "topo" if cy < 0.33 else ("centro" if cy < 0.66 else "base")
            horz = "esquerda" if cx < 0.33 else ("meio" if cx < 0.66 else "direita")
            return f"{vert}-{horz}"

        # ── Etapa 2: Gemini classifica cada recorte (com contexto da cena) ────
        deteccoes = []
        for conf, x1, y1, x2, y2 in boxes_raw:
            recorte = recortar_box(img, x1, y1, x2, y2)
            cx = (x1 + x2) / 2 / w
            cy = (y1 + y2) / 2 / h
            nome = gemini_identificar_recorte(
                recorte,
                cena_bytes=cena_bytes,
                posicao=_posicao_texto(cx, cy),
            )
            if nome is None:
                print(f"⚠️ Gemini descartou box conf={conf:.2f} — não é componente")
                continue
            deteccoes.append({
                "nome":      nome,
                "confianca": round(conf, 2),
                "x":         round((x1+x2)/2/w, 4),
                "y":         round((y1+y2)/2/h, 4),
                "w":         round((x2-x1)/w, 4),
                "h":         round((y2-y1)/h, 4),
                "bbox":      [x1/w, y1/h, x2/w, y2/h],  # normalizado para SORT
                "tipo": "", "descricao": "", "dica": "", "modelo": None,
            })

        print(f"🔍 Detectados após Gemini: {[d['nome'] for d in deteccoes]}")
        if not deteccoes:
            if alvo_canonico:
                return {"sucesso": False, "detectados": [],
                        "alvo": alvo_canonico, "alvo_encontrado": False,
                        "dica": "vazio", "outros": 0}
            return {"sucesso": False, "detectados": []}

        # ── TARGET 2.0 — FILTRO DE ALVO ──────────────────────────────────────
        # Fica AQUI, e nao antes do Gemini, por um motivo estrutural: no
        # /detectar quem sabe o NOME de cada caixa e o proprio Gemini. O YOLO
        # so entrega coordenadas + confianca. Nao ha como pular um recorte por
        # nome antes de perguntar qual e o nome dele.
        #
        # O ganho real de filtrar aqui (e nao no app):
        #   - pula contar_componentes_na_cena() quando sobra <=1 alvo
        #   - o SORT so rastreia o alvo -> track_ids limpos, sem IDs fantasmas
        #     de componentes que o app ia descartar mesmo
        #   - resposta menor no fio
        dica_alvo   = None
        outros_qtd  = 0
        if alvo_canonico:
            alvos  = [d for d in deteccoes if alvo_casa(alvo_canonico, d["nome"])]
            outros = [d for d in deteccoes if not alvo_casa(alvo_canonico, d["nome"])]
            outros_qtd = len(outros)

            if not alvos:
                # Alvo nao esta na cena. Devolve contexto para o app escrever a
                # dica na tela (efeito typewriter) em vez de so "nao encontrado".
                nomes_outros = sorted({d["nome"] for d in outros})
                print(f"🎯 Alvo {alvo_canonico!r} ausente — "
                      f"cena tem: {nomes_outros or 'nada'}")
                return {
                    "sucesso": False, "detectados": [],
                    "alvo": alvo_canonico, "alvo_encontrado": False,
                    "dica": "outros" if outros else "vazio",
                    "outros": outros_qtd,
                    "outros_nomes": nomes_outros,
                }

            # Alvo encontrado: segue o pipeline so com ele.
            deteccoes = alvos
            print(f"🎯 Alvo {alvo_canonico!r}: {len(alvos)} encontrado(s), "
                  f"{outros_qtd} outro(s) descartado(s)")

            # Dica de enquadramento: bbox encostando na borda = peca cortada.
            # So faz sentido quando ha UM alvo (com varios, o app nao sabe a
            # qual a dica se refere).
            if len(alvos) == 1:
                x1n, y1n, x2n, y2n = alvos[0]["bbox"]
                margem = 0.02
                if (x1n <= margem or y1n <= margem
                        or x2n >= 1 - margem or y2n >= 1 - margem):
                    dica_alvo = "cortado"
                elif alvos[0]["w"] * alvos[0]["h"] < 0.02:
                    dica_alvo = "longe"

        # ── Etapa 2.5: VALIDAÇÃO SEMÂNTICA COM A CENA COMPLETA ───────────────
        # O NMS geométrico pega caixas sobrepostas, mas o YOLO pode marcar o
        # mesmo objeto com caixas afastadas (ex.: duas metades de um SSD grande).
        # Aqui perguntamos ao Gemini, olhando a CENA INTEIRA, quantas unidades
        # físicas de cada tipo existem de fato — e usamos isso como TETO.
        # Se ele vê 1 SSD mas temos 2 marcações de SSD, fica só a de maior
        # confiança. Se ele vê 2 RAMs e temos 2 marcações, ambas permanecem.
        nomes_repetidos = [n for n in {d["nome"] for d in deteccoes}
                           if sum(1 for d in deteccoes if d["nome"] == n) > 1]
        if nomes_repetidos and cena_bytes:
            limites = contar_componentes_na_cena(cena_bytes, nomes_repetidos)
            if limites:
                print(f"🧠 Cena diz: {limites}")
                filtradas = []
                for nome in {d["nome"] for d in deteccoes}:
                    grupo = [d for d in deteccoes if d["nome"] == nome]
                    teto  = limites.get(nome)
                    # Só corta se o Gemini deu um número válido E menor que o
                    # que temos. Nunca corta abaixo de 1 (se ele errou e disse
                    # 0, mantemos a melhor — o recorte já foi confirmado antes).
                    if teto is not None and 0 < teto < len(grupo):
                        grupo.sort(key=lambda d: d["confianca"], reverse=True)
                        cortadas = len(grupo) - teto
                        grupo = grupo[:teto]
                        print(f"   ↳ '{nome}': {cortadas} marcação(ões) extra "
                              f"removida(s) — a cena mostra {teto}")
                    filtradas.extend(grupo)
                deteccoes = filtradas

        # ── Etapa 3: SORT associa IDs estáveis entre frames ──────────────────
        deteccoes = _tracker.atualizar(deteccoes)

        # Remove bbox do retorno (campo interno do SORT)
        for d in deteccoes:
            d.pop("bbox", None)

        print(f"🎯 Track IDs: {[d['track_id'] for d in deteccoes]}")
        resp = {"sucesso": True, "detectados": deteccoes}
        if alvo_canonico:
            resp["alvo"]            = alvo_canonico
            resp["alvo_encontrado"] = True
            resp["outros"]          = outros_qtd
            if dica_alvo:
                resp["dica"] = dica_alvo
        return resp
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}

# ── /descrever — Gemini descreve componentes ─────────────────────────────────
@app.post("/descrever")
async def descrever(
    imagem:      UploadFile = File(...),
    componentes: str        = Form("[]"),
):
    try:
        b    = await imagem.read()
        comp = json.loads(componentes)
        resultado = []
        for det in comp:
            try:
                info = descrever_com_gemini(b, det["nome"])
                resultado.append({**det, **info})
            except:
                resultado.append({**det,"tipo":"Hardware",
                    "descricao":"Componente identificado visualmente.",
                    "dica":"Consulte o manual para especificações.","modelo":None})
        return {"sucesso": True, "componentes": resultado}
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}

# ── /analisar — YOLO + Gemini combinados ─────────────────────────────────────
@app.post("/analisar")
async def analisar(imagem: UploadFile = File(...)):
    try:
        b   = await imagem.read()
        img = bytes_para_cv2(b)
        h, w = img.shape[:2]

        if modelo_yolo is None:
            return {"sucesso": False, "erro": "YOLO offline"}

        results   = modelo_yolo(img, verbose=False)[0]
        deteccoes = []
        for box in results.boxes:
            conf = float(box.conf[0])
            if conf >= CONFIANCA_MIN:
                x1,y1,x2,y2 = box.xyxy[0].tolist()
                nome_raw = modelo_yolo.names[int(box.cls[0])]
                nome = normalizar_nome_exibicao(traduzir_nome(nome_raw))
                deteccoes.append({
                    "nome": nome, "confianca": round(conf,2),
                    "x": round((x1+x2)/2/w,4), "y": round((y1+y2)/2/h,4),
                    "w": round((x2-x1)/w,4),   "h": round((y2-y1)/h,4),
                })

        if not deteccoes:
            return {"sucesso": False, "componentes": []}

        componentes_finais = []
        for det in deteccoes:
            try:
                info = descrever_com_gemini(b, det["nome"])
                componentes_finais.append({**det, **info})
            except:
                componentes_finais.append({**det,"tipo":"Hardware",
                    "descricao":"Componente identificado.","dica":"","modelo":None})

        return {"sucesso": True, "detectados": deteccoes, "componentes": componentes_finais}
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}

# ── /target — Target Vision (YOLO + Gemini) ───────────────────────────────────
@app.post("/target")
async def target(
    imagem:     UploadFile = File(...),
    componente: str        = Form("componente de hardware"),
    prompt:     str        = Form(""),
    preciso:    str        = Form("0"),
):
    try:
        b        = await imagem.read()
        eh_preciso = preciso == "1"

        # ── ETAPA 1: best_v3 (pipeline principal) ─────────────────────────────
        if eh_preciso and modelo_yolo:
            try:
                img = bytes_para_cv2(b)
                h, w = img.shape[:2]
                results = modelo_yolo(img, verbose=False)[0]
                detectados = []
                comp_norm = normalizar_componente(componente)
                for box in results.boxes:
                    conf = float(box.conf[0])
                    nome_raw = modelo_yolo.names[int(box.cls[0])]
                    nome = traduzir_nome(nome_raw)
                    match = (
                        nome.lower() == comp_norm or
                        comp_norm in nome.lower() or
                        nome.lower() in comp_norm
                    )
                    if conf >= 0.35 and match:
                        x1,y1,x2,y2 = box.xyxy[0].tolist()
                        detectados.append({
                            "encontrado": True,
                            "confianca": int(conf*100),
                            "posicao": {
                                "x":       round((x1+x2)/2/w,4),
                                "y":       round((y1+y2)/2/h,4),
                                "largura": round((x2-x1)/w,4),
                                "altura":  round((y2-y1)/h,4),
                            }
                        })
                if detectados:
                    melhor = max(detectados, key=lambda d: d["confianca"])
                    print(f"✅ Target best_v3: {componente} conf={melhor['confianca']}%")
                    return {"sucesso": True, **melhor}
            except Exception as e:
                print(f"⚠️ Target best_v3 erro: {e}")

        # Gemini como fallback
        prompt_final = prompt if prompt else (
            f'Localize "{componente}" nesta imagem. '
            f'Responda SOMENTE JSON: {{"encontrado":true/false,"confianca":0-100,'
            f'"posicao":{{"x":0.0-1.0,"y":0.0-1.0,"largura":0.0-1.0,"altura":0.0-1.0}}}}'
        )
        dados = gemini_json(prompt_final, b)
        return {
            "sucesso":    True,
            "encontrado": dados.get("encontrado", False),
            "confianca":  dados.get("confianca", 0),
            "posicao":    dados.get("posicao",
                          {"x":0.5,"y":0.5,"largura":0.3,"altura":0.3}),
        }
    except Exception as e:
        print(f"❌ Target erro: {e}")
        return {"sucesso": True, "encontrado": False, "confianca": 0,
                "posicao": {"x":0.5,"y":0.5,"largura":0.3,"altura":0.3}}


# ── /doutor ───────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
# /map — MODO MAP (anatomia educativa)
#
# SUBSTITUI o antigo /raiox. Em vez de "diagnosticar saúde" (que a IA não
# consegue fazer por foto — um SSD desgastado e um zerado são a mesma imagem),
# este endpoint explica a ESTRUTURA da peça: cada ponto tocável tem nome
# técnico, função e uma nota prática.
#
# COMO INSTALAR:
#   1. Cole este bloco no main.py, no lugar do bloco atual do "@app.post("/raiox")"
#      (linhas 1073-1107 do seu arquivo).
#   2. Se quiser manter o /raiox vivo por um tempo (app antigo instalado),
#      apenas ADICIONE este bloco e deixe o /raiox onde está — eles não
#      conflitam. Depois que o app novo estiver rodando, apague o /raiox.
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/map")
async def mapa_anatomia(
    imagem:     UploadFile = File(None),
    componente: str        = Form("componente de hardware"),
    x:          str        = Form(""),   # centro normalizado 0-1 (opcional)
    y:          str        = Form(""),
    w:          str        = Form(""),   # largura/altura normalizadas 0-1
    h:          str        = Form(""),
):
    """Devolve a anatomia educativa de UMA peça.

    Resposta:
    {
      "sucesso": true,
      "mapa": {
        "peca": "Memória RAM DDR2 SODIMM",
        "peca_curta": "Memória RAM",
        "resumo": "2 frases sobre a peça.",
        "divergente": false,
        "pontos": [
          {"id":1, "x":500, "y":300, "label":"Notch",
           "tipo":"conector",
           "oque":"Chave de encaixe do pente.",
           "funcao":"Impede encaixar o pente invertido no slot.",
           "pratica":"Ao comprar um pente usado, confira o notch antes.",
           "curiosidade":"A posição dele muda a cada geração de DDR."}
        ]
      }

    NOTA: as coordenadas dos pontos são SEMPRE relativas à imagem CHEIA
    enviada pelo app, mesmo quando houve recorte por bbox internamente.
    }
    """
    try:
        b = await imagem.read() if imagem else None
        if not b:
            return {"sucesso": True, "mapa": {
                "peca": componente,
                "resumo": f"Pause a câmera sobre o {componente} e tente novamente.",
                "divergente": False,
                "pontos": []}}

        # ── Recorte por bbox ──────────────────────────────────────────────────
        # Mesma lógica do /ocr_componente e do /info: quando o app manda as
        # coordenadas, recortamos SÓ aquela peça. Sem isso, com duas peças
        # iguais no quadro a IA mistura os pontos das duas.
        #
        # ⚠️ DIFERENÇA IMPORTANTE em relação ao /info e ao /ocr_componente:
        # aqueles devolvem TEXTO, então o recorte é invisível para o app. O
        # /map devolve COORDENADAS, e o Gemini as calcula em relação ao
        # RECORTE (0-1000 dentro do pedaço). Se devolvermos assim, o app
        # desenha os pontos sobre a imagem INTEIRA e eles caem fora da peça.
        # Por isso guardamos aqui a região exata que foi cortada — no fim da
        # função os pontos são convertidos de volta para o quadro completo.
        recortou = False
        crop_box = None   # (x1c, y1c, x2c, y2c) em pixels da imagem cheia
        img_dim  = None   # (W, H) da imagem cheia
        try:
            if x != "" and y != "" and w != "" and h != "":
                arr    = np.frombuffer(b, np.uint8)
                img_cv = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img_cv is not None:
                    H, W   = img_cv.shape[:2]
                    cx, cy = float(x) * W, float(y) * H
                    bw, bh = float(w) * W, float(h) * H

                    # FOLGA de 12% em cada dimensão. O recorte do YOLO às vezes
                    # sai um pouco torto ou apertado — cortando parte da peça ou
                    # a etiqueta. Uma folga proporcional faz o recorte capturar
                    # a peça inteira mesmo quando o YOLO erra um pouco. Não salva
                    # um enquadramento muito errado, mas resolve os casos de
                    # "quase certo". O clamp nas bordas evita estourar a imagem.
                    _FOLGA = 0.12
                    bw *= (1 + _FOLGA)
                    bh *= (1 + _FOLGA)

                    x1 = int(cx - bw / 2); y1 = int(cy - bh / 2)
                    x2 = int(cx + bw / 2); y2 = int(cy + bh / 2)

                    # Replica EXATAMENTE o que o recortar_box faz (padding de 4
                    # e clamp nas bordas). Precisa bater pixel a pixel, senão a
                    # conversão dos pontos fica deslocada.
                    _PAD = 4
                    x1c = max(0, x1 - _PAD)
                    y1c = max(0, y1 - _PAD)
                    x2c = min(W, x2 + _PAD)
                    y2c = min(H, y2 + _PAD)

                    # Recorte degenerado (bbox inválida) → usa imagem cheia
                    if x2c - x1c >= 8 and y2c - y1c >= 8:
                        b        = recortar_box(img_cv, x1, y1, x2, y2)
                        recortou = True
                        crop_box = (x1c, y1c, x2c, y2c)
                        img_dim  = (W, H)
        except Exception as e:
            print(f"⚠️ /map: falha ao recortar, usando imagem cheia: {e}")

        nota_recorte = (
            "- A imagem já está RECORTADA nesta peça. Se aparecer pedaço de "
            "outra peça na borda, IGNORE.\n"
            if recortou else
            "- Pode haver mais de uma peça na imagem. Foque na peça principal, "
            "a mais central e nítida.\n"
        )

        prompt = (
            f"Você é um PROFESSOR de hardware explicando a peça '{componente}' "
            f"para um estudante de manutenção de computadores.\n"
            f"Sua tarefa é ensinar a ANATOMIA da peça: apontar as partes "
            f"visíveis e explicar o que cada uma é e para que serve.\n\n"
            f"Sistema de coordenadas: x=0 esquerda, x=1000 direita, "
            f"y=0 topo, y=1000 base.\n\n"
            f"Responda SOMENTE JSON puro, sem markdown:\n"
            f'{{"peca":"Nome técnico completo da peça",'
            f'"peca_curta":"Nome curto, 2 ou 3 palavras",'
            f'"identidade":{{"tipo":"SSD SATA","fabricante":"Kingston",'
            f'"modelo":"A400","variante":"240GB","confianca":85}},'
            f'"resumo":"2 frases explicando o que é esta peça e o papel dela no computador.",'
            f'"composicao":[{{"titulo":"Nome do componente interno",'
            f'"explicacao":"O que ele é/faz, em 1 frase curta."}}],'
            f'"quiz":{{"pergunta":"Uma pergunta sobre esta peça.",'
            f'"opcoes":["alternativa A","alternativa B","alternativa C"],'
            f'"correta":0}},'
            f'"divergente":false,'
            f'"pontos":[{{"id":1,"x":500,"y":300,"label":"Nome curto da parte",'
            f'"tipo":"conector",'
            f'"formato":"completo",'
            f'"oque":"O que é esta parte, em 1 frase simples.",'
            f'"funcao":"Para que ela serve, em 1 frase.",'
            f'"pratica":"Uma situação REAL onde isso importa. 1 frase.",'
            f'"curiosidade":"Um fato interessante e pouco conhecido. 1 frase. '
            f'Use string vazia se não houver nada realmente interessante.",'
            f'"informacoes":[],"simbolos":[]}}]}}\n\n'
            f"CAMPO 'formato' — SEMPRE um destes três: 'completo' (padrão), "
            f"'etiqueta' (o adesivo de specs) ou 'curiosidade' (logo/selo). "
            f"As regras de cada um estão na seção ETIQUETAS abaixo.\n"
            f"CAMPOS 'informacoes' e 'simbolos' — listas de "
            f'{{"titulo":"...","explicacao":"..."}}, usadas SÓ quando '
            f"formato='etiqueta'. Nos outros formatos, deixe [].\n\n"
            f"═══ CAMPO 'identidade' — A FICHA DE IDENTIFICAÇÃO DA PEÇA ═══\n"
            f"Identifique a peça em CAMADAS, do geral ao específico, com o que "
            f"você conseguir ver. Preencha só até onde tiver certeza razoável — "
            f"deixe VAZIO ('') o que não conseguir determinar. NUNCA invente.\n"
            f"  • tipo: a categoria (ex.: 'SSD SATA', 'Memória RAM DDR4', "
            f"'Placa de Vídeo'). Quase sempre dá para preencher.\n"
            f"  • fabricante: a marca, se houver logo ou nome legível "
            f"(ex.: 'Kingston', 'Samsung', 'Corsair'). Vazio se não reconhecer.\n"
            f"  • modelo: a linha/família do produto, se der para ler na "
            f"etiqueta (ex.: 'A400', 'Fury', 'EVO 870'). Vazio se não tiver.\n"
            f"  • variante: capacidade ou detalhe final (ex.: '240GB', '8GB "
            f"3200MHz'). Vazio se não der.\n"
            f"  • confianca: um número de 0 a 100 dizendo o quanto você confia "
            f"na identificação do MODELO (não do tipo). Se só sabe o tipo, "
            f"confiança baixa (~30); se leu tudo na etiqueta com clareza, alta "
            f"(~90). Seja honesto — confiança baixa é melhor que erro.\n\n"
            f"Crie UMA pergunta de múltipla escolha sobre esta peça. 3 "
            f"alternativas, UMA correta. O campo 'correta' é o ÍNDICE da certa "
            f"(0, 1 ou 2).\n"
            f"REGRA IMPORTANTE: a pergunta DEVE ser sobre algo que você "
            f"ENSINOU EM UM DOS PONTOS ('pontos') — a função de uma parte "
            f"marcada, o que um dado da etiqueta significa, qual interface a "
            f"peça usa. NÃO pergunte sobre nada que não apareça nos pontos "
            f"(o usuário só leu os pontos; perguntar fora deles é injusto). "
            f"Nada de pegadinha. Ex.: se um ponto explica o conector SATA, "
            f"pergunta:'Qual a função do conector SATA no SSD?', "
            f"opcoes:['Conectar o SSD à placa e transferir dados e "
            f"energia','Armazenar os dados permanentemente','Resfriar o "
            f"controlador'], correta:0.\n"
            f"Linguagem simples, para quem está aprendendo.\n\n"
            f"═══ CAMPO 'composicao' — A ESTRUTURA COMPLETA DA PEÇA ═══\n"
            f"Esta é a lista de TODOS os componentes/partes que formam esta "
            f"peça, mesmo os que você NÃO marcou com um ponto. É a referência "
            f"completa: enquanto os pontos são só alguns destaques, a "
            f"composição ensina a peça inteira.\n"
            f"Liste de 5 a 10 itens, cada um {{titulo, explicacao}}. Inclua "
            f"tanto o que é visível quanto o que se sabe que existe naquele "
            f"tipo de peça. Ex. para uma RAM: 'Chips de memória', 'Chip SPD', "
            f"'PCB', 'Contatos de borda', 'Notch (chave)', 'Circuito de "
            f"alimentação'. Para um SSD: 'Controlador', 'Memória NAND', "
            f"'Cache DRAM', 'Interface SATA', 'PCB', 'Carcaça metálica'.\n"
            f"Baseie-se no que é REAL para esta peça específica (a geração, a "
            f"capacidade, o formato que você vê) — não invente componentes que "
            f"aquele tipo de peça não teria. Explicação de cada item: 1 frase "
            f"curta e didática.\n\n"
            f"CAMPO 'peca_curta': nome enxuto para caber num rótulo pequeno. "
            f"Ex.: 'SSD SATA', 'Memória RAM', 'Placa de Vídeo'. "
            f"NUNCA mais de 3 palavras.\n\n"
            f"CAMPO 'tipo' — escolha SEMPRE um destes 6 valores exatos:\n"
            f"  conector      → pinos, contatos, notch, slots, encaixes, portas\n"
            f"  memoria       → chips de memória, células NAND, cache\n"
            f"  controlador   → chip controlador, processador, SPD, BIOS, firmware\n"
            f"  alimentacao   → capacitores, resistores, reguladores, trilhas de energia\n"
            f"  identificacao → etiqueta, serial, marca, modelo, código de barras, QR\n"
            f"  dissipacao    → dissipador, heat spreader, cooler, pasta térmica, aletas\n\n"
            f"═══ O QUE MERECE UM PONTO ═══\n"
            f"Cada ponto precisa ENSINAR algo. Poucos pontos excelentes valem "
            f"mais que muitos pontos óbvios.\n"
            f"PRIORIZE: conectores, controladores, chips, memória NAND, cache, "
            f"PCB, dissipadores, sensores, reguladores, interfaces (SATA/NVMe), "
            f"capacitores e demais componentes eletrônicos relevantes.\n\n"
            f"NUNCA aponte (não ensinam nada):\n"
            f"  ✗ parafusos e furos de fixação\n"
            f"  ✗ abas, chanfros e recortes estruturais\n"
            f"  ✗ partes repetidas (se há 4 iguais, aponte UMA vez)\n"
            f"  ✗ a carcaça inteira, o corpo da peça, a 'superfície'\n"
            f"  ✗ código de barras ou número de série como ponto SOLTO — "
            f"eles pertencem à etiqueta e entram na lista 'informacoes' dela, "
            f"nunca como um ponto próprio\n"
            f"  ✗ qualquer detalhe puramente mecânico sem valor didático\n\n"
            f"═══ ETIQUETAS, LOGOTIPOS E SELOS ═══\n"
            f"Estes elementos usam um CAMPO ESPECIAL 'formato' que muda o que "
            f"o popup mostra. Escolha o formato certo:\n\n"
            f"1) ETIQUETA (o adesivo com specs) → formato:'etiqueta'.\n"
            f"   Gere UM ÚNICO ponto para a etiqueta inteira (NUNCA vários "
            f"pontos na mesma etiqueta). Preencha DUAS listas:\n"
            f"   • 'informacoes' — leia a etiqueta INTEIRA e liste TODOS os "
            f"dados escritos que conseguir ler, cada um com explicação curta. "
            f"NÃO pare em 2 ou 3: uma etiqueta típica tem de 5 a 10 dados "
            f"(capacidade, modelo, part number, serial, tensão/corrente, "
            f"velocidade, país de origem, data/lote, revisão...). Ex.: "
            f"titulo:'240GB', explicacao:'Capacidade de armazenamento'. "
            f"titulo:'DC+5.0V 1A', explicacao:'Tensão e corrente de operação'. "
            f"titulo:'SA400S37', explicacao:'Part number do modelo'.\n"
            f"   • 'simbolos' — liste TODOS os símbolos/logos de certificação "
            f"visíveis, cada um explicado (costumam ser vários juntos): CE, "
            f"FCC, UL, KC, RoHS, WEEE (lixeira riscada), triângulo de "
            f"reciclagem, etc. Ex.: titulo:'CE', explicacao:'Conformidade com "
            f"normas europeias'. titulo:'Lixeira riscada', explicacao:'Descarte "
            f"em ponto de coleta, não no lixo comum'.\n"
            f"   Só liste o que REALMENTE consegue ler/reconhecer; o que "
            f"estiver ilegível, ignore (nunca invente um valor).\n"
            f"   Se houver LOGOTIPO da fabricante NA etiqueta (ou coladinho "
            f"nela), NÃO crie um ponto separado para o logo — em vez disso, "
            f"preencha o campo 'curiosidade' deste mesmo ponto com um fato "
            f"curto sobre a fabricante. Assim a etiqueta e o logo viram UM "
            f"pin só.\n"
            f"   Para a etiqueta, os campos oque/funcao/pratica ficam VAZIOS "
            f"(as listas e a curiosidade substituem eles).\n"
            f"   LEIA de verdade: só inclua o que você REALMENTE consegue ver "
            f"e entender. O que estiver ilegível ou que você não reconhecer, "
            f"IGNORE — nunca invente um valor ou um significado.\n\n"
            f"2) LOGOTIPO ou SELO SOLTO (longe de qualquer etiqueta) → "
            f"formato:'curiosidade'.\n"
            f"   Só use este caso quando o logo/selo estiver claramente "
            f"SEPARADO de uma etiqueta. Gere UM ponto e preencha SÓ o campo "
            f"'curiosidade'. oque/funcao/pratica ficam VAZIOS.\n"
            f"   Ex.: label:'Logotipo Kingston', curiosidade:'Fundada em 1987 "
            f"nos EUA, é uma das maiores fabricantes de memória do mundo.'\n\n"
            f"3) Todas as OUTRAS partes (conector, chip, capacitor...) → "
            f"formato:'completo' (o padrão, com oque/funcao/pratica).\n\n"
            f"═══ CAMPO 'pratica' ═══\n"
            f"Não repita a função. Mostre uma SITUAÇÃO REAL: ao comprar uma "
            f"peça usada, durante uma manutenção, ao pedir garantia, num "
            f"upgrade, ao diagnosticar um defeito.\n\n"
            f"═══ CAMPO 'curiosidade' ═══\n"
            f"Um fato que faça o estudante pensar 'não sabia disso'. "
            f"Ex.: 'O SSD não tem nenhuma peça móvel.' / 'Nem todo fabricante "
            f"produz a própria memória NAND.'\n"
            f"Se não tiver nada realmente interessante, devolva string vazia — "
            f"melhor vazio do que uma obviedade.\n\n"
            f"═══ REGRAS GERAIS ═══\n"
            f"- Gere SEMPRE por volta de 5 pontos (no mínimo 4, no máximo 6). "
            f"Seja CONSISTENTE: a mesma peça deve gerar mais ou menos a mesma "
            f"quantidade de pontos toda vez. Escolha as 5 partes MAIS "
            f"importantes e didáticas — as que todo estudante deveria conhecer "
            f"naquela peça.\n"
            f"- Pontos bem separados: distância mínima de 150 entre eles. "
            f"Se dois elementos interessantes estão muito próximos, escolha "
            f"só o mais importante dos dois.\n"
            f"- Só aponte o que está REALMENTE VISÍVEL. NUNCA invente uma "
            f"parte que você não consegue ver na imagem.\n"
            f"- Se a peça está de cabeça para baixo ou de lado, considere a "
            f"orientação REAL da imagem ao dar as coordenadas.\n"
            f"- Linguagem DIDÁTICA e simples. Evite jargão sem explicar.\n"
            f"- NÃO diagnostique saúde, desgaste, defeito ou vida útil — "
            f"isso não é possível por foto e não é o objetivo aqui.\n"
            f"- NÃO estime preço nem valor de mercado.\n"
            f"- Cada campo de texto: no máximo 1 frase curta.\n"
            f"{nota_recorte}"
            f"- divergente=true SOMENTE se a imagem mostrar CLARAMENTE um "
            f"componente diferente de '{componente}'.\n"
        )

        resultado = gemini_json(prompt, b)

        # ── Saneamento da resposta ────────────────────────────────────────────
        resultado.setdefault("peca", componente)
        resultado.setdefault("peca_curta", "")
        resultado.setdefault("resumo", "")
        resultado.setdefault("composicao", [])
        resultado.setdefault("identidade", {})
        resultado.setdefault("quiz", {})
        resultado.setdefault("divergente", False)
        resultado.setdefault("pontos", [])

        # peca_curta é o que aparece no card do rodapé, onde só cabem ~2-3
        # palavras. Se o Gemini não mandar, encurta o nome completo aqui.
        if not str(resultado.get("peca_curta") or "").strip():
            palavras = str(resultado.get("peca") or componente).split()
            resultado["peca_curta"] = " ".join(palavras[:3])

        # Composição: lista {titulo, explicacao} da estrutura completa da peça.
        comp_ok = []
        if isinstance(resultado.get("composicao"), list):
            for it in resultado["composicao"]:
                if isinstance(it, dict):
                    t = str(it.get("titulo", "") or "").strip()
                    x = str(it.get("explicacao", "") or "").strip()
                    if t:
                        comp_ok.append({"titulo": t, "explicacao": x})
        resultado["composicao"] = comp_ok

        # Identidade hierárquica (fingerprint via Gemini): tipo → fabricante →
        # modelo → variante + confiança. Base da Biblioteca Técnica: a ficha
        # começa no nível que a IA conseguir e é promovida quando ler melhor.
        ident = resultado.get("identidade")
        ident_ok = {"tipo": "", "fabricante": "", "modelo": "",
                    "variante": "", "confianca": 0}
        if isinstance(ident, dict):
            ident_ok["tipo"]       = str(ident.get("tipo", "") or "").strip()
            ident_ok["fabricante"] = str(ident.get("fabricante", "") or "").strip()
            ident_ok["modelo"]     = str(ident.get("modelo", "") or "").strip()
            ident_ok["variante"]   = str(ident.get("variante", "") or "").strip()
            try:
                c = int(ident.get("confianca", 0))
            except (TypeError, ValueError):
                c = 0
            ident_ok["confianca"] = min(100, max(0, c))
        # Se a IA não deu o tipo, usa o componente que o app já sabia (do YOLO)
        if not ident_ok["tipo"]:
            ident_ok["tipo"] = componente
        resultado["identidade"] = ident_ok

        # Quiz: {pergunta, opcoes[], correta}. Valida o índice da correta e
        # exige pelo menos 2 opções, senão descarta (o botão só aparece se
        # houver quiz válido).
        quiz = resultado.get("quiz")
        quiz_ok = {}
        if isinstance(quiz, dict):
            perg = str(quiz.get("pergunta", "") or "").strip()
            ops  = quiz.get("opcoes")
            if perg and isinstance(ops, list):
                ops = [str(o).strip() for o in ops if str(o).strip()]
                if len(ops) >= 2:
                    try:
                        correta = int(quiz.get("correta", 0))
                    except (TypeError, ValueError):
                        correta = 0
                    if correta < 0 or correta >= len(ops):
                        correta = 0
                    quiz_ok = {
                        "pergunta": perg,
                        "opcoes":   ops,
                        "correta":  correta,
                    }
        resultado["quiz"] = quiz_ok

        if resultado.get("divergente"):
            resultado["pontos"] = []

        # Normaliza o 'tipo' de cada ponto: se a IA inventar um valor fora da
        # lista, cai em 'conector' (neutro). Isso evita pin sem cor no app.
        TIPOS_VALIDOS = {
            "conector", "memoria", "controlador",
            "alimentacao", "identificacao", "dissipacao",
        }
        pontos_ok = []
        for i, p in enumerate(resultado.get("pontos") or []):
            if not isinstance(p, dict):
                continue
            tipo = str(p.get("tipo", "")).strip().lower()
            # tolera acentos/variações que o Gemini às vezes devolve
            tipo = (tipo.replace("ó", "o").replace("ã", "a")
                        .replace("ç", "c").replace("é", "e")
                        .replace("í", "i").replace("á", "a"))
            if tipo not in TIPOS_VALIDOS:
                tipo = "conector"

            # ── Formato do popup ─────────────────────────────────────────
            formato = str(p.get("formato", "completo")).strip().lower()
            if formato not in ("completo", "etiqueta", "curiosidade"):
                formato = "completo"

            # ── Listas da etiqueta (titulo + explicacao) ─────────────────
            def _limpa_lista(raw):
                out = []
                if isinstance(raw, list):
                    for it in raw:
                        if isinstance(it, dict):
                            t = str(it.get("titulo", "") or "").strip()
                            x = str(it.get("explicacao", "") or "").strip()
                            if t or x:
                                out.append({"titulo": t, "explicacao": x})
                return out

            informacoes = _limpa_lista(p.get("informacoes"))
            simbolos    = _limpa_lista(p.get("simbolos"))

            # Coerência: só o formato 'etiqueta' carrega listas; se a IA
            # mandou listas com outro formato, promove para etiqueta se houver
            # conteúdo, senão descarta as listas.
            if formato != "etiqueta":
                if informacoes or simbolos:
                    formato = "etiqueta"
                else:
                    informacoes, simbolos = [], []

            # Uma etiqueta é SEMPRE identificação — o ícone do pin (label) tem
            # de bater com isso. Sem esta linha, quando o Gemini mandava a
            # etiqueta com tipo 'conector' (ou um tipo fora da lista, que caía
            # no fallback 'conector'), o holograma mostrava o ícone de cabo em
            # cima de um adesivo de specs. Aqui garantimos o ícone certo.
            if formato == "etiqueta":
                tipo = "identificacao"
            # O mesmo vale para o logo/selo solto (curiosidade da fabricante).
            elif formato == "curiosidade":
                tipo = "identificacao"

            # ── Coordenadas ──────────────────────────────────────────────
            try:
                px = float(p.get("x", 500))
                py = float(p.get("y", 500))
            except (TypeError, ValueError):
                px, py = 500.0, 500.0
            px = min(1000.0, max(0.0, px))
            py = min(1000.0, max(0.0, py))

            pontos_ok.append({
                "id":      p.get("id", i + 1),
                "x":       px,
                "y":       py,
                "label":   (p.get("label", "") or "").strip(),
                "tipo":    tipo,
                "formato":     formato,
                "oque":        (p.get("oque", "") or "").strip(),
                "funcao":      (p.get("funcao", "") or "").strip(),
                "pratica":     (p.get("pratica", "") or "").strip(),
                "curiosidade": (p.get("curiosidade", "") or "").strip(),
                "informacoes": informacoes,
                "simbolos":    simbolos,
            })

        # ── CONVERSÃO DAS COORDENADAS (recorte → imagem cheia) ────────────────
        # O Gemini viu apenas o RECORTE, então devolveu 0-1000 dentro dele.
        # O app desenha sobre a imagem INTEIRA. Sem esta conversão, um ponto
        # no centro da peça vai parar no centro da TELA — foi exatamente o
        # bug dos pins flutuando fora do componente.
        #
        #   x_cheia = (x1c + (px/1000) * larg_recorte) / W * 1000
        #
        # A mesma conta para Y. Quando não houve recorte, as coordenadas já
        # estão no referencial certo e nada muda.
        if recortou and crop_box and img_dim:
            x1c, y1c, x2c, y2c = crop_box
            W, H               = img_dim
            larg_crop          = x2c - x1c
            alt_crop           = y2c - y1c
            if larg_crop > 0 and alt_crop > 0 and W > 0 and H > 0:
                for p in pontos_ok:
                    px_abs = x1c + (p["x"] / 1000.0) * larg_crop
                    py_abs = y1c + (p["y"] / 1000.0) * alt_crop
                    p["x"]  = round(px_abs / W * 1000.0, 1)
                    p["y"]  = round(py_abs / H * 1000.0, 1)
                print(f"🗺️ /map: {len(pontos_ok)} pontos convertidos "
                      f"do recorte ({larg_crop}x{alt_crop}) para o quadro "
                      f"cheio ({W}x{H})")

        # ── Afasta pins colados demais ────────────────────────────────────────
        # Mesmo pedindo distância mínima no prompt, o Gemini às vezes agrupa
        # pontos (ex.: 3 selos lado a lado na etiqueta). Aqui, JÁ com as
        # coordenadas no referencial da imagem cheia, descartamos um ponto
        # quando ele cai perto demais de outro já aceito. Fica o primeiro —
        # como o Gemini tende a listar do mais importante ao menos, isso
        # costuma manter o melhor de cada aglomerado.
        #
        # O limiar é em unidades 0-1000 na MENOR dimensão da tela, para o
        # afastamento parecer o mesmo em retrato e paisagem.
        DIST_MIN = 70.0  # ~7% da tela; sobe se ainda ficarem juntos
        filtrados = []
        for p in pontos_ok:
            colado = False
            for q in filtrados:
                dx = p["x"] - q["x"]
                dy = p["y"] - q["y"]
                if (dx * dx + dy * dy) < (DIST_MIN * DIST_MIN):
                    colado = True
                    break
            if not colado:
                filtrados.append(p)
        if len(filtrados) < len(pontos_ok):
            print(f"🗺️ /map: {len(pontos_ok) - len(filtrados)} pin(s) "
                  f"removido(s) por estarem colados demais")
        pontos_ok = filtrados

        resultado["pontos"] = pontos_ok

        return {"sucesso": True, "mapa": resultado}

    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


@app.post("/doutor")
async def doutor(
    sintoma:             str        = Form(""),
    respostas_perguntas: str        = Form(""),
    imagem:              UploadFile = File(None),
):
    try:
        b = await imagem.read() if imagem else None

        system_prompt = (
            "Você é Dr. Hardware, especialista em diagnóstico de PCs e notebooks.\n"
            "ESCOPO: RAM, SSD, CPU, GPU, placa-mãe, fonte, cooler, Windows, drivers, BIOS.\n"
            "FORA DO ESCOPO: celulares, TVs, consoles, culinária, esportes, etc.\n\n"
            "Responda SOMENTE JSON puro sem markdown:\n"
            '{"componente":"RAM","explicacao":"Diagnóstico.\\n\\nSugere-se:\\n1- Passo",'
            '"confianca":85,"svg_id":"svg_ram"}\n'
            "svg_id: svg_ram, svg_ssd, svg_cpu, svg_gpu, svg_motherboard, svg_psu, "
            "svg_hdd, svg_cooler, svg_generico ou svg_bloqueio\n"
        )
        contexto = system_prompt
        if sintoma:
            contexto += f'\nSintoma: "{sintoma}"\n'
        else:
            contexto += "\nO usuário enviou apenas uma imagem. Analise-a.\n"
        if respostas_perguntas:
            contexto += f"\nRespostas:\n{respostas_perguntas}\n"

        resultado = gemini_json(contexto, b)
        return {"sucesso": True, "diagnostico": resultado}
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}

# ── /perguntas ────────────────────────────────────────────────────────────────
@app.post("/perguntas")
async def perguntas(sintoma: str = Form("")):
    try:
        if not sintoma:
            return {"sucesso": False, "erro": "Sintoma vazio"}
        prompt = (
            f'Sintoma: "{sintoma}"\n'
            f"Especialista em hardware de PCs. Gere ATÉ 3 perguntas técnicas ou lista vazia.\n"
            f"Responda SOMENTE JSON puro:\n"
            f'{{"perguntas":[{{"id":1,"texto":"Pergunta?","tipo":"sim_nao"}}]}}\n'
            f"tipos: sim_nao, multipla_escolha (com opcoes:[]), imagem_opcional\n"
            f"Se sintoma for fora do escopo ou muito específico, retorne perguntas:[]"
        )
        resultado = gemini_json(prompt)
        return {"sucesso": True, "perguntas": resultado.get("perguntas", [])}
    except:
        return {"sucesso": True, "perguntas": []}

# ── /dica ─────────────────────────────────────────────────────────────────────
@app.post("/dica")
async def dica(prompt: str = Form("")):
    try:
        if not prompt:
            return {"sucesso": False, "erro": "Prompt vazio"}
        txt = gemini_gerar(prompt)
        return {"sucesso": True, "dica": txt.strip()}
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}

# ── /ocr ──────────────────────────────────────────────────────────────────────
@app.post("/ocr")
async def ocr(imagem: UploadFile = File(...)):
    try:
        b      = await imagem.read()
        prompt = (
            "Analise esta etiqueta de notebook ou PC. Extraia o modelo exato.\n"
            "Responda SOMENTE JSON puro: {\"modelo\": \"Lenovo IdeaPad 3 15ITL6\"}\n"
            "Se não identificar claramente, retorne modelo vazio: ''\n"
            "NUNCA invente modelos."
        )
        dados = gemini_json(prompt, b)
        modelo_encontrado = dados.get("modelo", "").strip()
        if modelo_encontrado:
            return {"sucesso": True, "modelo": modelo_encontrado}
        return {"sucesso": False, "erro": "Modelo não identificado."}, 422
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}

# ── /ocr_componente ───────────────────────────────────────────────────────────
# Lê a etiqueta de UM componente (pente de RAM, SSD, etc.) e extrai marca e
# capacidade de forma rápida, para o subtítulo do popup de ações — sem depender
# do /info nem esperar o Gemini popular o cache. Diferente do /ocr, que lê o
# modelo de um notebook/PC inteiro.
@app.post("/ocr_componente")
async def ocr_componente(
    imagem:     UploadFile = File(...),
    componente: str        = Form(""),
    x:          str        = Form(""),   # centro normalizado 0-1 (opcional)
    y:          str        = Form(""),
    w:          str        = Form(""),   # largura/altura normalizadas 0-1
    h:          str        = Form(""),
):
    try:
        b = await imagem.read()
        # Se vierem coordenadas, recorta SÓ a região daquela peça antes de ler.
        # Sem isso, com 2 peças iguais na foto o Gemini escolhe uma etiqueta ao
        # acaso e troca os dados entre elas. O recorte elimina a ambiguidade.
        try:
            if x != "" and y != "" and w != "" and h != "":
                arr = np.frombuffer(b, np.uint8)
                img_cv = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img_cv is not None:
                    H, W = img_cv.shape[:2]
                    cx, cy = float(x) * W, float(y) * H
                    bw, bh = float(w) * W, float(h) * H
                    x1 = int(cx - bw / 2); y1 = int(cy - bh / 2)
                    x2 = int(cx + bw / 2); y2 = int(cy + bh / 2)
                    b = recortar_box(img_cv, x1, y1, x2, y2)
        except Exception as e:
            print(f"⚠️ /ocr_componente: falha ao recortar, usando imagem cheia: {e}")
        ctx = f"O componente é um(a) '{componente}'.\n" if componente else ""
        prompt = (
            "Você está lendo a ETIQUETA de um componente de hardware "
            "(pente de memória, SSD, HD, etc.).\n"
            f"{ctx}"
            "Extraia APENAS o que estiver LITERALMENTE impresso na etiqueta:\n"
            "- marca: fabricante impresso (ex: Kingston, ProMOS, Samsung, Hynix)\n"
            "- capacidade: valor de armazenamento/memória impresso "
            "(ex: 1GB, 8GB, 240GB, 1TB)\n"
            "Responda SOMENTE JSON puro sem markdown:\n"
            '{"marca": "ProMOS", "capacidade": "1GB"}\n'
            "REGRAS:\n"
            "- Só preencha o que LER de fato na etiqueta. NUNCA invente.\n"
            "- Campo ilegível ou ausente → string vazia \"\".\n"
            "- A imagem já está recortada nesta peça. Se aparecer pedaço de "
            "outra peça na BORDA, IGNORE — leia só a etiqueta da peça central.\n"
            "- capacidade: use o formato curto com unidade (1GB, 512MB, 240GB)."
        )
        dados = gemini_json(prompt, b)
        marca      = (dados.get("marca", "") or "").strip()
        capacidade = (dados.get("capacidade", "") or "").strip()
        # Sucesso se leu ao menos um dos dois campos
        if marca or capacidade:
            return {"sucesso": True, "marca": marca, "capacidade": capacidade}
        return {"sucesso": False, "erro": "Etiqueta ilegível",
                "marca": "", "capacidade": ""}
    except Exception as e:
        return {"sucesso": False, "erro": str(e), "marca": "", "capacidade": ""}

# ── /preco ────────────────────────────────────────────────────────────────────
@app.post("/preco")
async def preco(componente: str = Form(""), modelo: str = Form("")):
    try:
        if not componente:
            return {"sucesso": False, "erro": "Componente vazio"}
        identificador = f"{componente} {modelo}".strip() if modelo else componente
        prompt = (
            f"Especialista em hardware brasileiro. Preço de mercado: '{identificador}'.\n"
            f"Lojas: Kabum, Pichau, Amazon BR, Mercado Livre.\n"
            f"Responda SOMENTE JSON puro:\n"
            f'{{"faixa":"R$ 120 – 350","nota":"Varia conforme capacidade e marca."}}\n'
            f"- faixa: formato 'R$ X – Y', valores inteiros\n"
            f"- nota: máximo 8 palavras em português"
        )
        dados = gemini_json(prompt)
        return {"sucesso": True, "faixa": dados.get("faixa",""),
                "nota": dados.get("nota",""), "componente_normalizado": identificador}
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}

# ── /upgrade ──────────────────────────────────────────────────────────────────
@app.post("/upgrade")
async def upgrade(componente: str = Form(""), modelo: str = Form("")):
    try:
        if not componente:
            return {"sucesso": False, "erro": "Componente vazio"}
        prompt = (
            f"Especialista em hardware brasileiro.\n"
            f"Componente: '{componente}' | Equipamento: '{modelo or 'genérico'}'\n"
            f"Gere 4 produtos compatíveis disponíveis no Brasil com preços realistas.\n"
            f"Responda SOMENTE JSON puro:\n"
            f'{{"ofertas":[{{"nome":"Kingston NV3 500GB M.2 NVMe","preco":"R$ 289",'
            f'"avaliacao":4.8,"loja":"Amazon","url":"https://amazon.com.br/s?k=Kingston+NV3",'
            f'"thumbnail":""}}],'
            f'"url_ver_todos":"https://www.amazon.com.br/s?k={urllib.parse.quote(componente)}"}}'
        )
        dados = gemini_json(prompt)
        return {"sucesso": True, "ofertas": dados.get("ofertas",[]),
                "url_ver_todos": dados.get("url_ver_todos","")}
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}

# ── /sugestoes ────────────────────────────────────────────────────────────────
@app.get("/sugestoes")
async def sugestoes():
    prompt = (
        "Gere exatamente 6 modelos populares de notebooks ou PCs.\n"
        "Apenas marca + linha (ex: 'Dell Inspiron', 'Lenovo IdeaPad').\n"
        "Responda SOMENTE JSON: {\"modelos\": [\"Modelo 1\", ...]}"
    )
    try:
        dados = gemini_json(prompt)
        modelos = dados.get("modelos", [])
        if len(modelos) == 6:
            return {"sucesso": True, "modelos": modelos}
        raise ValueError("Quantidade incorreta")
    except:
        return {"sucesso": True, "modelos": [
            "Lenovo IdeaPad","Dell Inspiron","HP Pavilion",
            "Acer Aspire","Samsung Galaxy Book","Asus VivoBook"]}

# ── /guia_visual ──────────────────────────────────────────────────────────────
@app.post("/guia_visual")
async def guia_visual(
    componente:   str        = Form("componente"),
    acao:         str        = Form("instalar"),
    modelo_texto: str        = Form(""),
    imagem:       UploadFile = File(None),
):
    try:
        b = await imagem.read() if imagem else None
        modelo_ctx = f"Modelo: '{modelo_texto}'.\n" if modelo_texto else ""
        prompt = (
            f"Técnico especialista em hardware. O usuário quer {acao} '{componente}'.\n"
            f"{modelo_ctx}"
            f"NUNCA gere passos de: desligar, remover bateria, abrir gabinete.\n"
            f"Comece DIRETAMENTE no 1º passo técnico (localizar slot, remover parafuso, etc).\n"
            f"Responda SOMENTE JSON puro sem markdown:\n"
            f'{{"dificuldade":"Médio","tempo_estimado":"20 minutos","risco":"Baixo",'
            f'"ferramentas":[{{"nome":"Chave Philips #0","emoji":"🪛"}}],'
            f'"passos":[{{"numero":1,"titulo":"Título curto","instrucao":"Instrução detalhada.",'
            f'"ferramenta":{{"nome":"Chave Philips #0","emoji":"🪛"}},'
            f'"destaques":[{{"x":500,"y":300,"label":"Componente"}}],'
            f'"seta":{{"x":500,"y":300,"direcao":"baixo"}},'
            f'"retangulo":{{"x1":350,"y1":200,"x2":650,"y2":450,"label":"Slot"}}}}],'
            f'"verificacao_final":["Verificar encaixe","Fechar a tampa","Ligar o equipamento"]}}'
        )
        resultado = gemini_json(prompt, b)
        if "passos" not in resultado or not resultado["passos"]:
            raise ValueError("JSON sem passos")
        for p in resultado["passos"]:
            f = p.get("ferramenta")
            if isinstance(f, str):
                p["ferramenta"] = {"nome": f, "emoji": "🔧"}
        return {"sucesso": True, "guia": resultado}
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}


# ── /info ─────────────────────────────────────────────────────────────────────
# ── /info ─────────────────────────────────────────────────────────────────────
@app.post("/info")
async def info(
    componente: str        = Form(""),
    imagem:     UploadFile = File(None),
    x:          str        = Form(""),   # centro normalizado 0-1 (opcional)
    y:          str        = Form(""),
    w:          str        = Form(""),   # largura/altura normalizadas 0-1
    h:          str        = Form(""),
):
    try:
        if not componente:
            return {"sucesso": False, "erro": "Componente vazio"}
        b = await imagem.read() if imagem else None
        # Se vierem coordenadas, recorta SÓ aquela peça antes de enviar ao
        # Gemini. Sem isso, com 2 peças iguais na foto o Gemini lê a etiqueta
        # errada e troca os dados entre as peças.
        if b is not None:
            try:
                if x != "" and y != "" and w != "" and h != "":
                    arr = np.frombuffer(b, np.uint8)
                    img_cv = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    if img_cv is not None:
                        H, W = img_cv.shape[:2]
                        cx, cy = float(x) * W, float(y) * H
                        bw, bh = float(w) * W, float(h) * H
                        x1 = int(cx - bw / 2); y1 = int(cy - bh / 2)
                        x2 = int(cx + bw / 2); y2 = int(cy + bh / 2)
                        b = recortar_box(img_cv, x1, y1, x2, y2)
            except Exception as e:
                print(f"⚠️ /info: falha ao recortar, usando imagem cheia: {e}")
        # Normaliza nomes ambíguos do YOLO antes de enviar ao Gemini
        _norm = {
            "SSD/HD": "SSD", "ssd/hd": "SSD", "Ssd/Hd": "SSD",
            "HD/SSD": "SSD", "hd/ssd": "SSD",
        }
        componente = _norm.get(componente, componente)
        prompt = f"""Você é um especialista sênior em hardware de computadores.
Analise a imagem e gere uma ficha técnica para o componente: {componente}
Responda SOMENTE com JSON válido, sem markdown, sem texto antes ou depois.

REGRA CRÍTICA DE HONESTIDADE - LEIA COM ATENÇÃO:
Você está analisando um recorte da imagem que foi classificado como "{componente}".
- Só preencha marca/modelo/capacidade/interface se conseguir LER literalmente esses dados
  em uma etiqueta, chip serigrafado ou impressão que esteja NO PRÓPRIO "{componente}" visível
  no recorte.
- Se a imagem mostrar uma etiqueta de OUTRO componente (ex: etiqueta de SSD colada perto de
  um cabo flat, ou texto de outra peça ao fundo), IGNORE esses dados. Eles NÃO pertencem ao
  "{componente}" e usá-los seria uma informação falsa.
- ATENÇÃO ESPECIAL: o recorte pode conter, nas BORDAS, parte de OUTRA peça do MESMO tipo
  (ex: duas memórias RAM empilhadas). Descreva SOMENTE a peça CENTRAL do recorte. NUNCA
  combine dados de duas peças — "hynix / ProMOS" como marca ou "512MB / 1GB" como capacidade
  está ERRADO. Escolha a peça central e ignore a da borda.
- Se você não conseguir ler nenhuma etiqueta legível pertencente ao próprio "{componente}",
  retorne null nesses campos. Um card com campos null é MELHOR e mais útil do que um card
  com dados inventados ou copiados de outra peça.
- Nunca "complete" um número de modelo parcialmente visível. Ou você lê o número inteiro, ou
  retorna null.
- É preferível errar por falta de informação do que por excesso de invenção.

Estrutura obrigatória:
{{
  "nome_completo": "nome completo lido da etiqueta, ou nome genérico do tipo de componente se não houver etiqueta legível",
  "confianca": 90,
  "funcao": "frase curtíssima sobre o que o componente faz",
  "identificacao": {{
    "marca": "fabricante exato da etiqueta ou null",
    "modelo": "número de modelo exato da etiqueta ou null",
    "capacidade": "ex: 240GB, 4GB ou null",
    "interface": "ex: SATA III, PCIe ou null",
    "tipo_exato": "tipo específico: SSD SATA 2.5pol ou DDR3 SO-DIMM etc"
  }},
  "tags": {{
    "formato": "ex: Memória Notebook | GPU Desktop | SSD M.2 | Processador Socket",
    "classificacao": "Atual ou Transitória ou Depreciada",
    "ciclo_de_vida": "Ciclo de vida: Ativo ou Lançado há X anos ou Fora de linha desde XXXX",
    "integracao": "Em Slot ou Removível ou Soldada ou Dedicado ou Integrado ou Onboard",
    "desempenho": "Entrada ou Intermediário ou High-End"
  }},
  "atributos": [{{"label": "string", "valor": "string"}}],
  "preco_fora_de_linha": false,
  "upgrade": {{"vale": true, "icone": "subir", "conselho": "conselho curto"}},
  "alertas": ["alerta 1", "alerta 2"],
  "problema_comum": {{"falha": "nome da falha", "solucao": "solução rápida"}}
}}

REGRAS:
0. funcao: frase curtíssima (max 10 palavras) explicando o que o componente faz. Ex: "Armazena dados do sistema e programas.", "Processa instruções do sistema operacional."
1. identificacao.marca: preencher SOMENTE se lida na etiqueta física do próprio "{componente}", senão null
2. identificacao.modelo: número exato da etiqueta do próprio "{componente}", nunca inventar nem
   copiar de outra peça da imagem, senão null
3. identificacao.tipo_exato: sempre específico (SSD SATA 2.5pol, DDR3 SO-DIMM, Bateria Li-ion)
4. tags.formato: rótulo curto de forma física + contexto. Ex: "Memória Notebook", "GPU Desktop", "SSD M.2", "Processador Socket"
5. tags.integracao por tipo:
   - RAM SODIMM/DIMM em slot → "Em Slot"
   - RAM soldada → "Soldada"
   - GPU dedicada → "Dedicado"
   - GPU integrada → "Integrado"
6. tags.classificacao: DDR5/NVMe Gen4+/RTX40xx=Atual; DDR4/SSD NVMe=Atual; SSD SATA/DDR3/GTX10xx=Transitória; DDR2/IDE/bateria antiga/HDD=Depreciada
   NUNCA usar Legado, Legada, Clássico, Clássica ou Intermediária/Intermediaria — use sempre Transitória para a geração intermediária
7. atributos: NÃO repetir o que já está em identificacao nem em tags
   RAM: Frequência, Tensão, Pinos
   SSD: Leitura Seq., Escrita Seq.
   HDD: RPM, Cache
   CPU: Freq. Base, Núcleos/Threads, TDP
   GPU: VRAM, TDP, Núcleos shader
8. upgrade.icone: subir (vale=true) ou bloquear (vale=false)
9. Alertas: máximo 2, diferentes de problema_comum
10. nome_completo: nome curto para cabeçalho (Bateria, SSD, GPU — não Bateria de Notebook)"""
        resultado = gemini_json(prompt, b)
        print(f"✅ /info OK para {componente}: campos={list(resultado.keys())}")
        # Garante que os campos existam mesmo que o Gemini esqueça
        if "funcao" not in resultado:
            resultado["funcao"] = ""
        if "identificacao" not in resultado:
            resultado["identificacao"] = {
                "marca": None, "modelo": None,
                "capacidade": None, "interface": None, "tipo_exato": componente
            }
        if "tags" not in resultado:
            resultado["tags"] = {
                "formato": componente,
                "classificacao": "Transitória",
                "ciclo_de_vida": "Ciclo de vida: Ativo",
                "integracao": "Removível",
                "desempenho": "Entrada"
            }
        if "atributos" not in resultado:
            resultado["atributos"] = []
        return {"sucesso": True, "info": resultado}
    except Exception as e:
        print(f"❌ /info ERRO para {componente}: {e}")
        return {"sucesso": False, "erro": str(e)}
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)