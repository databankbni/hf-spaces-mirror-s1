# Windows setup — first local run

Open **Anaconda Prompt**.

```bat
D:
cd D:\llmwiki-chatGPT
conda activate llmwiki
python --version
```

Python 3.10 or 3.11 is recommended. Extract the downloaded folder so the project path is:

```text
D:\llmwiki-chatGPT\verified-student-pathway-agent
```

Then run:

```bat
cd D:\llmwiki-chatGPT\verified-student-pathway-agent
python -m pip install -r requirements.txt
python tools\preflight.py
python app.py
```

Open the local URL printed by Gradio, normally `http://127.0.0.1:7860`.

No Zhipu API key is required in v0.1. A later optional explanation layer will read `ZHIPU_API_KEY` from an environment variable; the key must never be written into code or uploaded to Hugging Face.
