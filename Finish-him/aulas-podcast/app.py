"""
Gerador de Aulas em Podcast (PT-BR) — vozes neurais da Microsoft via edge-tts.

Formato do roteiro (duas vozes):
    PROF: texto do professor...
    ALUNA: texto da aluna...

Linhas sem prefixo continuam a fala anterior. Se o roteiro não tiver
nenhum prefixo, tudo é lido pela voz do "Professor" (narração única).

Roda em Hugging Face Spaces (SDK Gradio) ou em qualquer máquina/Colab.
"""

import asyncio
import os
import re
import tempfile

import edge_tts
import gradio as gr
from pydub import AudioSegment

# Vozes PT-BR de alta qualidade (Azure Neural). Adicione outras se quiser.
VOICES = {
    "Antônio (masculina)": "pt-BR-AntonioNeural",
    "Donato (masculina)": "pt-BR-DonatoNeural",
    "Francisca (feminina)": "pt-BR-FranciscaNeural",
    "Thalita (feminina)": "pt-BR-ThalitaNeural",
}

# Aliases de quem fala -> qual voz. PROF e ALUNA são os papéis padrão.
DEFAULT_ROLE = "PROF"

SAMPLE_SCRIPT = """PROF: Olá! Este é um teste do gerador de aulas em podcast.
ALUNA: E eu sou a aluna, que faz as perguntas importantes. Funciona mesmo?
PROF: Funciona! Cole o roteiro do módulo, escolha as vozes e gere o áudio.
"""


def _load_default_script() -> str:
    """Carrega o roteiro do Módulo 1 se existir; senão, um exemplo curto."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "aula_m1_async.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    return SAMPLE_SCRIPT


def parse_script(script: str):
    """Converte o roteiro em [(papel, texto), ...]."""
    lines = []
    for raw in script.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        m = re.match(r"^([A-Za-zÀ-ÿ]+)\s*:\s*(.*)$", raw)
        if m:
            lines.append([m.group(1).upper(), m.group(2).strip()])
        elif lines:  # continuação da fala anterior
            lines[-1][1] += " " + raw
        else:  # texto solto no começo -> vira fala do professor
            lines.append([DEFAULT_ROLE, raw])
    return [(sp, tx) for sp, tx in lines if tx]


async def _synth_all(segments, role_to_voice, rate, pitch, tmpdir):
    paths = []
    for i, (role, text) in enumerate(segments):
        voice = role_to_voice.get(role, role_to_voice[DEFAULT_ROLE])
        out = os.path.join(tmpdir, f"{i:03d}.mp3")
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(out)
        paths.append(out)
    return paths


def generate(script, prof_voice_label, aluna_voice_label, speed, pitch_semitones,
             gap_ms, progress=gr.Progress()):
    segments = parse_script(script)
    if not segments:
        raise gr.Error("Roteiro vazio. Cole algo no formato 'PROF:' / 'ALUNA:'.")

    role_to_voice = {
        "PROF": VOICES[prof_voice_label],
        "ALUNA": VOICES[aluna_voice_label],
    }
    rate = f"{int(speed):+d}%"          # ex: "+0%", "-10%"
    pitch = f"{int(pitch_semitones):+d}Hz"

    tmpdir = tempfile.mkdtemp()
    progress(0.1, desc=f"Sintetizando {len(segments)} falas...")
    paths = asyncio.run(_synth_all(segments, role_to_voice, rate, pitch, tmpdir))

    progress(0.8, desc="Montando o episódio...")
    podcast = AudioSegment.silent(duration=300)
    pause = AudioSegment.silent(duration=int(gap_ms))
    for p in paths:
        podcast += AudioSegment.from_file(p, format="mp3") + pause

    out_path = os.path.join(tmpdir, "aula.mp3")
    podcast.export(out_path, format="mp3", bitrate="128k")
    progress(1.0, desc="Pronto!")
    return out_path, out_path


with gr.Blocks(title="Aulas em Podcast (PT-BR)") as demo:
    gr.Markdown(
        "# 🎙️ Gerador de Aulas em Podcast (PT-BR)\n"
        "Vozes neurais da Microsoft via `edge-tts`. "
        "Escreva o roteiro com **`PROF:`** e **`ALUNA:`** para duas vozes, "
        "ou sem prefixos para narração única."
    )
    with gr.Row():
        with gr.Column(scale=3):
            script = gr.Textbox(
                label="Roteiro", value=_load_default_script(), lines=18,
            )
        with gr.Column(scale=1):
            prof_voice = gr.Dropdown(
                list(VOICES), value="Antônio (masculina)", label="Voz do PROF")
            aluna_voice = gr.Dropdown(
                list(VOICES), value="Francisca (feminina)", label="Voz da ALUNA")
            speed = gr.Slider(-30, 30, value=0, step=5, label="Velocidade (%)")
            pitch = gr.Slider(-20, 20, value=0, step=2, label="Tom (Hz)")
            gap = gr.Slider(100, 900, value=350, step=50,
                            label="Pausa entre falas (ms)")
            btn = gr.Button("Gerar episódio 🎧", variant="primary")
    audio = gr.Audio(label="Prévia", type="filepath")
    file = gr.File(label="Baixar MP3")

    btn.click(generate,
              [script, prof_voice, aluna_voice, speed, pitch, gap],
              [audio, file])

if __name__ == "__main__":
    demo.launch()
