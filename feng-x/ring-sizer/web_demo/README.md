# Web Demo

Local Flask demo for ring-size-cv. Upload an image, run measurement, and return JSON + debug overlay.

## Setup

```bash
cd /Users/fengxie/Build/ring-size-cv
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python web_demo/app.py
```

Open `http://localhost:8000`.

## Notes
- Uploads stored in `web_demo/uploads/`
- Results stored in `web_demo/results/`
- Debug overlay auto-generated per request
- Default guided sample image is at `web_demo/static/examples/default_sample.jpg`
- `Start Measurement` uses the default sample image when no upload is selected
- Web demo enforces SAM-mask boundary edge detection only (`edge_method=mask`)
