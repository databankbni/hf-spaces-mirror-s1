"""
NOMI – crowd-source pronunciations
----------------------------------
• User picks language  -> we load all names for that language
• User selects name    -> records WAV via mic
• We push the clip (+ small JSON meta) into *nomi-names* dataset repo
"""

import os, uuid, datetime, json, tempfile
from pathlib import Path
import gradio as gr
from typing import List, Dict, Optional

import pandas as pd
from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download
from huggingface_hub.errors import HfHubHTTPError

print("Gradio version:", gr.__version__)

HF_TOKEN      = os.environ.get("HF_TOKEN")          # set in Space secrets
DATASET_REPO  = "nomi-stories/nomi-names"
INBOX_REPO    = "nomi-stories/nomi-pronunciation-inbox"
AUDIO_COL     = "Audio Pronunciation"               # column to update
LANGUAGES     = ["Yoruba", "Igbo", "Hausa", "Ibibio", "other"]  # adjust as needed

api = HfApi(token=HF_TOKEN)

# ───────────────────────────────────────────────────────────────────────
# 1 ▸ Load name list from parquet (avoids torchcodec / FFmpeg on HF Spaces)
def _has_audio(audio) -> bool:
    if audio is None or (not isinstance(audio, dict) and pd.isna(audio)):
        return False
    if isinstance(audio, dict):
        return bool(audio.get("bytes"))
    return bool(audio)


parquet_path = hf_hub_download(
    repo_id=DATASET_REPO,
    repo_type="dataset",
    filename="data/train-00000-of-00001.parquet",
    token=HF_TOKEN,
)
df = pd.read_parquet(parquet_path, columns=["Language", "Name", "NameStrip", "Meaning", "Audio Pronunciation"])

lang2names: Dict[str, List[str]] = {}
namestrip_by_display: Dict[tuple, str] = {}
meaning_by_display: Dict[tuple, str] = {}
seen_display_by_lang: Dict[str, set] = {}
for _, row in df.iterrows():
    lang = row["Language"]
    name = row["Name"]
    if not name or pd.isna(name):
        continue
    # Only show names for which there's no pronunciation yet
    if _has_audio(row.get("Audio Pronunciation")):
        continue
    if name in seen_display_by_lang.setdefault(lang, set()):
        continue
    seen_display_by_lang[lang].add(name)
    lang2names.setdefault(lang, []).append(name)
    namestrip_by_display[(lang, name)] = str(row.get("NameStrip", "")).strip()
    meaning = row.get("Meaning")
    meaning_by_display[(lang, name)] = "" if meaning is None or pd.isna(meaning) else str(meaning).strip()

LANGUAGES = sorted(lang2names.keys())

# ─── Parse reviewed pairs ────────────────────────────────────────
reviewed = set()
try:
    inbox = api.list_repo_files(repo_id=INBOX_REPO, repo_type="dataset")
    for file in inbox:
        if file.startswith("meta/") and file.endswith(".json"):
            path = hf_hub_download(repo_id=INBOX_REPO, repo_type="dataset", filename=file, token=HF_TOKEN)
            with open(path, "r") as f:
                data = json.load(f)
                lang = data.get("language")
                name = data.get("name")
                if lang and name:
                    reviewed.add((lang, name))
except Exception as e:
    print("⚠️ Could not load reviewed suggestions:", e)
# ───────────────────────────────────────────────────────────────────────

with open(Path(__file__).with_name("batches.json"), "r") as bf:
    BATCHES: Dict[str, dict] = json.load(bf)


def _filter_names(lang: str, batch_id: Optional[str] = None) -> List[str]:
    if batch_id and batch_id in BATCHES:
        batch = BATCHES[batch_id]
        if lang != batch["language"]:
            return []
        allowed = set(batch["names"])
        source = [
            n for n in lang2names.get(lang, [])
            if n in allowed or namestrip_by_display.get((lang, n), "") in allowed
        ]
    else:
        source = lang2names.get(lang, [])
    unreviewed = (n for n in source if (lang, n) not in reviewed)
    return sorted(dict.fromkeys(unreviewed))


def _meaning_for(lang: str, name: Optional[str]) -> str:
    if not lang or not name:
        return ""
    return meaning_by_display.get((lang, name), "").strip()


def _batch_banner_html(batch_id: str, lang: str) -> tuple[str, bool]:
    if not batch_id or batch_id not in BATCHES:
        return "", False
    batch = BATCHES[batch_id]
    if lang != batch["language"]:
        return "", False
    filtered = _filter_names(lang, batch_id)
    total = len(batch["names"])
    remaining = len(filtered)
    banner = (
        f"<div style='background:#ecfdf5;border:1px solid #6ee7b7;border-radius:12px;"
        f"padding:16px;margin-bottom:16px;'>"
        f"<strong>{batch['label']}</strong> — "
        f"{remaining} of {total} name{'s' if total != 1 else ''} still to record "
        f"(already-submitted names are hidden).</div>"
    )
    return banner, True


def names_for_language(lang, batch_id=None):
    filtered = _filter_names(lang, batch_id)
    first = filtered[0] if filtered else None
    return (
        gr.update(choices=filtered, value=first),
        gr.update(value=_meaning_for(lang, first)),
    )


