import sys
import os
import types
import logging
import subprocess
from pathlib import Path

import torch
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# ── 0. تحديث kagglehub (مهم جداً!) ────────────────────────
try:
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "-q", "--upgrade", "kagglehub>=1.0.2"
    ])
    logger.info("✅ kagglehub upgraded")
except Exception as e:
    logger.warning(f"⚠️ upgrade failed: {e}")

import kagglehub

# ── 1. Kaggle Credentials ─────────────────────────────────
kaggle_username = os.environ.get("KAGGLE_USERNAME")
kaggle_key = os.environ.get("KAGGLE_KEY")

if kaggle_username and kaggle_key:
    os.environ["KAGGLE_USERNAME"] = kaggle_username
    os.environ["KAGGLE_KEY"] = kaggle_key
    kaggle_dir = Path.home() / ".kaggle"
    kaggle_dir.mkdir(parents=True, exist_ok=True)
    kaggle_json = kaggle_dir / "kaggle.json"
    kaggle_json.write_text(f'{{"username":"{kaggle_username}","key":"{kaggle_key}"}}')
    os.chmod(kaggle_json, 0o600)
    logger.info("✅ Kaggle credentials configured")
else:
    logger.warning("⚠️ KAGGLE_USERNAME/KAGGLE_KEY not set")

# ── 2. تحميل النموذج (النسخة 3 + force_download) ───────────
model_path = None

try:
    logger.info("⬇️ [Attempt 1] transformers/default/19 + force_download")
    model_path = kagglehub.model_download(
        "ruicompany/onyx-code-figma/transformers/default/19",
        force_download=True
    )
    logger.info(f"✅ Success: {model_path}")
except Exception as e:
    logger.error(f"❌ Attempt 1 failed: {e}")

# محاولة 2: keras/default/3 (احتياطي)
if not model_path:
    try:
        logger.info("⬇️ [Attempt 2] keras/default/19")
        model_path = kagglehub.model_download(
            "ruicompany/onyx-code-figma/keras/default/19",
            force_download=True
        )
        logger.info(f"✅ Success: {model_path}")
    except Exception as e:
        logger.error(f"❌ Attempt 2 failed: {e}")

# محاولة 3: dataset_download (أكثر استقراراً)
if not model_path:
    try:
        logger.info("⬇️ [Attempt 3] dataset_download")
        model_path = kagglehub.dataset_download("ruicompany/onyx-code-figma")
        logger.info(f"✅ Success: {model_path}")
    except Exception as e:
        logger.error(f"❌ Attempt 3 failed: {e}")

# محاولة 4: مسار محلي
if not model_path:
    local_paths = [
        "/app/model",
        "./model",
        "/kaggle/working/onyx-code-figma-bundle",
        "./onyx-code-figma-bundle",
    ]
    for p in local_paths:
        if os.path.exists(p) and any(Path(p).rglob("*.safetensors")):
            model_path = p
            logger.info(f"✅ [Fallback] Local path: {p}")
            break

if not model_path:
    logger.error("🚨 All download attempts failed!")
    model_path = None

# ── 3. فحص الملفات ────────────────────────────────────────
if model_path:
    logger.info("📁 Files in model path:")
    for f in sorted(Path(model_path).rglob("*"))[:30]:
        logger.info(f"   {f.relative_to(model_path)}")

# ── 4. البحث عن onyx_code.py ──────────────────────────────
onyx_code_dir = None
if model_path:
    for py_file in Path(model_path).rglob("onyx_code.py"):
        onyx_code_dir = py_file.parent
        logger.info(f"🔍 Found onyx_code.py: {py_file}")
        break

# ── 5. Monkey-patch IPython ────────────────────────────────
captured_html = []

class MockHTML:
    def __init__(self, data=None, **kwargs):
        self.data = data or ""

def mock_display(*objs, **kwargs):
    for obj in objs:
        if hasattr(obj, 'data') and isinstance(obj.data, str):
            captured_html.append(obj.data)
        elif isinstance(obj, str):
            captured_html.append(obj)

ipython_pkg = types.ModuleType("IPython")
ipython_display = types.ModuleType("IPython.display")
ipython_display.HTML = MockHTML
ipython_display.display = mock_display
ipython_display.display_html = mock_display
ipython_display.clear_output = lambda *a, **k: None
ipython_display.Javascript = lambda *a, **k: MockHTML()

ipython_pkg.display = ipython_display
sys.modules["IPython"] = ipython_pkg
sys.modules["IPython.display"] = ipython_display

# ── 6. استيراد onyx_code ──────────────────────────────────
html_content = "<h2>⚠️ Onyx Designer not loaded</h2>"

if onyx_code_dir:
    sys.path.insert(0, str(onyx_code_dir))
    try:
        import onyx_code
        logger.info("✅ onyx_code imported")
        if hasattr(onyx_code, 'launch_designer'):
            onyx_code.launch_designer()
            html_content = captured_html[-1] if captured_html else html_content
            logger.info(f"📄 HTML: {len(html_content)} chars")
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        logger.error(traceback.format_exc())

# ── 7. تحميل Transformers Model ───────────────────────────
model = None
tokenizer = None

if model_path and any(Path(model_path).rglob("*.safetensors")):
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        
        quantization_config = BitsAndBytesConfig(
            load_in_8bit=True,
            llm_int8_enable_fp32_cpu_offload=True,
        )
        
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            quantization_config=quantization_config,
            device_map="auto",
            max_memory={0: "0GB", "cpu": "6GB"},
            offload_buffers=True,
            offload_folder="offload",
            offload_state_dict=True,
            torch_dtype=torch.float32,
            trust_remote_code=True,
        )
        tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        logger.info("✅ Model loaded")
    except Exception as e:
        logger.error(f"❌ Model load failed: {e}")

# ── 8. FastAPI ────────────────────────────────────────────
app = FastAPI(title="Onyx Code Figma API")

@app.get("/", response_class=HTMLResponse)
def read_root():
    return html_content

@app.get("/health")
def health_check():
    return {
        "model_loaded": model is not None,
        "model_path": model_path,
        "html_length": len(html_content),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)