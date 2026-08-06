"""Rocky Voice TTS Space (Gradio + Piper). Serves tts_b64 via the Gradio API."""
import base64
import gradio as gr
import piper_synth

TOOL_DESCRIPTION = (
    "Convert text to speech in the Rocky (Piper en_US-lessac-low) voice. "
    "Returns sample_rate and a base64-encoded 16 kHz mono WAV."
)

def tts_bytes(text: str) -> bytes:
    return piper_synth.synth(text)

def tts_b64(text: str) -> dict:
    """Gradio/MCP-friendly: base64 WAV + sample rate."""
    data = tts_bytes(text)
    return {
        "sample_rate": piper_synth.get_sample_rate(),
        "audio_b64": base64.b64encode(data).decode("ascii"),
    }

def _preview(text):
    import io
    import soundfile as sf
    data = tts_bytes(text)
    arr, sr = sf.read(io.BytesIO(data), dtype="int16")
    return (sr, arr)

with gr.Blocks(title="Rocky Voice TTS") as demo:
    txt = gr.Textbox(label="Text", placeholder="Hello, I am Rocky.")
    btn = gr.Button("Speak", variant="primary")
    out = gr.Audio(label="Speech", type="numpy")
    btn.click(_preview, inputs=txt, outputs=out, api_name=False, queue=False)
    gr.api(tts_b64, api_name="tts_b64", api_description=TOOL_DESCRIPTION, queue=False, concurrency_limit=None)

if __name__ == "__main__":
    demo.launch(mcp_server=True)