def show_meaning_for_name(lang, name):
    return gr.update(value=_meaning_for(lang, name))


def init_from_url(request: gr.Request):
    batch_id = ""
    if request:
        batch_id = dict(request.query_params).get("batch", "").strip()

    if batch_id not in BATCHES:
        return (
            "",
            gr.update(),
            gr.update(),
            gr.update(visible=False),
            gr.update(value=""),
            gr.update(value=""),
        )

    batch = BATCHES[batch_id]
    lang = batch["language"]
    filtered = _filter_names(lang, batch_id)
    first = filtered[0] if filtered else None
    banner, _ = _batch_banner_html(batch_id, lang)
    contributor = batch.get("contributor", "").strip()
    return (
        batch_id,
        gr.update(value=lang, interactive=False),
        gr.update(choices=filtered, value=first),
        gr.update(value=banner, visible=True),
        gr.update(value=_meaning_for(lang, first)),
        gr.update(value=contributor),
    )

###############################################################################
# UPLOAD HANDLER — stores WAV + meta JSON in the INBOX_REPO
###############################################################################

def _upload_no_change(msg: str):
    return gr.update(value=msg), gr.update(), gr.update(), gr.update(), gr.update()


def _format_upload_error(exc: Exception) -> str:
    status = getattr(getattr(exc, "response", None), "status_code", None)
    msg = str(exc)
    if status == 429 or "429" in msg or "Too Many Requests" in msg:
        return (
            "⏳ We're getting a lot of uploads right now and hit Hugging Face's rate limit "
            "(128 commits per hour). Please wait a few minutes and try again — "
            "your recording is still here."
        )
    if isinstance(exc, HfHubHTTPError) and status:
        return f"❌ Upload failed (HTTP {status}): {msg}"
    return f"❌ Upload failed: {msg}"


def upload_pronunciation(lang, name_sel, reviewer, audio, batch_id=""):
    batch_id = (batch_id or "").strip()

    if audio is None:
        return _upload_no_change("Please record audio first 🙂")
    if not name_sel:
        return _upload_no_change("Please select a name.")

    name_final = (name_sel or "").strip()
    if not name_final:
        return _upload_no_change("Please select a name.")

    name_strip = namestrip_by_display.get((lang, name_final), "").strip() or name_final

    sr, wav = audio
    uid = uuid.uuid4().hex[:8]
    import soundfile as sf
    fname = f"{lang}_{name_final}_{uid}.wav"
    tmp_wav = tempfile.mktemp(".wav")
    tmp_json = tempfile.mktemp(".json")
    try:
        sf.write(tmp_wav, wav, sr)

        meta_json = {
            "name": name_final,
            "name_strip": name_strip,
            "language": lang,
            "reviewer": (reviewer or "").strip(),
            "audio_path": f"audio/{fname}",
            "uploaded": datetime.datetime.utcnow().isoformat() + "Z",
        }
        with open(tmp_json, "w") as jf:
            json.dump(meta_json, jf)

        api.create_commit(
            repo_id=INBOX_REPO,
            repo_type="dataset",
            operations=[
                CommitOperationAdd(path_in_repo=f"audio/{fname}", path_or_fileobj=tmp_wav),
                CommitOperationAdd(path_in_repo=f"meta/{fname[:-4]}.json", path_or_fileobj=tmp_json),
            ],
            commit_message=f"Suggestion for {name_final}",
        )
    except Exception as e:
        return _upload_no_change(_format_upload_error(e))
    finally:
        for path in (tmp_wav, tmp_json):
            if os.path.exists(path):
                os.remove(path)

    reviewed.add((lang, name_final))
    filtered = _filter_names(lang, batch_id or None)
    first = filtered[0] if filtered else None

    batch_banner_update = gr.update()
    if batch_id:
        banner_html, visible = _batch_banner_html(batch_id, lang)
        if visible:
            batch_banner_update = gr.update(value=banner_html, visible=True)

    return (
        gr.update(value=f"<div style='color: green; font-size: 22px; font-weight: bold;'>✅ Uploaded pronunciation for {name_final}!</div>"),
        gr.update(value=None),
        gr.update(choices=filtered, value=first),
        gr.update(value=_meaning_for(lang, first)),
        batch_banner_update,
    )

