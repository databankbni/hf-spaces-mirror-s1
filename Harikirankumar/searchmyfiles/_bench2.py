import os, io, json, time, statistics
import requests
from PIL import Image
import app as a

base = os.path.abspath('portable_tesseract/Tesseract-OCR')
os.environ['TESSERACT_CMD'] = os.path.join(base, 'tesseract.exe')
os.environ['TESSDATA_PREFIX'] = os.path.join(base, 'tessdata')
a._configure_tesseract()

session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 OCRBenchmark/1.0'})

with open('_ocr_web_english_sources.json', encoding='utf-8') as f:
    sources = json.load(f)

def punct_ratio(text):
    t = text or ''
    total = max(1, len(t))
    punct = sum((not ch.isalnum()) and (not ch.isspace()) for ch in t)
    return punct / total

def avg(arr, key):
    return statistics.mean([x[key] for x in arr]) if arr else 0.0

baseline, improved = [], []

for item in sources:
    try:
        r = session.get(item['download_url'], timeout=45)
        if r.status_code != 200: continue
        img = Image.open(io.BytesIO(r.content)).convert('RGB')
        max_dim = 1700
        w, h = img.size
        if max(w, h) > max_dim:
            ratio = max_dim / float(max(w, h))
            img = img.resize((max(1, int(w*ratio)), max(1, int(h*ratio))), Image.Resampling.LANCZOS)

        t0 = time.perf_counter()
        b = a._ocr_best_details(img, lang='eng', psm=3, low_conf_threshold=55, is_region=False, is_image=False)
        tb = time.perf_counter() - t0

        opts = a._resolve_ocr_options(img, lang='auto', psm=3, preset='', low_conf_threshold=55, is_region=False, is_image=True)
        t1 = time.perf_counter()
        n = a._ocr_best_details(img, lang=opts['lang'], psm=int(opts['psm']), low_conf_threshold=int(opts['low_conf_threshold']), is_region=False, is_image=True)
        tn = time.perf_counter() - t1

        bt, nt = str(b.get('text') or ''), str(n.get('text') or '')
        baseline.append({'conf': float(b.get('confidence_score',0)), 'low': int(b.get('low_confidence_count',0)), 'punct': punct_ratio(bt), 'time': tb, 'len': len(bt.strip())})
        improved.append({'conf': float(n.get('confidence_score',0)), 'low': int(n.get('low_confidence_count',0)), 'punct': punct_ratio(nt), 'time': tn, 'len': len(nt.strip())})
    except Exception:
        continue

nn = len(baseline)
print(f'samples={nn}')
print(f'BASE conf={avg(baseline,"conf"):.2f}  punct={avg(baseline,"punct"):.4f}  time={avg(baseline,"time"):.3f}s')
print(f'NEW  conf={avg(improved,"conf"):.2f}  punct={avg(improved,"punct"):.4f}  time={avg(improved,"time"):.3f}s')
print(f'WINS conf={sum(1 for b,n in zip(baseline,improved) if n["conf"]>=b["conf"])}/{nn}  punct={sum(1 for b,n in zip(baseline,improved) if n["punct"]<=b["punct"])}/{nn}  speed={sum(1 for b,n in zip(baseline,improved) if n["time"]<=b["time"])}/{nn}')
