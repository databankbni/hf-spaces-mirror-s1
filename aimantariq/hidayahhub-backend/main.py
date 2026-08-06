
#  HidayahHub 
#  Powered by Groq (LLaMA 3) 
from fastapi import FastAPI, Query
from dotenv import load_dotenv
from groq import Groq
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict
import faiss
import pickle
import numpy as np
import random
import os
import re
from sentence_transformers import SentenceTransformer

# Load environment variables
load_dotenv()

# GROQ AI SETUP
try:
    from groq import Groq
    GROQ_AVAILABLE = True
    print("✓ Groq library available")
except ImportError:
    GROQ_AVAILABLE = False
    print("⚠️  Groq not installed. Run: pip install groq")

app = FastAPI(title="HidayahHub API", version="4.0.0")
app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

print("=" * 50)
print("HidayahHub Backend Starting...")
print("=" * 50)

# Load API key from environment variable (recommended) or fallback
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

AI_AVAILABLE = False
groq_client = None

if GROQ_AVAILABLE and GROQ_API_KEY:
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
        # Quick test to verify key works
        test = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=5
        )
        if test.choices[0].message.content:
            AI_AVAILABLE = True
            print(f"✓ Groq AI is READY! Model: llama-3.1-8b-instant")
    except Exception as e:
        print(f"⚠️  Groq init failed: {e}")
        AI_AVAILABLE = False
else:
    if not GROQ_API_KEY:
        print("⚠️  GROQ_API_KEY not set. Set it as an environment variable:")
        print("    Windows: set GROQ_API_KEY=gsk_...")
        print("    Linux/Mac: export GROQ_API_KEY=gsk_...")
    print("Running in fallback mode (no AI)")


# LOAD EMBEDDING MODEL
print("\nLoading AI embedding model...")
model = None
model_loaded = False

try:
    model = SentenceTransformer("all-MiniLM-L6-v2")
    model_loaded = True
    print("✓ Embedding model loaded!")
except Exception as e:
    print(f"⚠️  Could not load all-MiniLM-L6-v2: {e}")
    try:
        model = SentenceTransformer("paraphrase-MiniLM-L3-v2")
        model_loaded = True
        print("✓ Fallback embedding model loaded!")
    except Exception as e2:
        print(f"⚠️  Could not load any embedding model: {e2}")
        from sklearn.feature_extraction.text import TfidfVectorizer

        class SimpleEmbedder:
            def __init__(self):
                self.vectorizer = TfidfVectorizer(max_features=384)
                self.fitted = False

            def encode(self, texts, normalize_embeddings=True):
                if not self.fitted:
                    sample = [texts] if isinstance(texts, str) else texts
                    self.vectorizer.fit(sample)
                    self.fitted = True
                embeddings = self.vectorizer.transform(
                    [texts] if isinstance(texts, str) else texts
                ).toarray()
                if normalize_embeddings:
                    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
                    embeddings = embeddings / (norms + 1e-8)
                return embeddings.astype("float32")

        model = SimpleEmbedder()
        model_loaded = True
        print("✓ TF-IDF fallback embedder ready (reduced accuracy)")

# LOAD FAISS INDEX & METADATA
print("\nLoading FAISS index...")
index = None
metadata = []

try:
    index = faiss.read_index(os.path.join("Data", "quran_hadith.index"))
    with open(os.path.join("Data", "metadata.pkl"), "rb") as f:
        metadata = pickle.load(f)
    print(f"✓ Ready! {index.ntotal} Quran & Hadith vectors loaded!")
except FileNotFoundError:
    print("❌ Data files not found! Please ensure:")
    print("   - Data/quran_hadith.index")
    print("   - Data/metadata.pkl")
except Exception as e:
    print(f"❌ Error loading data: {e}")

# HELPER FUNCTIONS
def parse_reference(reference: str):
    match = re.match(r'(\d+):(\d+)', reference)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def find_exact_ayah(surah_num: int, ayah_num: int):
    for item in metadata:
        if item['source'] == 'Quran':
            parts = item['reference'].split(':')
            if len(parts) == 2:
                try:
                    if int(parts[0]) == surah_num and int(parts[1]) == ayah_num:
                        return item
                except:
                    pass
    return None