# ─────Gradio UI ─────────────────────────────────────────────────────────────────
with gr.Blocks(theme=gr.themes.Base(primary_hue=gr.themes.colors.green, font=[gr.themes.GoogleFont('Nunito Sans'), 'ui-sans-serif', 'system-ui', 'sans-serif']), title="NOMI – contribute pronunciation") as demo:
        # ── Header & Mission ──────────────────────────────
    gr.HTML("""
    <div style="text-align: center; margin-bottom: 20px;">
        <h1>🎤 NOMI Pronunciation Uploader</h1>
        <p style="font-size:16px; max-width:700px; margin: 0 auto;">
            Contribute African name pronunciations to Nomi, our initiative to
            <strong>build the AI infrastructure layer for African name data</strong>.
            High-quality recordings ensure that our names and languages live on digitally,
            powering apps, research, and storytelling globally.
        </p>
        <p><a href="https://nomistories.com/" target="_blank">🖥️ Nomi Website</a> | 
        <a href="https://huggingface.co/spaces/nomi-stories/nomi-name-search" target="_blank">🔍 Find similar names</a> | 
    </div>
    """)

    # ── Instructions Panel ─────────────────────────────
    gr.HTML("""
    <div style="background-color: #f0fdf4; border: 1px solid #86efac; border-radius: 12px; padding: 20px; margin-bottom: 20px;">
        <h3>📝 Submission Tips</h3>
        <ol style="font-size: 15px; line-height: 1.6;">
            <li><strong>Select a Language</strong> – Choose the language you speak natively or fluently.</li>
            <li><strong>Select a Name</strong> – Pick a name from the dropdown list that needs a recording.</li>
            <li><strong>Record in a Quiet Environment</strong> – Minimize background noise for clarity.</li>
            <li><strong>Pronounce Slowly and Clearly</strong> – Speak at a moderate pace, emphasizing each vowel and consonant sound clearly so the pronunciation is easy to understand.</li>
            <li><strong>Submit for Review</strong> – Our linguists and translators will verify each submission.</li>
        </ol>
        <p style="font-size:14px; margin-top: 10px;">
            By contributing, you are helping us enrich our dataset of over <strong>9,000 names</strong> names that preserves African linguistic heritage digitally.
        </p>
    </div>
    """)
    
    # ── Sample Audio Section ─────────────────────────────
    # Load Lantana sample audio from dataset using parquet to avoid audio decoding issues
    sample_audio_path = None
    try:
        sample_df = pd.read_parquet(parquet_path)
        
        # Find Lantana with Hausa language
        lantana_row = sample_df[(sample_df["NameStrip"] == "Lantana") & (sample_df["Language"].str.contains("Hausa", na=False))]
        
        if len(lantana_row) > 0:
            audio_data = lantana_row.iloc[0]["Audio Pronunciation"]
            if audio_data and isinstance(audio_data, dict) and "bytes" in audio_data:
                # Save audio bytes to a file - use absolute path for reliability
                audio_bytes = audio_data["bytes"]
                sample_audio_path = os.path.abspath("lantana_sample.wav")
                with open(sample_audio_path, "wb") as f:
                    f.write(audio_bytes)
                
                # Verify file was created
                if not os.path.exists(sample_audio_path):
                    sample_audio_path = None
    except Exception:
        sample_audio_path = None
    
    # Sample Audio Section with Audio component in the same visual container
    gr.HTML("""
    <style>
        .sample-audio-container {
            background-color: #eff6ff;
            border: 1px solid #93c5fd;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
    </style>
    """)
    
    with gr.Column(elem_classes=["sample-audio-container"]):
        gr.HTML("""
        <h3 style="margin-top: 0;">🎧 Listen to a Sample Recording</h3>
        <p style="font-size: 15px; line-height: 1.6; margin-bottom: 15px;">
            Listen to this example pronunciation of <strong>Lantana</strong> (Hausa) to understand the quality and clarity we're looking for. 
            Notice how the speaker pronounces each sound slowly and clearly, making it easy to understand the pronunciation.
        </p>
        <p style="font-size: 14px; color: #6b7280; margin-bottom: 15px;">
            <em>Recording by: Sa'ad Nasir Bashir</em>
        </p>
        """)
        
        # Audio component appears right below in the same container
        if sample_audio_path and os.path.exists(sample_audio_path):
            sample_audio = gr.Audio(
                value=sample_audio_path,
                label="Sample: Lantana (Hausa) pronunciation",
                interactive=False,
                show_download_button=True
            )
        else:
            sample_audio = gr.Audio(
                label="Sample: Lantana (Hausa) pronunciation",
                interactive=False,
                show_download_button=True
            )
    with gr.Row():
        reviewer_tb = gr.Textbox(label="Your Name or Email as a Contributor")
    
    batch_banner = gr.HTML(visible=False)
    batch_state = gr.State("")

    with gr.Row():
        lang_dd   = gr.Dropdown(LANGUAGES, value=None, label="Select a Language")
        name_box = gr.Dropdown([], label="Choose a Name")

    meaning_box = gr.Textbox(label="Meaning", interactive=False, lines=2)

    mic       = gr.Audio(sources=["microphone", "upload"], type="numpy", label="Record pronunciation of the name")
    btn       = gr.Button("🎤 Submit Pronunciation", variant="primary")
    status    = gr.Markdown()

    # behaviour

    demo.load(
        init_from_url,
        outputs=[batch_state, lang_dd, name_box, batch_banner, meaning_box, reviewer_tb],
    )
    lang_dd.change(names_for_language, [lang_dd, batch_state], [name_box, meaning_box])
    name_box.change(show_meaning_for_name, [lang_dd, name_box], meaning_box)
    btn.click(
        upload_pronunciation,
        [lang_dd, name_box, reviewer_tb, mic, batch_state],
        outputs=[status, mic, name_box, meaning_box, batch_banner],
    )

if __name__ == "__main__":
    demo.launch(share=True)