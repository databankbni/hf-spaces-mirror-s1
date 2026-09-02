import importlib
import os
import sys

from huggingface_hub import snapshot_download

TOKEN = os.environ["HF_TOKEN"]
PRIVATE_REPO = os.environ.get("PRIVATE_REPO", "PraddyK/cria-private-code")
REPO_TYPE = os.environ.get("PRIVATE_REPO_TYPE", "model")
PORT = int(os.environ.get("PORT", "7860"))

print(f"[loader] fetching private code from {REPO_TYPE}:{PRIVATE_REPO} ...", flush=True)
code_dir = snapshot_download(
    repo_id=PRIVATE_REPO,
    repo_type=REPO_TYPE,
    token=TOKEN,
    local_dir="/home/user/app_code",
)
print(f"[loader] code ready at {code_dir}", flush=True)

# All dependencies are already installed system-wide at build time, so we
# just import the app and launch it on the port Hugging Face expects.
os.chdir(code_dir)
sys.path.insert(0, code_dir)
print("[loader] importing app and launching on 0.0.0.0:%d ..." % PORT, flush=True)
appmod = importlib.import_module("app")
appmod.app.run(host="0.0.0.0", port=PORT)