def search_index(query_text: str, top_k: int = 10, source_filter: str = "All"):
    if not model_loaded or index is None:
        return []
    vec = model.encode([query_text], normalize_embeddings=True).astype("float32")
    fetch_k = min(top_k * 5, index.ntotal)
    scores, indices = index.search(vec, fetch_k)
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1 or idx >= len(metadata):
            continue
        row = metadata[idx]
        if source_filter != "All" and row["source"].lower() != source_filter.lower():
            continue
        results.append({**row, "score": round(float(score), 4)})
        if len(results) >= top_k:
            break
    return results

# CONVERSATION HISTORY


conversation_history: Dict[str, List[Dict]] = {}

# GROQ AI RESPONSE
SYSTEM_PROMPT = """You are HidayahBot, a knowledgeable and warm Islamic AI assistant.

Your role:
- Answer questions about Islam clearly, accurately, and conversationally
- Cite the Quran and Hadith naturally in your answers (e.g. "As Allah says in Surah Al-Baqarah 2:286...")
- Give step-by-step guidance when someone asks "how to" do something
- Be warm, empathetic, and encouraging — like a knowledgeable friend
- Use simple language anyone can understand
- Keep responses focused and practical (aim for 3–6 sentences unless a detailed answer is needed)
- Occasionally use relevant emojis (🌙 🕌 📖 🤲 💚) to keep the tone friendly
- If a question is unclear, ask a short clarifying question
- Never make up hadith or Quran references — only cite what you are given in context

You are NOT a mufti giving fatwa — for complex fiqh matters, remind the user to consult a qualified scholar."""


async def get_groq_response(messages: List[Dict]) -> str:
    """Call Groq API with full message history."""
    if not AI_AVAILABLE or not groq_client:
        return None
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=900,
            temperature=0.75,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq API error: {e}")
        return None


