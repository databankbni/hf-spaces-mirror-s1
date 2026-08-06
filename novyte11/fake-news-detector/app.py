"""
Evidence-Aware Fake News Detector — Hugging Face Space (Gradio).
Premium dark "cyber-SaaS" UI.
Secrets (optional): MODEL_KEY, NEWSAPI_KEY, GOOGLE_FACTCHECK_KEY, HF_TOKEN
"""
import os, json, re, html
import numpy as np
import pandas as pd
import faiss
import torch
import requests
import gradio as gr
from huggingface_hub import hf_hub_download, snapshot_download
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from sentence_transformers import SentenceTransformer

# ===================== config =====================
USER = "novyte11"
CLF_REPO, NLI_REPO, RET_REPO = f"{USER}/fnd-classifier", f"{USER}/fnd-nli", f"{USER}/fnd-retrieval"
HF_TOKEN = os.environ.get("HF_TOKEN")
MODEL_KEY = (os.environ.get("MODEL_KEY") or os.environ.get("LLM_KEY") or "").strip()
MODEL_ENDPOINT = os.environ.get("MODEL_ENDPOINT", "").strip()
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY")
FACTCHECK_KEY = os.environ.get("GOOGLE_FACTCHECK_KEY")
DEVICE = "cpu"; TOP_K = 5
QPREFIX = "Represent this sentence for searching relevant passages: "
torch.set_num_threads(os.cpu_count() or 2)

def _env_labels(name, default):
    return [x.strip().upper() for x in os.environ.get(name, default).split(",") if x.strip()]

CLF_FALLBACK_LABELS = _env_labels("CLF_LABELS", "REAL,FAKE")
NLI_FALLBACK_LABELS = _env_labels("NLI_LABELS", "SUPPORTED,REFUTED,NOT_ENOUGH_EVIDENCE")

# ===================== load models =====================
print("Loading classifier...")
clf_dir = snapshot_download(CLF_REPO, token=HF_TOKEN)
clf = AutoModelForSequenceClassification.from_pretrained(clf_dir).to(DEVICE).eval()
clf_tok = AutoTokenizer.from_pretrained(clf_dir)
print("Loading verifier...")
nli_dir = snapshot_download(NLI_REPO, token=HF_TOKEN)
nli = AutoModelForSequenceClassification.from_pretrained(nli_dir).to(DEVICE).eval()
nli_tok = AutoTokenizer.from_pretrained(nli_dir)
print("Loading index...")
idx_path = hf_hub_download(RET_REPO, "faiss_index.bin", repo_type="dataset", token=HF_TOKEN)
psg_path = hf_hub_download(RET_REPO, "passages.csv", repo_type="dataset", token=HF_TOKEN)
index = faiss.read_index(idx_path)
passages = pd.read_csv(psg_path)
SRC_COL = next((c for c in ["source", "source_dataset", "dataset", "origin", "domain"] if c in passages.columns), None)
def _avglen(c):
    try: return passages[c].astype(str).str.len().mean()
    except Exception: return 0
TEXT_COL = max([c for c in passages.columns if c != SRC_COL], key=_avglen)
print("Loading embedder...")
embedder = SentenceTransformer("BAAI/bge-small-en-v1.5", device=DEVICE)
print("External services ->", bool(MODEL_KEY), bool(NEWSAPI_KEY), bool(FACTCHECK_KEY))

# ===================== inference =====================
def esc(x):
    return html.escape(str(x or ""), quote=True)

def _canonical_label(label, kind):
    s = str(label or "").upper().replace("-", "_").replace(" ", "_")
    if kind == "clf":
        if s in {"REAL", "TRUE", "TRUTH", "RELIABLE", "LABEL_REAL", "LABEL_TRUE"}:
            return "REAL"
        if s in {"FAKE", "FALSE", "UNRELIABLE", "MISLEADING", "LABEL_FAKE", "LABEL_FALSE"}:
            return "FAKE"
    else:
        if s in {"SUPPORTED", "SUPPORT", "ENTAILMENT", "ENTAILED", "LABEL_SUPPORTED"}:
            return "SUPPORTED"
        if s in {"REFUTED", "REFUTE", "CONTRADICTION", "CONTRADICTED", "LABEL_REFUTED"}:
            return "REFUTED"
        if s in {"NOT_ENOUGH_EVIDENCE", "NEI", "NEUTRAL", "UNKNOWN", "LABEL_NEI"}:
            return "NOT_ENOUGH_EVIDENCE"
    return s

def label_of(model, i, kind):
    lab = model.config.id2label.get(i, "")
    if lab and not lab.upper().startswith("LABEL_"):
        return _canonical_label(lab, kind)
    fallback = CLF_FALLBACK_LABELS if kind == "clf" else NLI_FALLBACK_LABELS
    if i < len(fallback):
        return _canonical_label(fallback[i], kind)
    return f"CLASS_{i}"

