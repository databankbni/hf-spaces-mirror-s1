import gradio as gr
import subprocess
import os
import shutil
from huggingface_hub import HfApi

# 1. Startup Diagnostics - Installs locally to workspace directory to prevent permissions errors
print("🔧 Initializing Movees Downloader Node Workspace...")
subprocess.run("npm install @warren-bank/node-hls-downloader-tubitv", shell=True)

# Point directly to the local node execution link binary
LOCAL_BIN_PATH = os.path.abspath("node_modules/.bin")
os.environ["PATH"] = f"{LOCAL_BIN_PATH}:{os.environ.get('PATH', '')}"

HF_TOKEN = os.environ.get("HF_TOKEN")
VAULT_REPO = "israelmrakpor/Movees-Vault" 

def download_tubi(url, proxy_url):
    url = url.strip()
    out_dir = "temp_downloads"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    
    # Check if local installation was successful
    tubidl_executable = shutil.which("tubidl")
    if not tubidl_executable:
        return "❌ Installation Error: 'tubidl' component could not be found or mapped into workspace execution paths."
    
    # Clean the proxy format automatically to prevent parsing failures inside the node tool
    clean_proxy = proxy_url.strip()
    if clean_proxy:
        clean_proxy = clean_proxy.replace("http://", "").replace("https://", "")
    
    # Build command defensively safely passing parameters without breaking quote enclosures
    if clean_proxy:
        cmd = ["tubidl", "-P", out_dir, "-mf", "1", "-ll", "3", "--proxy", clean_proxy, "-u", url]
    else:
        cmd = ["tubidl", "-P", out_dir, "-mf", "1", "-ll", "3", "-u", url]
    
    print(f"📡 Downloading Video & Subtitles: {url}")
    if clean_proxy:
        print(f"📡 Routing stream traffic through sanitized proxy endpoint target: {clean_proxy}")
        
    # Execute safely via an un-shelled list to catch internal crashes precisely
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Direct terminal dump to Hugging Face engine logs for quick validation
    print(f"⚙️ Downloader Process Completed with Exit Status: {result.returncode}")
    if result.stdout:
        print(f"ℹ️ Core Downloader Standard Output:\n{result.stdout}")
    if result.returncode != 0 or result.stderr:
        print(f"🔥 Core Downloader Engine Error Log:\n{result.stderr}")
    
    # --- DEFENSIVE DRM PROTECTION EXCEPTION DETECTING ---
    combined_logs = (result.stdout or "") + "\n" + (result.stderr or "")
    if "missing data fields in video object metadata" in combined_logs or "Assertion Error" in combined_logs:
        # Clean the directory immediately to keep HF Space storage light
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        return (
            "❌ DRM PROTECTION ERROR\n\n"
            "This title is protected by Widevine DRM encryption.\n"
            "Tubi does not expose the raw manifest data fields for copy-protected studio movies.\n"
            "Please try downloading indie titles, classics, or less-restrictive content."
        )

    # --- SEARCH FOR MULTIPLE VIDEO AND SUBTITLE FORMATS ---
    downloaded_video = None
    downloaded_subs = []
    
    # Supported media extension arrays used by the streaming downloader tool
    video_extensions = (".mp4", ".mkv", ".ts")
    
    for root, dirs, files in os.walk(out_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if file.lower().endswith(video_extensions):
                downloaded_video = file_path
            elif file.lower().endswith((".srt", ".vtt")):
                downloaded_subs.append(file_path)

    if not downloaded_video:
        dir_content = os.listdir(out_dir) if os.path.exists(out_dir) else "Directory Missing"
        print(f"🔍 Diagnostic Dump: Check current download folder file structure -> {dir_content}")
        # Wipe temp directory to clear failures
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        return f"❌ Video file not found or extraction aborted. Check Hugging Face log dashboard console for full raw node logs."

    # 2. Upload to Vault
    try:
        api = HfApi(token=HF_TOKEN)
        movie_name = os.path.basename(downloaded_video)
        
        # Upload Movie
        print(f"☁️ Vaulting Movie: {movie_name}")
        api.upload_file(
            path_or_fileobj=downloaded_video,
            path_in_repo=f"movies/{movie_name}",
            repo_id=VAULT_REPO,
            repo_type="dataset"
        )
        
        # Upload Subtitles
        sub_status = "No subtitles found."
        if downloaded_subs:
            for sub in downloaded_subs:
                sub_name = os.path.basename(sub)
                print(f"☁️ Vaulting Subtitle: {sub_name}")
                api.upload_file(
                    path_or_fileobj=sub,
                    path_in_repo=f"subtitles/{sub_name}",
                    repo_id=VAULT_REPO,
                    repo_type="dataset"
                )
            sub_status = f"Found and uploaded {len(downloaded_subs)} subtitle(s)."
            
        shutil.rmtree(out_dir)
        return f"🎉 SUCCESS!\n📽️ Movie: {movie_name}\n📜 Subs: {sub_status}"
    
    except Exception as e:
        if os.path.exists(out_dir):
            shutil.rmtree(out_dir)
        return f"❌ VAULT ERROR: {str(e)}"

# UI Design
with gr.Blocks() as demo:
    gr.Markdown("# 🎥 Movees Tubi-Vault Downloader (Video + Subs)")
    with gr.Row():
        link_input = gr.Textbox(label="Tubi URL")
        proxy_input = gr.Textbox(label="Proxy", value="http://45.132.227.200:8080")
    
    btn = gr.Button("🚀 Download Everything", variant="primary")
    status = gr.Textbox(label="Status", interactive=False)
    
    btn.click(download_tubi, inputs=[link_input, proxy_input], outputs=status)

demo.launch(ssr_mode=False)