def build_messages(session_id: str, user_query: str, context: str) -> List[Dict]:
    """Build the message list: system + history + current user message."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Add conversation history (last 6 turns)
    history = conversation_history.get(session_id, [])
    for turn in history[-6:]:
        messages.append({"role": "user", "content": turn["user"]})
        messages.append({"role": "assistant", "content": turn["assistant"]})

    # Add current user message with Islamic source context
    user_content = user_query
    if context:
        user_content = (
            f"{user_query}\n\n"
            f"[Relevant Islamic sources for context — use these in your answer if appropriate:]\n{context}"
        )
    messages.append({"role": "user", "content": user_content})
    return messages


def simple_fallback(query: str, quran_verses: List[str], hadith_texts: List[str]) -> str:
    """Basic fallback when AI is unavailable."""
    q = query.lower()
    if any(w in q for w in ["how to pray", "prayer steps", "how to offer salah"]):
        return (
            "🕌 To pray (Salah):\n"
            "1. Make intention (Niyyah)\n2. Say Allahu Akbar (start)\n"
            "3. Recite Surah Al-Fatiha\n4. Bow (Ruku)\n5. Prostrate (Sajdah) twice\n"
            "6. Repeat for each rakat\n7. End with Tasleem (Assalamu Alaykum)\n\n"
            "The Quran says: 'Establish prayer for My remembrance.' (20:14)"
        )
    if any(w in q for w in ["wudu", "ablution", "purification"]):
        return (
            "🧼 Wudu steps:\n"
            "1. Intention\n2. Wash hands (×3)\n3. Rinse mouth (×3)\n"
            "4. Rinse nose (×3)\n5. Wash face (×3)\n6. Wash arms to elbows (×3)\n"
            "7. Wipe head\n8. Wash ears\n9. Wash feet (×3)\n\n"
            "The Prophet ﷺ said: 'Cleanliness is half of faith.' (Sahih Muslim)"
        )

    parts = ["🌙 Here's what I found:\n"]
    if quran_verses:
        parts.append(f"📖 Quran: {quran_verses[0][:250]}")
    if hadith_texts:
        parts.append(f"📜 Hadith: {hadith_texts[0][:250]}")
    if len(parts) == 1:
        parts.append(
            "I'm here to help with questions about prayer, fasting, Quran, Hadith, "
            "prophets, and more. What would you like to know?"
        )
    return "\n\n".join(parts)


# ENDPOINTS
@app.get("/chat")
async def chat(query: str = Query(...), session_id: str = Query("default")):
    """Conversational AI chatbot with memory."""
    sources = search_index(query, top_k=5) if index is not None else []

    quran_verses = []
    hadith_texts = []
    for s in sources:
        if s["source"] == "Quran":
            quran_verses.append(f"Quran {s['reference']}: {s['english']}")
        else:
            hadith_texts.append(f"Hadith ({s.get('book','')}) {s['reference']}: {s['english']}")

    # Build context string from search results
    context_lines = quran_verses[:3] + hadith_texts[:3]
    context = "\n".join(context_lines)

    ai_response = None
    if AI_AVAILABLE:
        messages = build_messages(session_id, query, context)
        ai_response = await get_groq_response(messages)

    if not ai_response:
        ai_response = simple_fallback(query, quran_verses, hadith_texts)

    # Save to history
    history = conversation_history.get(session_id, [])
    history.append({"user": query, "assistant": ai_response})
    conversation_history[session_id] = history[-10:]  # keep last 10 turns

    return {
        "query": query,
        "response": ai_response,
        "sources_used": len(sources),
        "ai_used": AI_AVAILABLE,
        "model_used": "llama-3.1-8b-instant" if AI_AVAILABLE else "fallback",
    }


@app.get("/search")
def search_endpoint(
    query: str = Query(...),
    filter: str = Query("All"),
    top_k: int = Query(10)
):
    results = search_index(query, top_k, filter)
    return {"query": query, "total": len(results), "results": results}


@app.get("/tafseer")
async def get_tafseer(reference: str = Query(...), question: str = Query("")):
    """AI tafseer for Quran verses."""
    surah_num, ayah_num = parse_reference(reference)
    if not surah_num or not ayah_num:
        return {
            "error": "Tafseer is only available for Quran verses (e.g. 2:255)",
            "is_quran": False
        }

    ayah = find_exact_ayah(surah_num, ayah_num)
    if not ayah:
        return {"error": f"Verse {reference} not found.", "is_quran": False}

    verse_info = (
        f"Quran {ayah['reference']}\n"
        f"Arabic: {ayah.get('arabic', 'N/A')}\n"
        f"Translation: {ayah['english']}"
    )

    if AI_AVAILABLE:
        user_msg = (
            f"Please provide a clear, practical tafseer (explanation) for this Quran verse:\n\n"
            f"{verse_info}\n\n"
            f"{'Question: ' + question if question else 'Explain the meaning and lessons of this verse.'}"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg}
        ]
        tafseer = await get_groq_response(messages)
        if tafseer:
            return {
                "reference": reference,
                "tafseer": tafseer,
                "verse_text": ayah["english"],
                "arabic_text": ayah.get("arabic", ""),
                "is_quran": True,
                "ai_generated": True,
            }

    return {
        "reference": reference,
        "tafseer": (
            f"Translation: {ayah['english']}\n\n"
            "This verse is a reminder of Allah's guidance. "
            "Reflect on its meaning and apply it in your daily life."
        ),
        "verse_text": ayah["english"],
        "arabic_text": ayah.get("arabic", ""),
        "is_quran": True,
        "ai_generated": False,
    }


@app.get("/mood/{mood}")
def mood_search(mood: str, top_k: int = Query(8)):
    mood_queries = {
        "anxious": "anxiety fear worry peace calm trust Allah",
        "sad": "sadness grief crying sorrow comfort consolation",
        "grateful": "gratitude thankfulness blessings shukr praise Allah",
        "lost": "guidance direction lost confused right path hidayah",
        "hopeful": "hope future promise relief ease after hardship",
        "angry": "anger control patience forgiveness self-restraint",
        "lonely": "loneliness Allah always near close companionship",
        "motivated": "striving effort hard work success reward paradise",
        "sinful": "repentance forgiveness tawbah mercy sins Allah",
        "stressed": "stress burden relief peace tranquility dhikr",
    }
    q = mood_queries.get(mood.lower(), mood)
    results = search_index(q, top_k)
    return {"mood": mood, "query_used": q, "total": len(results), "results": results}


@app.get("/similar/{result_id}")
def find_similar(result_id: int, top_k: int = Query(5)):
    row = next((m for m in metadata if m.get("id") == result_id), None)
    if not row:
        return {"error": "Not found"}
    results = [r for r in search_index(row["english"], top_k + 2) if r.get("id") != result_id][:top_k]
    return {"original_id": result_id, "total": len(results), "results": results}


@app.get("/journey")
def spiritual_journey(query: str = Query(...)):
    stages = [
        {"label": "Acknowledgement", "desc": "Recognise and accept the feeling",
         "q": f"acknowledge accept {query} feeling"},
        {"label": "Patience (Sabr)", "desc": "Find strength through steadfastness",
         "q": f"patience sabr strength {query}"},
        {"label": "Hope & Promise", "desc": "Hold onto Allah's promise",
         "q": f"hope promise relief ease {query}"},
        {"label": "Gratitude (Shukr)", "desc": "Return with thankfulness",
         "q": f"gratitude shukr thankful {query}"},
    ]
    steps = []
    seen_refs = set()
    for stage in stages:
        for r in search_index(stage["q"], top_k=5):
            if r["reference"] not in seen_refs:
                seen_refs.add(r["reference"])
                steps.append({
                    "label": stage["label"],
                    "desc": stage["desc"],
                    "arabic": r.get("arabic", ""),
                    "english": r["english"],
                    "reference": r["reference"],
                    "book": r.get("book", ""),
                    "source": r["source"],
                })
                break
    return {"query": query, "steps": steps}


@app.get("/daily")
def daily_ayah():
    if index is None:
        return {"error": "Data not loaded"}
    quran_rows = [m for m in metadata if m["source"] == "Quran"]
    if not quran_rows:
        return {"error": "No Quran data found"}
    chosen = random.choice(quran_rows)
    related = search_index(chosen["english"], top_k=2, source_filter="Hadith")
    return {"ayah": chosen, "related_hadith": related[0] if related else None}


@app.get("/topics")
def get_topics():
    return {
        "topics": [
            "patience and perseverance", "gratitude and thankfulness",
            "forgiveness and mercy", "seeking knowledge and wisdom",
            "trust in Allah", "prayer and worship",
            "good character and manners", "hope and optimism",
            "family and relationships", "repentance",
            "hardship and relief", "death and afterlife",
            "generosity and charity", "justice and truth",
            "love and compassion",
        ]
    }


@app.get("/topic/{topic_name}")
def search_topic(topic_name: str, top_k: int = Query(8)):
    results = search_index(topic_name, top_k)
    return {"topic": topic_name, "total": len(results), "results": results}


@app.get("/stats")
def stats():
    if index is None:
        return {"total": 0, "quran": 0, "hadith": 0, "ai_available": AI_AVAILABLE, "error": "Data not loaded"}
    quran = sum(1 for m in metadata if m["source"] == "Quran")
    hadith = sum(1 for m in metadata if m["source"] == "Hadith")
    return {
        "total": len(metadata),
        "quran": quran,
        "hadith": hadith,
        "ai_available": AI_AVAILABLE,
        "model_loaded": model_loaded,
        "groq_model": "llama-3.1-8b-instant" if AI_AVAILABLE else None,
    }


@app.get("/health")
def health_check():
    return {
        "status": "running",
        "ai_available": AI_AVAILABLE,
        "groq_model": "llama-3.1-8b-instant" if AI_AVAILABLE else None,
        "data_loaded": index is not None,
        "vectors_loaded": index.ntotal if index is not None else 0,
    }


@app.get("/")
def root():
    return {
        "app": "HidayahHub",
        "version": "4.0.0",
        "vectors": index.ntotal if index is not None else 0,
        "ai_available": AI_AVAILABLE,
        "groq_model": "llama-3.1-8b-instant" if AI_AVAILABLE else None,
        "status": "running",
    }

# RUN
if __name__ == "__main__":
    import uvicorn
    print("\n" + "=" * 50)
    print("HidayahHub Backend is ready!")
    print("=" * 50)
    print(f"✓ Vectors loaded: {index.ntotal if index else 'N/A'}")
    print(f"✓ AI Mode: {'Groq (LLaMA 3.1) Active' if AI_AVAILABLE else 'Fallback Mode'}")
    print(f"✓ API URL: http://localhost:8000")
    print(f"✓ Docs:    http://localhost:8000/docs")
    print("=" * 50 + "\n")
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)