def retrieve(claim, k=TOP_K):
    q = np.asarray(embedder.encode([QPREFIX + claim], normalize_embeddings=True), dtype="float32")
    sc, ids = index.search(q, k)
    return [(float(s), str(passages.iloc[i][TEXT_COL]), str(passages.iloc[i][SRC_COL]) if SRC_COL else "")
            for s, i in zip(sc[0], ids[0]) if 0 <= i < len(passages)]

def nli_predict(evidence, claim):
    inp = nli_tok(evidence, claim, truncation=True, max_length=256, return_tensors="pt").to(DEVICE)
    with torch.no_grad(): p = nli(**inp).logits.softmax(-1)[0].cpu().numpy()
    return {label_of(nli, i, "nli"): float(p[i]) for i in range(len(p))}

def classify(text):
    inp = clf_tok(text, truncation=True, max_length=256, return_tensors="pt").to(DEVICE)
    with torch.no_grad(): p = clf(**inp).logits.softmax(-1)[0].cpu().numpy()
    return {label_of(clf, i, "clf"): float(p[i]) for i in range(len(p))}

# ===================== live cross-check =====================
def google_factcheck(claim):
    if not FACTCHECK_KEY: return []
    try:
        r = requests.get("https://factchecktools.googleapis.com/v1alpha1/claims:search",
                         params={"query": claim, "key": FACTCHECK_KEY, "languageCode": "en"}, timeout=12)
        out = []
        for c in r.json().get("claims", [])[:8]:
            ctext = c.get("text", "")
            for rev in c.get("claimReview", [])[:1]:
                out.append({"publisher": rev.get("publisher", {}).get("name", "Fact-checker"),
                            "rating": rev.get("textualRating", ""), "title": rev.get("title", ""), "ctext": ctext})
        return out
    except Exception as e: print("factcheck error:", e); return []

def news_search(claim):
    if not NEWSAPI_KEY: return []
    try:
        r = requests.get("https://newsapi.org/v2/everything",
                         params={"q": claim, "apiKey": NEWSAPI_KEY, "pageSize": 5, "language": "en", "sortBy": "relevancy"}, timeout=12)
        return [{"title": a.get("title", ""), "desc": a.get("description", "") or "",
                 "source": a.get("source", {}).get("name", "")} for a in r.json().get("articles", [])[:5]]
    except Exception as e: print("news error:", e); return []

ENGINE_MODEL = os.environ.get("MODEL_NAME", "gpt-4o-mini")
SEARCH_MODEL = os.environ.get("MODEL_SEARCH_NAME", ENGINE_MODEL)

def _extract_response_text(data):
    if isinstance(data, dict):
        if data.get("output_text"):
            return str(data["output_text"]).strip()
        chunks = []
        for item in data.get("output", []) or []:
            for c in item.get("content", []) or []:
                if isinstance(c, dict) and c.get("text"):
                    chunks.append(str(c["text"]))
        if chunks:
            return "\n".join(chunks).strip()
    return ""

def _call_model(payload, timeout=35):
    if not MODEL_ENDPOINT:
        raise RuntimeError("MODEL_ENDPOINT is not configured.")
    headers = {"Authorization": f"Bearer {MODEL_KEY}", "Content-Type": "application/json"}
    r = requests.post(MODEL_ENDPOINT, headers=headers, json=payload, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"verification endpoint returned HTTP {r.status_code}: {r.text[:300]}")
    return r.json()

def engine_verdict(claim, news, facts):
    if not MODEL_KEY: return None
    ctx = ""
    if facts: ctx += "Known fact-check ratings:\n" + "\n".join(f"- {f['publisher']}: {f['rating']} — {f['title']}" for f in facts) + "\n"
    if news:  ctx += "Some recent headlines:\n" + "\n".join(f"- {n['source']}: {n['title']}" for n in news) + "\n"
    instructions = ("You are a precise fact-verification assistant for a fake-news detection system. "
                    "Use current reliable sources when the claim is recent or time-sensitive. "
                    "Ignore any provided source that is about a different claim. "
                    "If evidence is missing, conflicting, or weak, return UNCERTAIN instead of guessing.")
    user = (f'Claim: "{claim}"\n\n{ctx}\n'
            'Reply ONLY as compact JSON: {"verdict":"REAL|FAKE|UNCERTAIN","confidence":0-1,"reason":"one short sentence"}.')
    try:
        txt = None
        for tool in ({"type": "web_search_preview", "search_context_size": "medium"}, {"type": "web_search"}):
            try:
                payload = {"model": SEARCH_MODEL, "tools": [tool], "instructions": instructions, "input": user}
                txt = _extract_response_text(_call_model(payload))
                if txt:
                    break
            except Exception as e_ws:
                print(f"Verification web search failed with {tool.get('type')} on {SEARCH_MODEL}:", e_ws)
        if not txt:
            payload = {
                "model": ENGINE_MODEL,
                "instructions": instructions,
                "input": user,
            }
            txt = _extract_response_text(_call_model(payload))
        m = re.search(r"\{.*\}", txt, re.S)
        out = json.loads(m.group(0)) if m else None
        if not out:
            return None
        v = str(out.get("verdict", "UNCERTAIN")).upper()
        if v not in {"REAL", "FAKE", "UNCERTAIN"}:
            out["verdict"] = "UNCERTAIN"
        out["confidence"] = max(0.0, min(1.0, float(out.get("confidence", 0.5) or 0.5)))
        return out
    except Exception as e:
        print("Verification engine error:", e); return None

def rating_to_tag(rating):
    r = (rating or "").lower()
    if any(w in r for w in ["false", "pants", "incorrect", "misleading", "no evidence", "fake", "hoax", "wrong"]): return "REFUTED"
    if any(w in r for w in ["true", "correct", "accurate"]): return "SUPPORTED"
    return "NOT_ENOUGH_EVIDENCE"

STOP = set("about above after again against because before being between both could doing during each from have having into more most other some such than that them then there these they this those through under until very were what when where which while with would your".split())
def _kw(s): return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) > 3 and w not in STOP}
def _relevant(text, claim_kw, n=2): return len(_kw(text) & claim_kw) >= n

def is_url(s): return bool(re.match(r"^https?://", s.strip(), re.I))
def fetch_claim_from_url(url):
    try:
        from bs4 import BeautifulSoup
        html = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12).text
        soup = BeautifulSoup(html, "html.parser")
        def meta(p):
            t = soup.find("meta", property=p) or soup.find("meta", attrs={"name": p})
            return t.get("content").strip() if t and t.get("content") else ""
        title = meta("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
        desc = meta("og:description") or meta("description") or ""
        claim = (title + (". " + desc if desc else "")).strip()
        return claim[:400] or None
    except Exception as e:
        print("url fetch error:", e); return None

# ===================== result rendering =====================
VMAP = {"REAL": ("v-real", "Likely Real", "✔"), "FAKE": ("v-fake", "Likely Fake", "✘"), "NEI": ("v-nei", "Not Enough Evidence", "▢")}
TAGMAP = {"SUPPORTED": ("t-ok", "supports"), "REFUTED": ("t-bad", "refutes"), "NOT_ENOUGH_EVIDENCE": ("t-mid", "neutral")}
RECS = {
    "REAL": ["The available evidence supports this statement.", "Confirm with an official primary source before acting on it.", "Safe to cite with proper attribution."],
    "FAKE": ["The available evidence contradicts this statement.", "Do not share it without independent verification.", "Check the original or official source directly."],
    "NEI":  ["Not enough reliable evidence was found to decide.", "Treat the statement as unverified for now.", "Look for primary sources or official statements."],
}

def card(key, conf, reason, ev_rows, clf_r, sources_used="", headline=""):
    cls, label, icon = VMAP[key]
    score = round(conf * 100) if key == "REAL" else round((1 - conf) * 100) if key == "FAKE" else 50
    head = f'<div class="src-head"><span>Source headline</span>{esc(headline)}</div>' if headline else ""
    ev = ""
    for top, prob, passage, src in ev_rows:
        tc, tl = TAGMAP.get(top, ("t-mid", "neutral"))
        srctxt = f'<span class="ev-src">{esc(src)}</span>' if src else ""
        ev += (f'<div class="ev-row"><div class="ev-top"><span class="ev-tag {tc}">{tl} · {prob:.2f}</span>{srctxt}</div>'
               f'<div class="ev-text">{esc(passage[:260])}</div></div>')
    recs = "".join(f"<li>{esc(r)}</li>" for r in RECS[key])
    used = f'<div class="src-used">Cross-checked: {esc(sources_used)}</div>' if sources_used else ""
    return f"""
    <div class="result {cls} reveal">
      {head}
      <div class="v-top">
        <div class="v-icon">{icon}</div>
        <div><div class="v-label">{esc(label)}</div><div class="v-reason">{esc(reason)}</div></div>
      </div>
      <div class="score">
        <div class="score-row"><span>Credibility Score</span><span class="score-num">{score}/100</span></div>
        <div class="score-track"><div class="score-fill" style="width:{score}%"></div></div>
      </div>
      {used}
      <div class="detail-grid">
        <div class="detail"><span>Verdict</span><b>{esc(label)}</b></div>
        <div class="detail"><span>Confidence</span><b>{conf*100:.0f}%</b></div>
        <div class="detail"><span>Evidence items</span><b>{len(ev_rows)}</b></div>
      </div>
      <div class="block-title">Recommendations</div>
      <ul class="rec-list">{recs}</ul>
      <div class="block-title">Evidence checked</div>
      {ev or '<div class="ev-empty">No directly relevant evidence found.</div>'}
    </div>"""

WELCOME = ('<div class="result welcome reveal"><div class="welcome-ic">🛡️</div>'
           '<div class="welcome-t">Your verification report will appear here</div>'
           '<div class="welcome-s">Enter a claim, headline, or article link and press Analyze.</div></div>')

SPINNER_CARD = ('<div class="result" style="text-align:center;padding:48px 22px">'
                '<div class="modal-spinner" style="margin:0 auto"></div>'
                '<div class="modal-title" style="margin-top:16px">Analyzing… Please wait</div>'
                '<div class="modal-sub">Searching evidence and cross-checking through system</div>'
                '<div class="modal-dots" style="margin-top:14px"><i></i><i></i><i></i></div></div>')

def err(msg): return f'<div class="result v-nei"><div class="v-label">⚠ Unable to read</div><div class="v-reason">{esc(msg)}</div></div>'

def card_with_headline(html, headline):
    note = f'<div class="src-head"><span>Source headline</span>{esc(headline)}</div>'
    return html.replace('<div class="result', note + '<div class="result', 1)

# ===================== fusion (unchanged logic) =====================
def _decide(claim):
    ev = retrieve(claim, TOP_K)
    sup = ref = 0; bs = br = 0.0; local_rows = []
    for sc, passage, src in ev:
        r = nli_predict(passage, claim); top = max(r, key=r.get)
        local_rows.append((top, r[top], passage, src))
        if top == "SUPPORTED" and r["SUPPORTED"] >= 0.70: sup += 1; bs = max(bs, r["SUPPORTED"])
        if top == "REFUTED" and r["REFUTED"] >= 0.70: ref += 1; br = max(br, r["REFUTED"])
    clf_r = classify(claim)
    if sup >= 2 and sup > ref: local = ("REAL", bs, f"{sup} evidence passages support this statement.")
    elif ref >= 2 and ref > sup: local = ("FAKE", br, f"{ref} evidence passages refute this statement.")
    elif sup == 1 and ref == 0 and bs >= 0.90: local = ("REAL", bs, "A strong supporting passage was found.")
    elif ref == 1 and sup == 0 and br >= 0.90: local = ("FAKE", br, "A strong refuting passage was found.")
    else: local = ("NEI", max(clf_r.get("REAL", 0), clf_r.get("FAKE", 0)), "Local evidence was weak or mixed.")

    if not (MODEL_KEY or FACTCHECK_KEY or NEWSAPI_KEY):
        return card(local[0], local[1], local[2], local_rows, clf_r, "project evidence base")

    ck = _kw(claim)
    facts = [f for f in google_factcheck(claim) if _relevant(f["title"] + " " + f.get("ctext", ""), ck)]
    news = [n for n in news_search(claim) if _relevant(n["title"] + " " + n["desc"], ck)]
    live_rows, used = [], []
    for f in facts: live_rows.append((rating_to_tag(f["rating"]), 0.99, f"{f['rating']} — {f['title']}", f["publisher"]))
    for n in news[:3]: live_rows.append(("NOT_ENOUGH_EVIDENCE", 0.50, f"{n['title']}. {n['desc']}", n["source"]))
    if facts: used.append("trusted fact-checks")
    if news:  used.append("live news")

    eng = engine_verdict(claim, news, facts)
    if eng:
        v = str(eng.get("verdict", "UNCERTAIN")).upper(); conf = float(eng.get("confidence", 0.7) or 0.7)
        kk = {"REAL": "REAL", "FAKE": "FAKE"}.get(v, None)
        if kk:
            used.append("verification engine")
            reason = eng.get("reason", "Assessed against trusted sources.")
            live_rows.append(("SUPPORTED" if kk == "REAL" else "REFUTED", conf, reason, "Verification engine"))
            return card(kk, conf, reason, live_rows, clf_r, ", ".join(used))
        used.append("verification engine")
        reason = eng.get("reason", "Current evidence was insufficient or mixed.")
        live_rows.append(("NOT_ENOUGH_EVIDENCE", conf, reason, "Verification engine"))
        return card("NEI", conf, reason, live_rows or local_rows, clf_r, ", ".join(used))

    fc_tags = [rating_to_tag(f["rating"]) for f in facts]
    fc_key = "FAKE" if ("REFUTED" in fc_tags and "SUPPORTED" not in fc_tags) else \
             "REAL" if ("SUPPORTED" in fc_tags and "REFUTED" not in fc_tags) else None
    if fc_key:
        return card(fc_key, 0.95, "Based on professional fact-check ratings.", live_rows, clf_r, ", ".join(used))
    if local[0] != "NEI":
        return card(local[0], local[1], local[2], local_rows, clf_r, "project evidence base")
    return card("NEI", local[1], "Evidence was weak or mixed across all sources.",
                live_rows or local_rows, clf_r, ", ".join(used) if used else "")

def verify(user_input):
    text = (user_input or "").strip()
    if not text:
        yield WELCOME; return
    yield SPINNER_CARD                      # immediate visible feedback
    headline = ""
    if is_url(text):
        claim = fetch_claim_from_url(text)
        if not claim:
            yield err("That link could not be read (the site may block access). Paste the headline or claim text instead.")
            return
        headline = f"“{claim[:170]}”"
    else:
        claim = text
    html = _decide(claim)
    yield card_with_headline(html, headline) if headline else html

# ===================== premium dark UI =====================
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
:root{
  --bg:#0B0F19; --bg2:#0E1117; --surface:#121829; --surface2:#161d31;
  --border:rgba(255,255,255,.08); --line:rgba(255,255,255,.06);
  --text:#E6E9F2; --muted:#9AA3B8; --faint:#6b7488;
  --indigo:#6366F1; --purple:#8B5CF6; --teal:#14B8A6; --emerald:#34D399; --danger:#F87171; --amber:#FBBF24;
  --grad:linear-gradient(135deg,#6366F1,#14B8A6);
}
.gradio-container{background:radial-gradient(1200px 600px at 50% -10%,#16203a 0%,var(--bg) 55%) !important;
  max-width:100% !important;margin:0 !important;padding:0 !important;font-family:'Plus Jakarta Sans',sans-serif !important;color:var(--text) !important;}
.gradio-container *{font-family:'Plus Jakarta Sans',sans-serif;}
footer{visibility:hidden;}
.wrap-pad{max-width:1180px;margin:0 auto;padding:0 22px;}
h1,h2,h3,.font-h{font-family:'Sora',sans-serif !important;}

/* reveal on scroll */
.reveal{opacity:0;transform:translateY(16px);transition:opacity .6s ease,transform .6s ease;}
.reveal.in{opacity:1;transform:none;}

/* HERO */
#hero{position:relative;text-align:center;padding:70px 22px 40px;}
#hero .eyebrow{display:inline-block;font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--teal);
  border:1px solid var(--border);border-radius:999px;padding:6px 14px;background:rgba(20,184,166,.06);}
#hero h1{font-size:54px;line-height:1.05;font-weight:800;margin:20px auto 0;max-width:900px;letter-spacing:-1px;}
#hero h1 .g{background:var(--grad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}
#hero p.sub{color:var(--muted);font-size:18px;max-width:640px;margin:18px auto 0;line-height:1.6;}
.infocard{margin:34px auto 0;max-width:760px;background:linear-gradient(180deg,rgba(255,255,255,.04),rgba(255,255,255,.01));
  border:1px solid var(--border);border-radius:20px;padding:22px 24px;backdrop-filter:blur(10px);
  display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap;text-align:left;}
.infocard .col span{display:block;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin-bottom:6px;}
.infocard .col b{color:var(--text);font-weight:600;font-size:14.5px;line-height:1.7;}
.infocard .uni{width:100%;border-top:1px solid var(--line);padding-top:12px;color:var(--muted);font-size:13.5px;text-align:center;}

/* section heading */
.sec{padding:46px 0 8px;}
.sec .kick{text-align:center;color:var(--teal);font-size:13px;letter-spacing:.12em;text-transform:uppercase;}
.sec h2{text-align:center;font-size:32px;font-weight:700;margin:8px 0 6px;letter-spacing:-.5px;}
.sec .lead{text-align:center;color:var(--muted);max-width:620px;margin:0 auto;font-size:15.5px;}

/* about */
.about{display:grid;grid-template-columns:1.2fr 1fr;gap:22px;margin-top:24px;}
.about .txt{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:24px;color:var(--muted);font-size:15.5px;line-height:1.7;}
.about .txt b{color:var(--text);}
.hl{display:grid;gap:12px;}
.hl .item{display:flex;gap:14px;align-items:flex-start;background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:16px 18px;transition:transform .25s ease,border-color .25s;}
.hl .item:hover{transform:translateY(-4px);border-color:rgba(99,102,241,.4);}
.hl .ic{width:38px;height:38px;flex:0 0 38px;border-radius:11px;display:flex;align-items:center;justify-content:center;background:rgba(99,102,241,.12);color:#a5b4fc;font-size:18px;}
.hl h4{margin:0;font-size:15px;color:var(--text);} .hl p{margin:3px 0 0;color:var(--muted);font-size:13.5px;}

/* steps */
.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:26px;}
.step{position:relative;background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:20px 18px;transition:transform .25s ease,border-color .25s;}
.step:hover{transform:translateY(-4px);border-color:rgba(20,184,166,.4);}
.step .n{width:34px;height:34px;border-radius:10px;background:var(--grad);color:#fff;font-weight:700;display:flex;align-items:center;justify-content:center;font-family:'JetBrains Mono';}
.step h4{margin:12px 0 4px;font-size:15.5px;} .step p{margin:0;color:var(--muted);font-size:13.5px;line-height:1.5;}

/* scanner */
.scanner{max-width:820px;margin:24px auto 0;}
#claimbox textarea{background:var(--surface2) !important;border:1px solid var(--border) !important;border-radius:18px !important;
  color:var(--text) !important;font-size:16px !important;padding:16px 18px !important;font-family:'JetBrains Mono',monospace !important;
  box-shadow:0 10px 30px rgba(0,0,0,.35);transition:border-color .2s,box-shadow .2s;}
#claimbox textarea:focus{border-color:var(--indigo) !important;box-shadow:0 0 0 4px rgba(99,102,241,.18),0 10px 30px rgba(0,0,0,.4) !important;}
#claimbox label,#claimbox span{color:var(--muted) !important;}
#analyzebtn{background:var(--grad) !important;border:none !important;color:#fff !important;font-weight:700 !important;
  font-size:16px !important;border-radius:14px !important;padding:14px !important;box-shadow:0 10px 26px rgba(99,102,241,.35) !important;transition:transform .2s,box-shadow .2s !important;}
#analyzebtn:hover{transform:translateY(-3px) !important;box-shadow:0 16px 34px rgba(99,102,241,.45) !important;}
#clearbtn{background:var(--surface2) !important;border:1px solid var(--border) !important;color:var(--muted) !important;border-radius:14px !important;}
.examples-note{color:var(--faint);font-size:13px;margin:14px 0 4px;text-align:center;}
button.gr-button.example, .gradio-container [data-testid] .example{background:var(--surface) !important;}

/* result card */
.result{background:linear-gradient(180deg,rgba(255,255,255,.035),rgba(255,255,255,.012));border:1px solid var(--border);
  border-radius:20px;padding:22px;backdrop-filter:blur(10px);}
.result.welcome{text-align:center;padding:54px 22px;color:var(--muted);}
.welcome-ic{font-size:44px;} .welcome-t{margin-top:12px;color:var(--text);font-weight:600;font-size:16px;} .welcome-s{color:var(--faint);font-size:13.5px;margin-top:4px;}
.src-head{background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.25);border-radius:12px;padding:9px 13px;margin-bottom:14px;color:#fcd96b;font-size:13.5px;}
.src-head span{display:block;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#b9933a;margin-bottom:2px;}
.v-top{display:flex;gap:16px;align-items:center;}
.v-icon{width:54px;height:54px;flex:0 0 54px;border-radius:16px;display:flex;align-items:center;justify-content:center;font-size:26px;font-weight:800;}
.v-label{font-family:'Sora';font-size:23px;font-weight:800;}
.v-reason{color:var(--muted);font-size:14.5px;margin-top:3px;}
.v-real .v-icon{background:rgba(52,211,153,.14);color:var(--emerald);} .v-real .v-label{color:var(--emerald);}
.v-fake .v-icon{background:rgba(248,113,113,.14);color:var(--danger);} .v-fake .v-label{color:var(--danger);}
.v-nei .v-icon{background:rgba(154,163,184,.14);color:var(--muted);} .v-nei .v-label{color:#c3cad9;}
.score{margin-top:18px;} .score-row{display:flex;justify-content:space-between;font-size:13px;color:var(--muted);}
.score-num{font-family:'JetBrains Mono';color:var(--text);font-weight:600;}
.score-track{height:10px;border-radius:999px;background:rgba(255,255,255,.07);margin-top:7px;overflow:hidden;}
.score-fill{height:100%;border-radius:999px;transition:width 1.1s cubic-bezier(.2,.8,.2,1);}
.v-real .score-fill{background:linear-gradient(90deg,#10b981,#34d399);} .v-fake .score-fill{background:linear-gradient(90deg,#ef4444,#f87171);} .v-nei .score-fill{background:linear-gradient(90deg,#64748b,#94a3b8);}
.src-used{margin-top:12px;font-size:12.5px;color:var(--teal);}
.detail-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px;}
.detail{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:11px 13px;}
.detail span{display:block;font-size:11px;color:var(--faint);text-transform:uppercase;letter-spacing:.06em;} .detail b{font-size:15px;}
.block-title{font-family:'Sora';font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);margin:18px 0 8px;}
.rec-list{margin:0;padding-left:18px;color:var(--muted);font-size:14px;line-height:1.7;} .rec-list li{margin-bottom:4px;}
.ev-row{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:11px 13px;margin:7px 0;}
.ev-top{display:flex;gap:8px;align-items:center;} .ev-src{color:var(--faint);font-size:12px;}
.ev-tag{border-radius:7px;padding:2px 9px;font-size:11.5px;font-weight:700;color:#fff;}
.t-ok{background:#10b981;} .t-bad{background:#ef4444;} .t-mid{background:#64748b;}
.ev-text{color:#c6ccdb;font-size:13.5px;margin-top:6px;} .ev-empty{color:var(--faint);font-size:13.5px;}

/* features */
.features{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-top:26px;}
.feat{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:22px;transition:transform .25s,border-color .25s;}
.feat:hover{transform:translateY(-4px);border-color:rgba(139,92,246,.4);}
.feat .ic{font-size:22px;width:44px;height:44px;border-radius:12px;background:rgba(139,92,246,.12);color:#c4b5fd;display:flex;align-items:center;justify-content:center;}
.feat h4{margin:14px 0 5px;font-size:16px;} .feat p{margin:0;color:var(--muted);font-size:14px;line-height:1.6;}

/* footer */
#foot{text-align:center;color:var(--faint);font-size:13px;margin:46px 0 30px;padding-top:18px;border-top:1px solid var(--line);}
#foot b{color:var(--muted);}

/* modal */
.modal-overlay{display:none;position:fixed;inset:0;z-index:9999;align-items:center;justify-content:center;
  background:rgba(6,9,16,.72);backdrop-filter:blur(7px);}
.modal-box{background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(255,255,255,.02));border:1px solid var(--border);
  border-radius:22px;padding:40px 48px;text-align:center;box-shadow:0 30px 80px rgba(0,0,0,.55);}
.modal-spinner{width:54px;height:54px;margin:0 auto;border-radius:50%;border:4px solid rgba(255,255,255,.12);
  border-top-color:var(--indigo);border-right-color:var(--teal);animation:spin 1s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
.modal-title{margin-top:18px;font-family:'Sora';font-size:18px;font-weight:700;color:var(--text);}
.modal-sub{margin-top:6px;color:var(--muted);font-size:13.5px;}
.modal-dots{margin-top:14px;display:flex;gap:6px;justify-content:center;}
.modal-dots i{width:7px;height:7px;border-radius:50%;background:var(--teal);opacity:.4;animation:blink 1.2s infinite;}
.modal-dots i:nth-child(2){animation-delay:.2s;} .modal-dots i:nth-child(3){animation-delay:.4s;}
@keyframes blink{0%,100%{opacity:.25;}50%{opacity:1;}}

@media(max-width:860px){
  #hero h1{font-size:38px;} .about{grid-template-columns:1fr;} .steps{grid-template-columns:1fr 1fr;}
  .features{grid-template-columns:1fr;} .detail-grid{grid-template-columns:1fr;} .infocard{flex-direction:column;}
}
"""

FORCE_DARK = """() => { const u=new URL(window.location.href); if(u.searchParams.get('__theme')!=='dark'){ u.searchParams.set('__theme','dark'); window.location.replace(u.href);} }"""
REVEAL_JS = """() => { const io=new IntersectionObserver((es)=>{es.forEach(e=>{if(e.isIntersecting)e.target.classList.add('in');});},{threshold:.12});
  const scan=()=>document.querySelectorAll('.reveal:not(.in)').forEach(el=>io.observe(el));
  scan(); new MutationObserver(scan).observe(document.body,{childList:true,subtree:true}); }"""
SHOW_MODAL = """(x) => { const m=document.getElementById('scan-modal'); if(m){m.style.display='flex'; clearTimeout(window.__mt); window.__mt=setTimeout(()=>m.style.display='none',45000);} return x; }"""
HIDE_MODAL = """() => { const m=document.getElementById('scan-modal'); if(m){m.style.display='none';} }"""

with gr.Blocks(title="Evidence-Aware Fake News Detector") as demo:
    gr.HTML("""
    <div id="scan-modal" class="modal-overlay"><div class="modal-box">
      <div class="modal-spinner"></div>
      <div class="modal-title">Analyzing… Please wait</div>
      <div class="modal-sub">Searching evidence and cross-checking through system</div>
      <div class="modal-dots"><i></i><i></i><i></i></div>
    </div></div>

    <div id="hero" class="reveal">
      <span class="eyebrow">Evidence-Aware Verification</span>
      <h1>Verify news before<br>you <span class="g">believe</span> it.</h1>
      <p class="sub">A research-grade system that checks whether a news claim or article is credible —
      by gathering evidence, weighing it, and cross-verifying trusted sources.</p>
      <div class="infocard">
        <div class="col"><span>Project Team</span><b>Muhammad — 21258<br>M.Abbas — 21223<br>M.Asif — 21228<br>Ahmed Raza — 22211</b></div>
        <div class="col" style="text-align:right"><span>Supervisor</span><b>Dr. Kalsoom Safdar</b></div>
        <div class="uni">University of Jhang · Department of Computer Science &amp; IT</div>
      </div>
    </div>""")

    with gr.Column(elem_classes="wrap-pad"):
        gr.HTML("""<div class="sec reveal"><div class="kick">Overview</div><h2>About the Project</h2></div>
        <div class="about reveal">
          <div class="txt">This system helps readers judge whether a news <b>claim or headline is credible</b>.
          Rather than relying on wording alone, it gathers supporting evidence, checks whether that evidence agrees
          or disagrees with the statement, and cross-verifies current topics against trusted sources — then presents a
          clear verdict with a credibility score and the reasoning behind it. It is designed as an academic research
          prototype for responsible information verification.</div>
          <div class="hl">
            <div class="item"><div class="ic">◎</div><div><h4>Evidence-based</h4><p>Verdicts grounded in retrieved evidence, not guesswork.</p></div></div>
            <div class="item"><div class="ic">⚡</div><div><h4>Fast</h4><p>Results in seconds, with a transparent rationale.</p></div></div>
            <div class="item"><div class="ic">✦</div><div><h4>Comprehensive</h4><p>Combines evidence analysis with trusted cross-checks.</p></div></div>
          </div>
        </div>

        <div class="sec reveal"><div class="kick">Process</div><h2>How It Works</h2></div>
        <div class="steps reveal">
          <div class="step"><div class="n">1</div><h4>Gather</h4><p>Finds evidence most related to your statement.</p></div>
          <div class="step"><div class="n">2</div><h4>Verify</h4><p>Checks whether evidence supports or refutes it.</p></div>
          <div class="step"><div class="n">3</div><h4>Cross-check</h4><p>Confirms current topics with trusted sources.</p></div>
          <div class="step"><div class="n">4</div><h4>Report</h4><p>Delivers a verdict, score, and clear reasoning.</p></div>
        </div>

        <div class="sec reveal"><div class="kick">Try It</div><h2>Verify a Claim or Article</h2>
          <div class="lead">Enter a news claim, headline, or paste an article link.</div></div>""")

        with gr.Row(elem_classes="scanner"):
            with gr.Column():
                inp = gr.Textbox(elem_id="claimbox", label="", lines=3, show_label=False,
                                 placeholder="Type a news claim / headline  —or—  paste an article URL")
                with gr.Row():
                    btn = gr.Button("Analyze", elem_id="analyzebtn", scale=4)
                    clr = gr.Button("Clear", elem_id="clearbtn", scale=1)
                gr.HTML('<div class="examples-note">Examples</div>')
                gr.Examples(examples=[
                    "Climate change is primarily caused by human activity.",
                    "Vaccines cause autism.",
                    "Smoking increases the risk of lung cancer.",
                    "Argentina won the 2022 FIFA World Cup, defeating France in the final.",
                ], inputs=inp)
                out = gr.HTML(WELCOME)

        gr.HTML("""<div class="sec reveal"><div class="kick">Capabilities</div><h2>Features</h2></div>
        <div class="features reveal">
          <div class="feat"><div class="ic">🛡️</div><h4>Credibility scoring</h4><p>A clear 0–100 credibility score with every verdict.</p></div>
          <div class="feat"><div class="ic">🔎</div><h4>Transparent evidence</h4><p>See the passages and sources behind each decision.</p></div>
          <div class="feat"><div class="ic">🌐</div><h4>Current-topic aware</h4><p>Cross-verifies recent events with trusted sources.</p></div>
        </div>

        <div id="foot"><b>© 2026 · Final Year Project · University of Jhang (UOJ)</b><br>
          Department of Computer Science &amp; IT<br>
          <span style="font-size:12px">Research prototype — assists verification, not a replacement for professional fact-checkers.</span></div>""")

    ev = btn.click(verify, inputs=inp, outputs=out, js=SHOW_MODAL)
    ev.then(lambda: None, None, None, js=HIDE_MODAL)
    ev2 = inp.submit(verify, inputs=inp, outputs=out, js=SHOW_MODAL)
    ev2.then(lambda: None, None, None, js=HIDE_MODAL)
    clr.click(lambda: ("", WELCOME), outputs=[inp, out])
    demo.load(js=FORCE_DARK)
    demo.load(js=REVEAL_JS)

if __name__ == "__main__":
    demo.launch(theme=gr.themes.Base(), css=CSS)
