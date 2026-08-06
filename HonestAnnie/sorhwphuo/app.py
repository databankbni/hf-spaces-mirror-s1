# -*- coding: utf-8 -*-

# ---------------------------------------------------------------------------
# 0) Imports
# ---------------------------------------------------------------------------
import gradio as gr
import chromadb
from google import genai
from google.genai import types as genai_types
import os
from dotenv import load_dotenv
import logging
from collections import defaultdict
import datetime # For timestamped filenames
import numpy as np # For cosine similarity calculation
import json # For the author cache and the favourites ledger
import threading # tiny file‑lock for the JSON ledger
import html # escape text for clickable spans
# ---------------------------------------------------------------------------


# --- Configuration ---

# Configure logging level
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# Load environment variables (for API Key)
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

genai_client = None
if not API_KEY:
    logging.error("GEMINI_API_KEY not found in environment variables.")
else:
    try:
        genai_client = genai.Client(api_key=API_KEY)
        logging.info("Gemini API configured successfully.")
    except Exception as e:
        logging.error(f"Error configuring Gemini API: {e}")
        API_KEY = None

# Chroma DB Configuration
# The DB is ~2.5 GB and no longer fits the Space's git storage, so it lives in a
# private dataset repo and is pulled at startup. A local ./chroma still wins, so
# development runs untouched and offline.
COLLECTION_NAME = "phil_de"
CHROMA_REPO = os.getenv("CHROMA_REPO", "HonestAnnie/thought-loop-chroma")


def _resolve_chroma_path():
    if os.path.exists("./chroma/chroma.sqlite3"):
        logging.info("Using local Chroma DB at ./chroma")
        return "./chroma"

    # /data only exists when the Space has persistent storage booked; without it
    # the download repeats on every cold start.
    target = "/data/chroma" if os.path.isdir("/data") else "./chroma_cache"
    logging.info(f"No local Chroma DB. Downloading '{CHROMA_REPO}' to {target} ...")
    from huggingface_hub import snapshot_download
    path = snapshot_download(
        repo_id=CHROMA_REPO,
        repo_type="dataset",
        local_dir=target,
        token=os.getenv("HF_TOKEN"),
    )
    logging.info(f"Chroma DB ready at {path}")
    return path


CHROMA_DB_PATH = _resolve_chroma_path()

# Gemini Model Configuration
EMBEDDING_MODEL = "gemini-embedding-2" # Must match the model the corpus vectors were built with
LLM_RERANK_MODEL_NAME = "gemini-pro-latest" # Alias that always points at the current recommended stable Pro model

logging.info(f"Using embedding model: {EMBEDDING_MODEL}")
logging.info(f"Using LLM Re-Rank/Truncate generation model: {LLM_RERANK_MODEL_NAME}")

# --- Constants ---
MAX_RESULTS_STANDARD = 20 # Max results shown in standard search after re-ranking
INITIAL_RESULTS_FOR_RERANK = 300 # How many results to fetch initially for re-ranking passes
RERANK_WINDOW_SIZE = 2 # +/- N sentences to consider for contextual re-ranking (both passes)
MIN_CHARS_FOR_RELEVANT_NEIGHBOR = 6 # Minimum characters for a neighbor to contribute to the re-rank score
# Weight factor for neighbor similarity in 1st pass re-rank score.
# Calibrated 2026-08-01 on 120 synthetic queries (an LLM wrote a thematic and a
# sentence-specific German query for each of 60 real paragraphs; the metric is where the
# source paragraph lands in the top 20), cross-checked with pointwise relevance ratings
# on 19 hand-written queries. Findings:
#   * The old 0.5 was measurably WORSE than switching context re-ranking off entirely
#     (MRR 0.522 vs 0.599; paired bootstrap 95% CI [-0.139, -0.017], n=120).
#   * The optimum is flat across 0.1-0.2; 0.4 and above degrades results.
#   * The gain over no context at all is small and not significant (+0.006 MRR), i.e.
#     query-time neighbor averaging is a weak substitute for context-aware embeddings.
# 0.15 sits in the flat optimum, leaning slightly toward thematic queries, which is the
# app's main use (search, then "weiterlesen" into the surrounding paragraph).
RERANK_WEIGHT = 0.15
# Score decay per sentence distance. The sweep could not distinguish decay values at any
# sensible weight (spread <= 0.02 MRR, far inside the bootstrap CI), so this is chosen for
# interpretability rather than fit: a neighbor two sentences away counts half as much as
# an immediate one. Window size likewise showed no measurable effect (best achievable MRR
# 0.613-0.614 for windows 1-4), so RERANK_WINDOW_SIZE stays at 2 for a readable context block.
RERANK_DECAY = 0.5
# How much evidence (sum of decayed neighbor weights) is needed before the context
# score is trusted at full strength. Below this the context term is shrunk towards
# the passage's own similarity, so a single lucky neighbor cannot carry a passage.
RERANK_FULL_EVIDENCE_WEIGHT = 2.0
LLM_RERANK_CANDIDATE_COUNT = 25 # How many candidates (after 1st pass re-rank) to send to LLM
LLM_RERANK_TARGET_COUNT = 10 # How many final edited results to request from LLM
LLM_MAX_OUTPUT_TOKENS = 8192 # Hard cap so a runaway response fails loudly instead of silently truncating
LLM_THINKING_BUDGET = 2048 # Bounded thinking budget for the (mechanical) re-ranking task
PROMPT_LOG_DIR = "./prompts" # Directory to save LLM prompts for debugging
MAX_PROMPT_LOGS = 200 # Keep only the newest N prompt logs; older ones are pruned on startup
MAX_RESULTS_PER_AUTHOR = None # Max results from a single author in the final (displayed) list
MAX_FAVOURITES = 50 # Max favourites to load for display
AUTHOR_CACHE_FILE = "./authors_cache.json" # Cached author list, keyed by collection count
NEIGHBOR_EMBEDDING_CACHE_SIZE = 20000 # Max individual sentence embeddings held in memory

# --- Constants for Highlighting ---
HIGHLIGHT_HUE = 60 # Yellowish hue
HIGHLIGHT_SATURATION = 100
HIGHLIGHT_LIGHTNESS = 90
HIGHLIGHT_MAX_ALPHA = 0.5 # Max transparency (0 = transparent, 1 = opaque)
HIGHLIGHT_MIN_ALPHA = 0.05 # Minimum alpha for sentences at the threshold (when max > threshold)
# Minimum cosine similarity score to apply highlighting. Recalibrated 2026-08-02 for
# gemini-embedding-2 against 12 real queries (RETRIEVAL_QUERY vs. the stored
# RETRIEVAL_DOCUMENT vectors) plus 1500 randomly sampled corpus sentences; run
# calibrate_threshold.py to reproduce. The new model separates query<->document far
# better than exp-03-07 did: unrelated text now falls off sharply above 0.55, so the
# bar can sit lower without lighting up noise. At 0.62 all 240 measured hits still
# highlight (lowest observed hit: 0.6425, hence the safety margin -- 0.66 would already
# drop 6% of them), about 42% of a displayed paragraph lights up, and only 0.16% of
# random sentences clear the bar.
# Re-run the calibration if EMBEDDING_MODEL changes -- this number is model-specific.
HIGHLIGHT_SIMILARITY_THRESHOLD = 0.62

# ─── FAVOURITES CONFIG ──────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))       # always absolute
FAV_FILE = os.path.join(BASE_DIR, "favourites.json")        # ./favourites.json
_fav_lock = threading.Lock()                                # file‑write lock

# --- Define Prompt for LLM Re-ranking V3 ---
LLM_RERANKING_PROMPT_TEMPLATE_V3 = """
**Task:** Evaluate, truncate, and re-rank the provided text passages based on their relevance to the user's query. Return exactly the top {target_count} most relevant results, including their original IDs, the edited text, and a brief rationale for each selection.

**User Query:**
"{user_query}"

**Text Passages to Evaluate:**
{passage_blocks_str}
--- END OF PASSAGES ---

**Instructions:**
1.  **Analyze Query:** Understand the core question or theme of the User Query.
2.  **Evaluate Each Passage:** For each text passage provided above (identified by "Passage ID:" and separated by '--- PASSAGE SEPARATOR ---'):
    * Read the entire passage carefully.
    * Identify the most relevant contiguous sentences within the passage that directly address or best illuminate the User Query.
    * **Truncate/Edit:** Extract ONLY the most relevant segment. Discard the rest of the passage. The goal is a concise, highly relevant excerpt. If an entire passage seems irrelevant, discard it entirely.
    * **Rationale Generation:** Briefly explain *why* the segment you extracted is relevant to the User Query.
3.  **Rank Edited Passages:** Based on the relevance of the *edited/truncated* segments you created, determine a final ranking. The most relevant edited segment should be ranked first.
4.  **Select Top Results:** Choose exactly the top {target_count} most relevant edited passages from your ranking. If fewer than {target_count} passages were deemed relevant at all, return only those that were.

**Critical constraint on `edited_text`:** It MUST be copied verbatim, character for character, from the passage it came from. Do not paraphrase, translate, modernise the spelling, fix punctuation, join separated sentences with different wording, or add ellipses. You may only choose where the excerpt starts and where it ends. Any excerpt that is not an exact substring of its source passage will be discarded.

Fill in `original_id` with the ID of the passage the text came from, `edited_text` with the verbatim excerpt, and `rationale` with your brief explanation of its relevance. Return the list sorted from most relevant to least relevant.
"""

# Schema for the LLM re-ranking response. Passing this to the API guarantees
# well-formed JSON, so no fence-stripping or regex extraction is needed.
LLM_RERANK_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "ranked_edited_passages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "original_id": {"type": "STRING"},
                    "edited_text": {"type": "STRING"},
                    "rationale": {"type": "STRING"},
                },
                "required": ["original_id", "edited_text", "rationale"],
            },
        }
    },
    "required": ["ranked_edited_passages"],
}

# --- User-facing error text ---
# The search functions return an error *message* next to their results so the UI can tell
# "nothing matched this query" apart from "the search never ran". Previously both arrived
# as an empty list, so an exhausted API quota, a blocked prompt or a truncated LLM
# response were all displayed as "Keine Resultate gefunden."
ERR_EMBEDDING = ("Die Suchanfrage konnte nicht in einen Vektor umgewandelt werden. "
                 "Vermutlich ist der Embedding-Dienst nicht erreichbar oder das Kontingent erschöpft.")
ERR_DB = "Die Datenbank konnte nicht abgefragt werden."
ERR_UNEXPECTED = "Unerwarteter Fehler bei der Suche."
ERR_LLM_UNAVAILABLE = ("Das LLM für die Auswahl ist nicht verfügbar "
                       "(kein API-Schlüssel oder Initialisierung fehlgeschlagen).")
ERR_LLM_BLOCKED = "Die Anfrage wurde vom Sicherheitsfilter des LLM blockiert."
ERR_LLM_TRUNCATED = ("Die Antwort des LLM wurde durch das Token-Limit abgeschnitten und "
                     "konnte nicht ausgewertet werden.")
ERR_LLM_NO_TEXT = "Das LLM hat keine auswertbare Antwort geliefert."
ERR_LLM_PARSE = "Die Antwort des LLM konnte nicht als JSON ausgewertet werden."
ERR_LLM_METADATA = "Zu den ausgewählten Passagen konnten keine Metadaten geladen werden."
ERR_LLM_NO_BLOCKS = "Für die ausgewählten Kandidaten konnten keine Kontextblöcke erzeugt werden."


# --- Prompt Log Housekeeping ---
def _prune_prompt_logs(keep=MAX_PROMPT_LOGS):
    """Deletes all but the newest `keep` prompt logs so the directory stays bounded."""
    try:
        entries = [os.path.join(PROMPT_LOG_DIR, name)
                   for name in os.listdir(PROMPT_LOG_DIR)
                   if name.endswith("_llm_rank_truncate_prompt.txt")]
        if len(entries) <= keep:
            return
        entries.sort(key=os.path.getmtime, reverse=True)
        for stale in entries[keep:]:
            try:
                os.remove(stale)
            except OSError as rm_e:
                logging.debug(f"Could not prune prompt log {stale}: {rm_e}")
        logging.info(f"Pruned {len(entries) - keep} old prompt logs (keeping newest {keep}).")
    except Exception as e:
        logging.warning(f"Prompt log pruning failed: {e}")


# --- Author List Caching ---
def _load_cached_authors(expected_count):
    """Returns the cached author list if it was built from the same collection size."""
    try:
        with open(AUTHOR_CACHE_FILE, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        if cached.get("collection_count") == expected_count and isinstance(cached.get("authors"), list):
            return [a for a in cached["authors"] if isinstance(a, str) and a]
    except FileNotFoundError:
        pass
    except Exception as e:
        logging.warning(f"Could not read author cache {AUTHOR_CACHE_FILE}: {e}")
    return None


def _store_cached_authors(authors, collection_count):
    """Persists the author list so later startups skip the full metadata scan."""
    try:
        with open(AUTHOR_CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump({"collection_count": collection_count, "authors": authors}, fh, ensure_ascii=False, indent=2)
        logging.debug(f"Author cache written to {AUTHOR_CACHE_FILE}.")
    except Exception as e:
        logging.warning(f"Could not write author cache {AUTHOR_CACHE_FILE}: {e}")


def _scan_authors(total_count):
    """Pages through the collection metadata to collect every distinct author."""
    # Page through the collection: a single unfiltered get() over tens of
    # thousands of rows can exceed SQLite's bound-variable limit in newer
    # chromadb versions ("too many SQL variables").
    AUTHOR_FETCH_BATCH_SIZE = 5000
    authors_set = set()
    for batch_offset in range(0, total_count, AUTHOR_FETCH_BATCH_SIZE):
        batch = collection.get(include=['metadatas'], limit=AUTHOR_FETCH_BATCH_SIZE, offset=batch_offset)
        for meta in batch.get('metadatas') or []:
            if isinstance(meta, dict) and meta.get('author'):
                authors_set.add(meta['author'])
    return sorted(authors_set)


# --- ChromaDB Connection and Author Fetching ---
collection = None
unique_authors = []
try:
    os.makedirs(PROMPT_LOG_DIR, exist_ok=True)
    logging.info(f"Prompt log directory ensured at: {PROMPT_LOG_DIR}")
    _prune_prompt_logs()
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    total_count = collection.count()
    logging.info(f"Successfully connected to ChromaDB collection '{COLLECTION_NAME}'. Collection count: {total_count}")
    if total_count > 0:
        unique_authors = _load_cached_authors(total_count) or []
        if unique_authors:
            logging.info(f"Loaded {len(unique_authors)} unique authors from cache.")
        else:
            logging.info("Fetching all metadata to extract unique authors...")
            unique_authors = _scan_authors(total_count)
            if unique_authors:
                logging.info(f"Found {len(unique_authors)} unique authors.")
                _store_cached_authors(unique_authors, total_count)
            else:
                logging.warning("Could not retrieve metadata or no metadata found to extract authors.")
    else:
        logging.warning(f"Collection '{COLLECTION_NAME}' is empty. No authors to fetch.")
except Exception as e:
    logging.critical(f"FATAL: Could not connect to Chroma DB, fetch authors, or setup prompt dir: {e}", exc_info=True)
    unique_authors = [] # Ensure it's an empty list on error


# --- Gemini Generation Model Initialization ---
# The new google-genai SDK is client-based (no per-model object needed); we just
# record the model name here and call it via genai_client.models.generate_content().
llm_rerank_model = None
if genai_client:
    llm_rerank_model = LLM_RERANK_MODEL_NAME
    logging.info(f"Gemini LLM Re-Rank Model '{LLM_RERANK_MODEL_NAME}' initialized.")


# --- Embedding Function ---
# Only *successful* embeddings are cached. A plain lru_cache would memoise the
# None returned after a transient API error, so retyping the same query could
# never recover for the lifetime of the process.
_query_embedding_cache = {}
_query_embedding_cache_lock = threading.Lock()
QUERY_EMBEDDING_CACHE_SIZE = 1024


def get_embedding(text, task="RETRIEVAL_QUERY"):
    """Generates an embedding for the given text using the configured Gemini model."""
    if not genai_client:
        logging.error("Cannot generate embedding: API key not configured.")
        return None
    if not text or not isinstance(text, str) or not text.strip():
        return None

    valid_task_types = {"RETRIEVAL_QUERY", "RETRIEVAL_DOCUMENT", "SEMANTIC_SIMILARITY", "CLASSIFICATION", "CLUSTERING"}
    if task not in valid_task_types:
        logging.warning(f"Invalid task type '{task}' for embedding model. Defaulting to 'RETRIEVAL_QUERY'.")
        task = "RETRIEVAL_QUERY"

    cache_key = (text, task)
    with _query_embedding_cache_lock:
        cached = _query_embedding_cache.get(cache_key)
    if cached is not None:
        logging.debug(f"Embedding cache hit for '{text[:50]}...' (task={task}).")
        return cached

    try:
        logging.debug(f"Requesting embedding for text: '{text[:50]}...' with task: {task}")
        result = genai_client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=genai_types.EmbedContentConfig(task_type=task)
        )
        embedding = result.embeddings[0].values if result.embeddings else None
        if embedding:
            logging.debug(f"Embedding received. Type: {type(embedding)}, Length (if list): {len(embedding) if isinstance(embedding, list) else 'N/A'}")
            with _query_embedding_cache_lock:
                if len(_query_embedding_cache) >= QUERY_EMBEDDING_CACHE_SIZE:
                    _query_embedding_cache.pop(next(iter(_query_embedding_cache)), None)
                _query_embedding_cache[cache_key] = embedding
        else:
            logging.warning("Gemini API returned result without embeddings.")
        return embedding
    except Exception as e:
        logging.error(f"Error generating Gemini embedding for '{text[:50]}...': {e}", exc_info=True)
        if "resource has been exhausted" in str(e).lower():
            logging.error("Embedding failed likely due to quota exhaustion.")
        elif "api key not valid" in str(e).lower():
            logging.error("Embedding failed due to invalid API key.")
        return None

# --- Helper: Fetch Embeddings for Neighbor IDs ---
# Cached per individual sentence ID rather than per request. Keying an lru_cache on
# the whole ID tuple meant every entry held ~1200 x 3072 floats (~29 MB), and since
# the tuple was built from a set its ordering was unstable, so it almost never hit.
_neighbor_embedding_cache = {}
_neighbor_embedding_cache_lock = threading.Lock()


def fetch_embeddings_for_ids(ids_to_fetch):
    """Fetches embeddings for an iterable of passage IDs, using a per-ID memory cache."""
    if collection is None or not ids_to_fetch:
        return {}
    valid_ids = [str(id_val) for id_val in ids_to_fetch if id_val is not None]
    if not valid_ids:
        return {}

    embeddings_map = {}
    missing_ids = []
    with _neighbor_embedding_cache_lock:
        for id_val in valid_ids:
            cached = _neighbor_embedding_cache.get(id_val)
            if cached is not None:
                embeddings_map[id_val] = cached
            else:
                missing_ids.append(id_val)

    if not missing_ids:
        logging.debug(f"All {len(valid_ids)} neighbor embeddings served from cache.")
        return embeddings_map

    try:
        logging.debug(f"Fetching {len(missing_ids)} neighbor embeddings from DB ({len(valid_ids) - len(missing_ids)} cached).")
        results = collection.get(ids=missing_ids, include=['embeddings'])
        ids_list = results.get('ids')
        embeddings_list = results.get('embeddings')

        if ids_list is not None and embeddings_list is not None and len(ids_list) == len(embeddings_list):
            fetched = {}
            for i, fetched_id in enumerate(ids_list):
                if embeddings_list[i] is not None:
                    fetched[fetched_id] = embeddings_list[i]
                else:
                    logging.warning(f"Embedding for neighbor ID {fetched_id} was None in DB result.")
            embeddings_map.update(fetched)
            with _neighbor_embedding_cache_lock:
                # Simple bounded cache: clear wholesale rather than tracking recency,
                # since a single search re-reads the same neighborhood many times.
                if len(_neighbor_embedding_cache) + len(fetched) > NEIGHBOR_EMBEDDING_CACHE_SIZE:
                    logging.debug("Neighbor embedding cache full; clearing.")
                    _neighbor_embedding_cache.clear()
                _neighbor_embedding_cache.update(fetched)
        elif ids_list is not None or embeddings_list is not None:
             logging.error(f"Mismatch/Incomplete fetch for neighbor embeddings. Fetched IDs: {len(ids_list) if ids_list is not None else 'None'}, Embeddings: {len(embeddings_list) if embeddings_list is not None else 'None'} for {len(missing_ids)} requested IDs.")

    except Exception as e:
        logging.error(f"Error fetching neighbor embeddings for {len(missing_ids)} IDs: {e}", exc_info=True)
    return embeddings_map

# --- Helper: Fetch all sentences for a specific paragraph ---
def fetch_paragraph_data(author, book, paragraph_index):
    """Fetches all sentence data (doc, meta, embedding) for a specific paragraph."""
    logging.debug(f"Attempting fetch_paragraph_data: Author='{author}', Book='{book}', ParaIdx={paragraph_index}")
    if collection is None or author is None or book is None or paragraph_index is None or paragraph_index < 0:
        logging.warning(f"fetch_paragraph_data: Invalid arguments provided.")
        return []
    try:
        paragraph_index_int = int(paragraph_index) # Ensure integer for query
        results = collection.get(
            where={"$and": [{"author": author}, {"book": book}, {"paragraph_index": paragraph_index_int}]},
            include=['documents', 'metadatas', 'embeddings'] # Crucial: include embeddings for highlighting
        )

        if not results or not results.get('ids'):
            logging.debug(f"No sentences found for Author='{author}', Book='{book}', ParagraphIndex={paragraph_index_int}")
            return []

        paragraph_sentences = []
        num_results = len(results['ids'])
        documents_list = results.get('documents', [])
        metadatas_list = results.get('metadatas', [])
        embeddings_list = results.get('embeddings', [])

        if not (num_results == len(documents_list) == len(metadatas_list) == len(embeddings_list)):
            logging.warning(f"fetch_paragraph_data: Length mismatch in results for {author}/{book}/P{paragraph_index_int}. IDs:{num_results}, Docs:{len(documents_list)}, Metas:{len(metadatas_list)}, Embs:{len(embeddings_list)}. Clamping to minimum.")
            num_results = min(num_results, len(documents_list), len(metadatas_list), len(embeddings_list))

        for i in range(num_results):
            sent_id = results['ids'][i]
            meta = metadatas_list[i]
            doc = documents_list[i]
            emb = embeddings_list[i] # Get embedding

            if doc is None or emb is None: # Embedding needed for highlighting
                logging.warning(f"Skipping sentence {sent_id} in paragraph {paragraph_index_int} due to missing document or embedding.")
                continue

            entry = {'id': sent_id, 'doc': doc, 'meta': meta or {}, 'embedding': emb, 'paragraph_index': meta.get('paragraph_index', paragraph_index_int)}
            try:
                entry['sentence_sort_key'] = int(sent_id)
            except (ValueError, TypeError):
                entry['sentence_sort_key'] = float('inf') # Put unparsable IDs at the end
                logging.warning(f"Could not parse sentence ID as integer for sorting: {sent_id}")

            paragraph_sentences.append(entry)

        paragraph_sentences.sort(key=lambda x: x.get('sentence_sort_key', float('inf')))
        logging.debug(f"Fetched and sorted {len(paragraph_sentences)} sentences for paragraph {paragraph_index_int}.")
        return paragraph_sentences
    except Exception as e:
        logging.error(f"Error fetching paragraph data for Author='{author}', Book='{book}', ParagraphIndex={paragraph_index}: {e}", exc_info=True)
        return []

# --- Helper: Fetch Documents and Metadata for Multiple IDs ---
def fetch_multiple_passage_data(passage_ids):
    """Fetches documents and metadata for multiple passage IDs from ChromaDB."""
    if not passage_ids or collection is None:
        logging.warning(f"fetch_multiple_passage_data called with no IDs or no collection.")
        return {}

    passage_data_map = {}
    try:
        str_ids = [str(pid) for pid in passage_ids if pid is not None]
        if not str_ids: return {}

        logging.debug(f"Fetching passage data for {len(str_ids)} IDs: {str_ids[:10]}...")
        results = collection.get(ids=str_ids, include=['documents', 'metadatas'])

        if results and results.get('ids'):
            fetched_ids = results['ids']
            docs = results.get('documents', [])
            metas = results.get('metadatas', [])

            if not (len(fetched_ids) == len(docs) == len(metas)):
                 logging.error(f"Mismatch in lengths returned by collection.get for multiple IDs: {len(fetched_ids)} IDs, {len(docs)} docs, {len(metas)} metas. IDs requested: {str_ids}")
                 # Attempt to process based on shortest list? For now, proceed cautiously.

            id_to_index = {fid: i for i, fid in enumerate(fetched_ids)}
            # num_fetched = len(fetched_ids) # Unused after refactor

            for req_id in str_ids:
                if req_id in id_to_index:
                    idx = id_to_index[req_id]
                    # Check index bounds against potentially mismatched lists
                    doc = docs[idx] if idx < len(docs) and docs[idx] is not None else "_Text fehlt_"
                    meta = metas[idx] if idx < len(metas) and metas[idx] is not None else {}
                    passage_data_map[req_id] = {'doc': doc, 'meta': meta}
                    if doc == "_Text fehlt_": logging.warning(f"Missing document for fetched ID: {req_id}")
                    if not meta: logging.warning(f"Missing metadata for fetched ID: {req_id}")
                else:
                    logging.warning(f"Requested ID not found in collection.get results: {req_id}")

            missing_ids = set(str_ids) - set(passage_data_map.keys())
            if missing_ids:
                logging.warning(f"Could not find any data (doc/meta) for requested IDs: {missing_ids}")
        else:
            logging.warning(f"ChromaDB get returned no results or no IDs for requested list: {str_ids[:10]}...")

    except Exception as e:
        logging.error(f"Error fetching multiple passage data for IDs {passage_ids}: {e}", exc_info=True)
    return passage_data_map

# --- Helper: Calculate Cosine Similarity ---
def cosine_similarity_np(vec1, vec2):
    """Calculates cosine similarity between two vectors using NumPy."""
    if vec1 is None or vec2 is None:
        return 0.0
    try:
        vec1 = np.array(vec1, dtype=np.float32)
        vec2 = np.array(vec2, dtype=np.float32)
    except Exception as e:
        logging.error(f"Error converting vectors to numpy arrays for cosine similarity: {e}. vec1 type: {type(vec1)}, vec2 type: {type(vec2)}")
        return 0.0

    if vec1.shape != vec2.shape:
        if vec1.size > 0 and vec2.size > 0:
             logging.warning(f"Cosine similarity shape mismatch: {vec1.shape} vs {vec2.shape}")
        return 0.0
    if vec1.ndim == 0 or vec1.size == 0:
         return 0.0

    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    if norm1 == 0 or norm2 == 0:
         return 0.0

    epsilon = 1e-10 # Small value to prevent division by zero
    similarity = np.dot(vec1, vec2) / (norm1 * norm2 + epsilon)

    return float(np.clip(similarity, -1.0, 1.0))

# --- Helper: Compare Passage Metadata ---
def compare_passage_metadata(meta1, meta2):
    """Checks if two passages share the same author, book, section, and title metadata."""
    if not meta1 or not meta2: return False
    return all(meta1.get(key) == meta2.get(key) for key in ('author', 'book', 'section', 'title'))

# --- Favourite-helpers ---
def _load_favs() -> dict[str, int]:
    logging.debug(f"Attempting to load favourites from {FAV_FILE}")
    try:
        with open(FAV_FILE, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
            # Ensure IDs are strings and scores are integers
            favs = {str(k): int(v) for k, v in raw.items()}
            logging.debug(f"Successfully loaded {len(favs)} favourites.")
            return favs
    except FileNotFoundError:
        logging.debug(f"Favourites file not found at {FAV_FILE.strip()}. Starting with empty favourites.")
        return {}
    except Exception as e:
        logging.error(f"Could not read {FAV_FILE}: {e}", exc_info=True)
        return {}

def _save_favs() -> None:
    logging.debug(f"Attempting to save favourites to {FAV_FILE}")
    tmp = FAV_FILE + ".tmp"

    try:
        # This code is now directly executed when _save_favs() is called.
        # It relies on the CALLER (e.g., inc_favourite) holding the lock.
        with open(tmp, "w", encoding="utf-8") as fh:
            logging.debug(f"Opened temp file {tmp} for writing.")
            json.dump(favourite_scores, fh, ensure_ascii=False, indent=2)
            logging.debug("Dumped favourites to temp file.")
            fh.flush()
            logging.debug("Flushed temp file.")
            os.fsync(fh.fileno()) # Force write to disk
            logging.debug("Synced temp file.")
        # logging.debug(f"Closed temp file {tmp}.") # This line is now after the 'with open' block
        os.replace(tmp, FAV_FILE) # Atomic replace
        logging.debug(f"Successfully replaced {FAV_FILE} with temp file.")
        logging.debug(f"Successfully saved {len(favourite_scores)} favourites.")
    except Exception as e:
        logging.error(f"Could not save {FAV_FILE}: {e}", exc_info=True)

favourite_scores: dict[str, int] = _load_favs() # Load favourites on startup

def inc_favourite(passage_id: str) -> int:
    """Add one ⭐ to a sentence, persist, return new total."""
    logging.info(f"Attempting to increment favourite for ID: {passage_id}")
    if not passage_id or not isinstance(passage_id, str):
        logging.warning(f"Invalid passage_id for inc_favourite: {passage_id}")
        return 0
    with _fav_lock:
        # Ensure ID is treated as string key
        str_passage_id = str(passage_id)
        favourite_scores[str_passage_id] = favourite_scores.get(str_passage_id, 0) + 1
        _save_favs()
        new_score = favourite_scores[str_passage_id]
        logging.info(f"Incremented favourite for ID {str_passage_id}. New score: {new_score}")
    return new_score

def top_favourites(n: int = MAX_FAVOURITES) -> list[dict]:
    """Return N top‑scored sentences incl. doc/meta."""
    logging.debug(f"Fetching top {n} favourites.")
    if not favourite_scores:
        logging.debug("No favourites available.")
        return []
    try:
        # Sort items, convert keys to str explicitly just in case
        top = sorted([(str(k), v) for k, v in favourite_scores.items()], key=lambda kv: kv[1], reverse=True)[:n]
        ids = [sid for sid, _ in top]
        logging.debug(f"Top {len(top)} favourite IDs: {ids}")
        data = fetch_multiple_passage_data(ids) # Fetch document and metadata
        logging.debug(f"Fetched data for {len(data)} favourite IDs.")
        results = []
        for sid, score in top:
            if sid not in data:
                logging.warning(f"Could not retrieve data for favourite ID {sid}. Skipping.")
                continue
            entry = {
                "id": sid, # The ID
                "document": data[sid]["doc"], # The text
                "metadata": data[sid]["meta"], # The metadata
                "distance": 0.0, # Favourites don't have a semantic distance in this view
                "favourite_score": score, # The favourite score
            }
            results.append(entry)
        logging.debug(f"Prepared {len(results)} top favourite results.")
        return results
    except Exception as e:
        logging.error(f"Error fetching top favourites: {e}", exc_info=True)
        return []

# --- Combined Formatting Function for all result types (Standard, LLM, Favourites) ---
def format_result_display(result_data, index, total_results, result_type):
    """Formats a single search, LLM, or favourite result for Accordion/Textbox display."""
    if not result_data or not isinstance(result_data, dict):
        # Must stay a 3-tuple: every call site unpacks title, metadata and text.
        return "Keine Ergebnisdaten verfügbar.", "", ""

    metadata = result_data.get('metadata', {})

    # Determine what text to display and its label
    # Favourites might have 'document', Standard/LLM might have 'context_block' or 'edited_text'
    display_text = result_data.get('edited_text', result_data.get('context_block', result_data.get('document', "_Text fehlt_")))

    # Determine what ID label to use
    # Prioritize original_id (LLM), then id (standard search/context/fav), then fallback
    result_id = result_data.get('original_id', result_data.get('id', 'N/A'))

    # --- Construct the Accordion Heading ---
    accordion_title = ""
    if result_type == "llm":
        accordion_title = f"{index + 1} von {total_results}"
    elif result_type == "standard":
         accordion_title = f"{index + 1} von {total_results}"
    elif result_type == "favourites":
        score = result_data.get('favourite_score', 0)
        accordion_title = f"⭐{score}" # Title is just the star score

    # --- Construct the Accordion Content (Metadata & Scores) ---
    accordion_content_md = ""

    score_info_lines = []
    # Favourite score is already in title for favs, only show for standard/LLM if present
    if 'favourite_score' in result_data and result_data['favourite_score'] is not None:
         if result_type != "favourites":
             score_info_lines.append(f"* ⭐ Score: {result_data['favourite_score']}")
    if 'final_similarity' in result_data and result_data['final_similarity'] is not None:
         score_info_lines.append(f"* Score (Kontext-Gewichtet): {result_data['final_similarity']:.4f}")


    score_info = "\n".join(score_info_lines) + "\n\n" if score_info_lines else "\n"

    author = metadata.get('author', 'N/A')
    book = metadata.get('book', 'N/A')
    section = metadata.get('section', None)
    titel = metadata.get('title', None)

    accordion_content_md += f"* Autor: {author}\n* Buch: {book}\n"
    if section and str(section).strip().lower() not in ["unknown", "n/a", ""]:
         accordion_content_md += f"* Abschnitt: {section}\n"
    if titel is not None and str(titel).strip().lower() not in ["unknown", "n/a", ""]:
         try: accordion_content_md += f"* Titel/Nr: {int(titel)}\n"
         except (ValueError, TypeError): accordion_content_md += f"* Titel/Nr: {titel}\n"

    accordion_content_md += score_info

    # --- ADDED: Include LLM Rationale if available and this is an LLM result ---
    # Check for both result_type and the presence of the 'rationale' key
    if result_type == "llm" and 'rationale' in result_data and result_data['rationale']:
         accordion_content_md += f"**LLM Begründung:**\n> {result_data['rationale']}\n\n"
    # --- END ADDED ---

    # The LLM's excerpt could not be matched against the stored text, so the full
    # original passage is shown instead. Say so rather than passing it off as an excerpt.
    if result_type == "llm" and not result_data.get('excerpt_verified', True):
         accordion_content_md += ("_Hinweis: Der vom LLM gekürzte Text stimmte nicht wörtlich mit der Quelle "
                                  "überein. Angezeigt wird die unveränderte Originalpassage._\n\n")


    # The text content for the Textbox is just the display_text
    text_content = display_text

    # Return the two separate parts
    return accordion_title, accordion_content_md, text_content

# --- Helper: Author Diversity Quota ---
def _apply_author_quota(ranked_results, quota, target_n_results=None):
    """Re-orders a ranked list so that no single author dominates the top of it.

    A first pass walks the list in rank order and keeps at most `quota` results per
    author. If that leaves fewer than `target_n_results`, the results the quota skipped
    are appended afterwards, still in rank order, until the target is filled.

    The quota is therefore soft: it decides *which* results come first, but never
    shortens the list below what the ranking can supply. A hard quota silently deleted
    results instead of diversifying them -- the corpus is roughly half Nietzsche, so a
    search restricted to one author returned 3 hits out of 20 requested, and the LLM's
    ten ranked passages were routinely cut to five. A falsy or non-positive quota
    disables the filter entirely.
    """
    if not ranked_results:
        return []
    if not quota or quota <= 0:
        return ranked_results[:target_n_results] if target_n_results else ranked_results

    author_counts = defaultdict(int)
    kept = []
    overflow = []  # Passed over by the quota; used to fill the page back up.
    for candidate in ranked_results:
        if target_n_results is not None and len(kept) >= target_n_results:
            logging.debug(f"Reached target result count {target_n_results}. Stopping quota application.")
            break
        # Use author 'Unknown' if metadata or author key is missing
        author = (candidate.get('metadata') or {}).get('author', 'Unknown')
        if author_counts[author] < quota:
            kept.append(candidate)
            author_counts[author] += 1
        else:
            overflow.append(candidate)

    kept_authors = sum(1 for count in author_counts.values() if count > 0)
    logging.info(f"Quota applied (max {quota}/author). Selected {len(kept)} of {len(ranked_results)} results "
                 f"from {kept_authors} unique authors.")

    if target_n_results is not None and len(kept) < target_n_results and overflow:
        backfill = overflow[:target_n_results - len(kept)]
        logging.info(f"Quota left only {len(kept)} of {target_n_results} requested results; "
                     f"backfilling {len(backfill)} more in rank order.")
        kept.extend(backfill)

    return kept


# --- Contextual Re-ranking Function (V5) ---
def rerank_with_context(candidates, original_query_embedding, target_n_results, weight, decay_factor,
                        window_size, min_chars_neighbor, author_quota=MAX_RESULTS_PER_AUTHOR):
    """
    Re-ranks candidate passages by blending each passage's own similarity to the query
    with the similarity of its surrounding sentences, collapses candidates whose context
    windows overlap, and optionally applies an author quota for diversity.

    Both score components are raw cosine similarities on the same scale, so they are
    combined directly. Earlier versions min-max normalized each component across the
    candidate pool, which discarded absolute quality (the worst candidate always scored
    0.0, the best always 1.0) and made the ranking depend on how many candidates were
    fetched. Pass author_quota=None to disable the diversity filter.
    """
    logging.info(f"Starting contextual re-ranking (V5: Raw+WindowDeDup+Quota) for {len(candidates)} candidates... "
                 f"(Win={window_size}, Weight={weight:.2f}, Decay={decay_factor:.2f}, MinChars={min_chars_neighbor}, AuthQuota={author_quota})")
    if not candidates or original_query_embedding is None:
        logging.warning("rerank_with_context called with no candidates or no query embedding.")
        return candidates[:target_n_results] if candidates else []

    # --- Phase 1: Calculate Initial Similarities ---
    processed_candidates_phase1 = []
    logging.debug("Phase 1: Calculating initial similarities...")
    for candidate in candidates:
        initial_distance = candidate.get('distance')
        if initial_distance is None or not isinstance(initial_distance, (float, int)) or initial_distance < 0:
            initial_similarity = 0.0
        else:
            # Collection uses cosine space, so similarity = 1 - distance.
            initial_similarity = max(0.0, 1.0 - float(initial_distance))
        candidate['initial_similarity'] = initial_similarity
        processed_candidates_phase1.append(candidate)

    # --- Phase 2: Calculate Combined Neighbor Similarities ---
    passage_data_map = {str(cand['id']): {'doc': cand.get('document'), 'meta': cand.get('metadata', {})} for cand in processed_candidates_phase1}
    neighbor_embeddings_cache = {}
    all_neighbor_ids_to_fetch = set()
    candidate_neighbor_map = defaultdict(lambda: {'prev': [], 'next': []})
    potential_neighbor_distances = {}

    # Pass 2.1: Identify neighbors
    for candidate in processed_candidates_phase1:
        try:
            center_id_str = str(candidate['id'])
            center_id_int = int(center_id_str)
            potential_neighbor_distances[center_id_str] = {}
            for dist in range(1, window_size + 1):
                prev_id_int, next_id_int = center_id_int - dist, center_id_int + dist
                if prev_id_int >= 0:
                    prev_id_str = str(prev_id_int); all_neighbor_ids_to_fetch.add(prev_id_str); candidate_neighbor_map[center_id_str]['prev'].append(prev_id_str); potential_neighbor_distances[center_id_str][prev_id_str] = dist
                next_id_str = str(next_id_int); all_neighbor_ids_to_fetch.add(next_id_str); candidate_neighbor_map[center_id_str]['next'].append(next_id_str); potential_neighbor_distances[center_id_str][next_id_str] = dist
            candidate_neighbor_map[center_id_str]['prev'].sort(key=int, reverse=True)
            candidate_neighbor_map[center_id_str]['next'].sort(key=int)
        except (ValueError, TypeError):
            logging.warning(f"Could not parse candidate ID {candidate.get('id')} as integer for neighbor finding.")
            continue

    # Pass 2.2: Fetch neighbor data (embeddings, docs, metas)
    ids_needed_for_fetch = list(all_neighbor_ids_to_fetch)
    if ids_needed_for_fetch:
        fetched_embeddings = fetch_embeddings_for_ids(ids_needed_for_fetch); neighbor_embeddings_cache.update(fetched_embeddings)
        ids_to_fetch_docs_meta = [nid for nid in ids_needed_for_fetch if nid not in passage_data_map]
        if ids_to_fetch_docs_meta:
             fetched_neighbor_docs_meta = fetch_multiple_passage_data(ids_to_fetch_docs_meta); passage_data_map.update(fetched_neighbor_docs_meta)


    # Pass 2.3: Calculate combined similarity per candidate and construct context block
    scored_candidates = []
    no_neighbor_count = 0
    logging.debug("Phase 2: Calculating combined neighbor similarities and constructing context blocks...")
    for candidate in processed_candidates_phase1:
        try:
            center_id_str = str(candidate['id'])
            center_meta = candidate.get('metadata', {})
            total_weighted_similarity = 0.0
            total_weight = 0.0
            candidate_neighbors_dist = potential_neighbor_distances.get(center_id_str, {})

            # Calculate weighted neighbor similarity
            for neighbor_id_str, dist_level in candidate_neighbors_dist.items():
                neighbor_emb = neighbor_embeddings_cache.get(neighbor_id_str)
                neighbor_data = passage_data_map.get(neighbor_id_str)
                if neighbor_emb is not None and neighbor_data:
                    neighbor_meta = neighbor_data.get('meta')
                    neighbor_doc = neighbor_data.get('doc')
                    if (neighbor_meta is not None and compare_passage_metadata(center_meta, neighbor_meta)
                        and neighbor_doc and isinstance(neighbor_doc, str) and len(neighbor_doc) >= min_chars_neighbor):
                        neighbor_sim_to_query = cosine_similarity_np(original_query_embedding, neighbor_emb)
                        current_decay = max(0.0, 1.0 - ((dist_level - 1) * decay_factor))
                        current_weight = current_decay # Weight by decayed distance
                        total_weighted_similarity += neighbor_sim_to_query * current_weight
                        total_weight += current_weight

            if total_weight > 0:
                combined_sim = total_weighted_similarity / total_weight
            else:
                # A passage at the start or end of a section has no usable neighbors.
                # Falling back to 0.0 used to punish it by up to `weight` of the final
                # score; falling back to its own similarity makes the context term a
                # no-op instead, which is what "no context evidence" should mean.
                combined_sim = candidate['initial_similarity']
                no_neighbor_count += 1

            candidate['combined_neighbor_similarity'] = combined_sim
            candidate['context_evidence_weight'] = total_weight

            # Construct context block for this candidate using ALL neighbors (even short ones)
            context_block_text = _construct_passage_block(center_id_str, passage_data_map, candidate_neighbor_map)
            candidate['context_block'] = context_block_text

            scored_candidates.append(candidate)
        except Exception as e:
            logging.error(f"Error processing candidate ID {candidate.get('id')} during neighbor scoring/context block: {e}", exc_info=True)
            candidate['combined_neighbor_similarity'] = candidate.get('initial_similarity', 0.0)
            candidate['context_evidence_weight'] = 0.0
            candidate['context_block'] = "_Fehler bei Kontext-Erstellung_"
            scored_candidates.append(candidate)

    if no_neighbor_count:
        logging.debug(f"{no_neighbor_count} candidates had no usable neighbors; context term fell back to their own similarity.")


    # --- Phase 3: Combine Scores (raw cosine, no pool normalization) ---
    logging.debug("Phase 3: Combining initial and context similarities...")
    for candidate in scored_candidates:
        try:
            initial_sim = candidate.get('initial_similarity', 0.0)
            combined_sim = candidate.get('combined_neighbor_similarity', initial_sim)
            evidence = candidate.get('context_evidence_weight', 0.0)

            # Shrink the context term toward the passage's own similarity when it rests
            # on thin evidence, so one lucky neighbor cannot outrank four consistent ones.
            confidence = min(1.0, evidence / RERANK_FULL_EVIDENCE_WEIGHT) if RERANK_FULL_EVIDENCE_WEIGHT > 0 else 1.0
            context_term = confidence * combined_sim + (1.0 - confidence) * initial_sim

            candidate['final_similarity'] = (1.0 - weight) * initial_sim + weight * context_term

        except Exception as e:
            logging.error(f"Error calculating final similarity for candidate ID {candidate.get('id')}: {e}", exc_info=True)
            candidate['final_similarity'] = -1.0 # Penalize on error


    # --- Phase 4: Sort by Score ---
    scored_candidates.sort(key=lambda x: x.get('final_similarity', -1.0), reverse=True)
    logging.debug(f"Sorted {len(scored_candidates)} candidates by combined score.")


    # --- Phase 5: Collapse Overlapping Context Windows ---
    # Candidates come from a single vector query, so their IDs are unique by
    # construction; de-duplicating by ID (as earlier versions did) never merged
    # anything. What actually produces redundant results is two hits a sentence or
    # two apart, whose context blocks are nearly the same text. Walking the list in
    # score order and dropping any candidate that sits inside an already-kept
    # candidate's context window keeps the better of each such pair.
    logging.debug("Phase 5: Collapsing candidates with overlapping context windows...")
    kept_windows = defaultdict(list) # (author, book, section, title) -> [kept center ids]
    unique_best_candidates = []
    for candidate in scored_candidates:
        center_id = candidate.get('id')
        if not center_id:
            logging.warning(f"Skipping candidate with missing ID: {candidate}")
            continue
        try:
            center_id_int = int(str(center_id))
        except (ValueError, TypeError):
            # Unparsable ID: cannot reason about overlap, so keep it.
            unique_best_candidates.append(candidate)
            continue

        meta = candidate.get('metadata', {}) or {}
        doc_key = (meta.get('author'), meta.get('book'), meta.get('section'), meta.get('title'))
        if any(abs(center_id_int - kept_id) <= window_size for kept_id in kept_windows[doc_key]):
            logging.debug(f"Dropping candidate {center_id}: window overlaps a higher-scoring result.")
            continue
        kept_windows[doc_key].append(center_id_int)
        unique_best_candidates.append(candidate)

    logging.info(f"Reduced {len(scored_candidates)} candidates to {len(unique_best_candidates)} non-overlapping passages.")


    # --- Phase 6: Apply Author Quota ---
    logging.debug(f"Phase 6: Applying author quota (max {author_quota} per author)...")
    return _apply_author_quota(unique_best_candidates, author_quota, target_n_results)

# --- Modified Format Context for Reading Area (Revision 6 - HTML Output) ---
def format_context_markdown(passages_state_list, query_embedding):
    """Formats a list of paragraph sentences for HTML display with dynamic highlighting.
       Uses class/data-id for JS event listeners."""
    logging.info(f"Formatting context HTML for {len(passages_state_list)} passages.")

    # --- Validate Query Embedding (same) ---
    is_query_embedding_valid = False
    query_embedding_np = None
    if isinstance(query_embedding, (list, np.ndarray)):
        try:
            query_embedding_np = np.array(query_embedding, dtype=np.float32)
            if query_embedding_np.ndim == 1 and query_embedding_np.size > 0:
                 is_query_embedding_valid = True
                 logging.debug(f"Query embedding is valid (Shape: {query_embedding_np.shape}). Highlighting enabled.")
            else: logging.warning("Query embedding received but is empty or has wrong dimensions. Highlighting disabled.")
        except Exception as e:
            logging.error(f"Error converting or checking query embedding: {e}. Highlighting disabled.")
    else: logging.warning(f"Query embedding is type {type(query_embedding)}. Highlighting disabled.")

    if not passages_state_list:
        return "<div>_Kein Kontext zum Anzeigen._</div>" # Return valid HTML

    # Sort BEFORE scoring. The similarity scores below are keyed by position in this
    # list and read back by position further down, so re-ordering the list in between
    # would hand each sentence its neighbour's highlight. Sorting into a local copy also
    # keeps this function from mutating the caller's gr.State list as a side effect.
    passages_state_list = sorted(
        passages_state_list,
        key=lambda x: (x.get('paragraph_index', -1), x.get('sentence_sort_key', float('inf')))
    )

    # --- Step 1: Calculate all similarities and find relevant range (same) ---
    sentence_similarities = {}
    scores_above_threshold = []
    if is_query_embedding_valid:
        logging.debug("Calculating similarities for dynamic highlighting...")
        for i, sentence_data in enumerate(passages_state_list):
            sentence_embedding = sentence_data.get('embedding')
            sentence_id = sentence_data.get('id', f'index_{i}') # Use index if ID missing
            sentence_role = sentence_data.get('role', 'context')

            # Skip markers or sentences without embeddings
            if sentence_role == 'missing' or sentence_embedding is None:
                continue

            try:
                similarity_score = cosine_similarity_np(query_embedding_np, sentence_embedding)
                sentence_similarities[i] = similarity_score # Store score by index
                if similarity_score >= HIGHLIGHT_SIMILARITY_THRESHOLD:
                    scores_above_threshold.append(similarity_score)
            except Exception as e:
                logging.warning(f"Error calculating similarity for sentence ID {sentence_id} (Index {i}): {e}")

    max_relevant_score = -1.0
    min_relevant_score = HIGHLIGHT_SIMILARITY_THRESHOLD
    if scores_above_threshold:
        max_relevant_score = max(scores_above_threshold)
        logging.debug(f"Dynamic Highlighting: Min Relevant Score (Threshold) = {min_relevant_score:.4f}, Max Relevant Score = {max_relevant_score:.4f}")
    else:
        logging.debug("Dynamic Highlighting: No sentences met the similarity threshold.")

    # --- Step 2: Format output as HTML ---
    # (already sorted above, before the similarities were computed)

    output_parts = []
    current_paragraph_index = None
    previous_section = "__INITIAL_NONE__"
    previous_title = "__INITIAL_NONE__"
    is_first_paragraph_overall = True
    PLACEHOLDERS_TO_IGNORE = {"unknown", "n/a", "", None}
    is_paragraph_open = False # Track if we need to close a <p> tag

    for i, sentence_data in enumerate(passages_state_list):
        sentence_doc = sentence_data.get('doc', '_Text fehlt_')
        sentence_meta = sentence_data.get('meta', {})
        sentence_para_idx = sentence_data.get('paragraph_index')
        sentence_role = sentence_data.get('role', 'context')
        sentence_id = sentence_data.get('id', f'index_{i}')


        # --- Handle boundary markers (as HTML) ---
        if sentence_role == 'missing':
            if is_paragraph_open:
                output_parts.append("</p>\n") # Close previous paragraph
                is_paragraph_open = False
            output_parts.append(f"<p><em>{html.escape(sentence_doc)}</em></p>\n") # Use <em> for italics
            current_paragraph_index = None
            is_first_paragraph_overall = True
            # No need for extra newlines between markers in HTML, <p> handles blocks
            # if i < len(passages_state_list) - 1: output_parts.append("<br><br>") # Optional: explicit vertical space
            continue

        # --- Check for Paragraph Start and Handle Headings/Separators (as HTML) ---
        is_new_paragraph = (sentence_para_idx is not None and sentence_para_idx != current_paragraph_index)
        if is_new_paragraph:
             if is_paragraph_open:
                 output_parts.append("</p>\n") # Close previous paragraph
                 is_paragraph_open = False

             current_section = sentence_meta.get('section')
             current_title = sentence_meta.get('title')

             norm_prev_section = None if str(previous_section).strip().lower() in PLACEHOLDERS_TO_IGNORE else previous_section
             norm_prev_title = None if str(previous_title).strip().lower() in PLACEHOLDERS_TO_IGNORE else previous_title
             norm_curr_section = None if str(current_section).strip().lower() in PLACEHOLDERS_TO_IGNORE else current_section
             norm_curr_title = None if str(current_title).strip().lower() in PLACEHOLDERS_TO_IGNORE else current_title

             section_changed = (norm_curr_section != norm_prev_section)
             title_changed = (norm_curr_title != norm_prev_title)

             # --- REMOVED/COMMENTED OUT: This is where the <hr> was added ---
             # if not is_first_paragraph_overall:
             #     if section_changed or title_changed:
             #         output_parts.append("<hr>\n") # Use <hr> for separator
             # --- END REMOVED/COMMENTED OUT ---


             heading_parts_to_add = []
             if section_changed and norm_curr_section is not None:
                 heading_parts_to_add.append(f"<h3>{html.escape(str(norm_curr_section))}</h3>\n") # Use <h3>
             if title_changed and norm_curr_title is not None:
                 title_str = str(norm_curr_title).strip()
                 title_display = html.escape(title_str)
                 try: title_display = html.escape(str(int(title_str))) # Attempt int cast if relevant
                 except (ValueError, TypeError): pass # Keep string if not int
                 heading_parts_to_add.append(f"<h4>{title_display}</h4>\n") # Use <h4>


             if heading_parts_to_add:
                 output_parts.extend(heading_parts_to_add)

             output_parts.append("<p>") # Open new paragraph tag
             is_paragraph_open = True

             previous_section = current_section
             previous_title = current_title
             current_paragraph_index = sentence_para_idx
             is_first_paragraph_overall = False
        elif not is_paragraph_open:
             # Handle case where first item is not a paragraph start marker
             output_parts.append("<p>")
             is_paragraph_open = True


        # --- Sentence Formatting and DYNAMIC Highlighting (as HTML Spans) ---
        # Build attributes for the SINGLE span element
        span_classes = ["clickable-sentence"]
        # Use inline style for cursor:pointer for simplicity, although CSS is also fine
        # style_parts = ["cursor:pointer;"] # <-- Moved cursor to CSS
        style_parts = []

        safe_doc = html.escape(sentence_doc)


        current_score = sentence_similarities.get(i)

        # Determine if highlighting should be applied
        apply_highlight = is_query_embedding_valid and current_score is not None and current_score >= min_relevant_score
        alpha = 0.0
        if apply_highlight:
            try:
                 if max_relevant_score > min_relevant_score:
                     normalized_score = (current_score - min_relevant_score) / (max_relevant_score - min_relevant_score)
                     alpha = HIGHLIGHT_MIN_ALPHA + normalized_score * (HIGHLIGHT_MAX_ALPHA - HIGHLIGHT_MIN_ALPHA)
                     alpha = max(HIGHLIGHT_MIN_ALPHA, min(alpha, HIGHLIGHT_MAX_ALPHA))
                 elif max_relevant_score == min_relevant_score:
                     alpha = HIGHLIGHT_MIN_ALPHA

            except Exception as e:
                 logging.warning(f"Error calculating dynamic highlighting alpha for sentence ID {sentence_id}: {e}")
                 alpha = 0.0 # Disable highlighting on error

        # Apply highlighting by adding the class and style properties (including the CSS variable)
        if alpha > 0:
             span_classes.append("highlighted")
             # Add dynamic styles (padding, border-radius, box-decoration-break) to style_parts
             style_parts.append("padding: 1px 3px;")
             style_parts.append("border-radius: 3px;")
             style_parts.append("box-decoration-break: clone;")
             style_parts.append("-webkit-box-decoration-break: clone;")
             # Set the CSS variable for the alpha
             style_parts.append(f"--highlight-alpha: {alpha:.2f};")
             # DO NOT set background-color here - it's set in CSS using the variable


        # Join the classes and styles
        class_str = " ".join(span_classes)
        style_str = " ".join(style_parts)

        # Construct the single span element
        # ADDED cursor: pointer to CSS, removed from inline style below
        formatted_sentence = (
             f'<span class="{class_str}" data-id="{sentence_id}" style="{style_str}">'
             f"{safe_doc}</span>"
         )


        # --- Append Formatted Sentence with Spacing (handle HTML spaces) ---
        # Add a space before if not the first sentence in the paragraph
        if not is_new_paragraph and is_paragraph_open and i > 0 and passages_state_list[i-1].get('role') != 'missing' and sentence_role != 'missing':
             # Find the previous non-missing sentence to check if it was the end of a paragraph block
             prev_valid_sentence_index = i - 1
             while prev_valid_sentence_index >= 0 and passages_state_list[prev_valid_sentence_index].get('role') == 'missing':
                 prev_valid_sentence_index -= 1

             # Add a space unless the previous element was a heading, hr, or paragraph open tag
             # This check is implicitly handled by the is_new_paragraph logic and checking if is_paragraph_open.
             # If it's not a new paragraph and the paragraph is open, we generally want a space.
             if prev_valid_sentence_index >= 0 and passages_state_list[prev_valid_sentence_index].get('paragraph_index') == sentence_para_idx:
                 output_parts.append(" ")
             # No space needed if it's the very first item in a paragraph after a break/heading


        output_parts.append(formatted_sentence)


    # Close the last paragraph tag if it was opened
    if is_paragraph_open:
         output_parts.append("</p>\n")


    # Wrap everything in a main div for robustness
    return "<div>\n" + "".join(output_parts) + "</div>"

# --- Internal Search Helper ---
def _perform_single_query_search(query, where_filter, n_results, query_embedding=None):
    """Performs a single vector query against ChromaDB, returning processed results.

    `query_embedding` may be supplied by the caller to avoid re-embedding a query that
    has already been embedded; it is only computed here when omitted.
    """
    logging.info(f"Performing single query search for: '{query[:50]}...' (n_results={n_results}, filter={where_filter})")
    if collection is None:
        logging.error("ChromaDB collection is not available for query.")
        raise ConnectionError("DB not available.")
    if not query:
        logging.error("Cannot perform search with an empty query.")
        return [] # Return empty list for empty query

    if query_embedding is None:
        query_embedding = get_embedding(query, task="RETRIEVAL_QUERY")
        logging.debug(f"Inside _perform_single_query_search: Generated query embedding. Is None: {query_embedding is None}")

    if query_embedding is None:
        # Embedding failed, cannot proceed with query
        raise ValueError(f"Embedding generation failed for query: '{query[:50]}...'")

    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where_filter, # Apply filter if provided
            include=['documents', 'metadatas', 'distances'] # Fetch necessary fields
        )

        processed_results = []
        # Results structure: {'ids': [[]], 'documents': [[]], ...}
        # Check if results and the first list within 'ids' exist and are not empty
        if results and results.get('ids') and results['ids'] and results['ids'][0]:
            # Extract the lists for the single query
            ids_list = results['ids'][0]
            docs_list = results.get('documents', [[]])[0] or [] # Use default empty list
            metadatas_list = results.get('metadatas', [[]])[0] or []
            distances_list = results.get('distances', [[]])[0] or []

            num_found = len(ids_list)
            # Robustness check on list lengths
            if not (num_found == len(docs_list) == len(metadatas_list) == len(distances_list)):
                logging.warning(f"ChromaDB result length mismatch: {num_found} IDs, {len(docs_list)} docs, {len(metadatas_list)} metas, {len(distances_list)} dists. Processing cautiously.")
                num_found = min(num_found, len(docs_list), len(metadatas_list), len(distances_list))
                ids_list = ids_list[:num_found] # Truncate lists to match


            logging.info(f"ChromaDB query returned {len(ids_list)} results.")

            for i, res_id in enumerate(ids_list):
                # Check bounds just in case, though clamping should prevent IndexError
                if i >= num_found: break
                doc = docs_list[i] if docs_list[i] is not None else "_Text fehlt_"
                meta = metadatas_list[i] if metadatas_list[i] is not None else {}
                dist = distances_list[i] if distances_list[i] is not None else float('inf')

                # Basic validation
                if res_id is None: logging.warning(f"Skipping result with None ID at index {i}"); continue
                res_id_str = str(res_id) # Ensure ID is string
                if doc == "_Text fehlt_": logging.warning(f"Missing document for ID {res_id_str} at index {i}")
                if dist == float('inf'): logging.warning(f"Missing distance for ID {res_id_str} at index {i}")

                processed_results.append({
                    "id": res_id_str, # Store ID as string
                    "document": doc,
                    "metadata": meta,
                    "distance": dist
                })
        else:
            logging.info(f"Query '{query[:50]}...' returned no results from ChromaDB.")
        return processed_results

    except Exception as e:
        logging.error(f"Error during ChromaDB query for '{query[:50]}...': {e}", exc_info=True)
        if "dimension" in str(e).lower():
            logging.error("Query failed possibly due to embedding dimension mismatch.")
            raise ValueError(f"Dimension mismatch error for query '{query[:50]}...'")
        raise RuntimeError(f"DB search error for query '{query[:50]}...': {type(e).__name__}")

# --- Helper: Verify an LLM excerpt against its source ---
def _normalize_with_offsets(text):
    """Collapses runs of whitespace to single spaces, returning the normalized string
       and, for each normalized character, its offset in the original text."""
    normalized_chars = []
    offsets = []
    prev_was_space = True # also strips leading whitespace
    for idx, char in enumerate(text):
        if char.isspace():
            if prev_was_space:
                continue
            normalized_chars.append(' ')
            offsets.append(idx)
            prev_was_space = True
        else:
            normalized_chars.append(char)
            offsets.append(idx)
            prev_was_space = False
    while normalized_chars and normalized_chars[-1] == ' ':
        normalized_chars.pop()
        offsets.pop()
    return ''.join(normalized_chars), offsets


def _verify_excerpt(excerpt, source_block):
    """Checks that an LLM-produced excerpt really occurs in its source passage.

    Returns (text_to_display, was_faithful). Differences in whitespace are tolerated,
    and on a match the corresponding slice of the *source* is returned so the displayed
    quotation is byte-identical to the stored text. When the excerpt cannot be located
    the full source block is returned instead, so the user never sees an altered quote.
    """
    if not source_block or not isinstance(source_block, str):
        # Nothing to check against; surface the excerpt but mark it unverified.
        return excerpt, False

    norm_excerpt, _ = _normalize_with_offsets(excerpt)
    norm_source, source_offsets = _normalize_with_offsets(source_block)
    if not norm_excerpt:
        return source_block, False

    position = norm_source.find(norm_excerpt)
    if position == -1:
        return source_block, False

    start = source_offsets[position]
    end = source_offsets[position + len(norm_excerpt) - 1] + 1
    return source_block[start:end], True


# --- Helper Function: Construct Passage Block ---
def _construct_passage_block(center_id_str, passage_data_map, candidate_neighbor_map):
    """Constructs a continuous text block including neighbors for a given center passage."""
    center_data = passage_data_map.get(center_id_str)
    if not center_data:
        logging.warning(f"_construct_passage_block: Missing data for center ID {center_id_str}.")
        return "_Zentrumstext fehlt_"

    center_meta = center_data.get('meta', {})
    center_text = center_data.get('doc')
    if not center_text or center_text == "_Text fehlt_":
        logging.warning(f"_construct_passage_block: Missing document text for center ID {center_id_str}.")
        return "_Zentrumstext fehlt_"

    block_text_parts = []
    neighbors = candidate_neighbor_map.get(center_id_str, {'prev': [], 'next': []})

    # Add previous neighbors (if metadata matches) - Iterate in original order (closest first) and insert at beginning
    # Note: Sorting neighbors.get('prev', []) by int() ensures chronological order
    for prev_id in sorted(neighbors.get('prev', []), key=int):
        prev_data = passage_data_map.get(prev_id)
        if prev_data and compare_passage_metadata(center_meta, prev_data.get('meta', {})):
            prev_text = prev_data.get('doc')
            if prev_text and prev_text != "_Text fehlt_":
                block_text_parts.append(prev_text) # Add to the end temporarily

    # Add the center text
    block_text_parts.append(center_text)

    # Add next neighbors (if metadata matches) - Iterate in original order (closest first) and append
    for next_id in sorted(neighbors.get('next', []), key=int):
        next_data = passage_data_map.get(next_id)
        if next_data and compare_passage_metadata(center_meta, next_data.get('meta', {})):
            next_text = next_data.get('doc')
            if next_text and next_text != "_Text fehlt_":
                block_text_parts.append(next_text) # Add to the end

    # Join the parts into a single string for the block
    continuous_block_text = " ".join(block_text_parts)

    if not continuous_block_text.strip():
        logging.warning(f"_construct_passage_block: Constructed empty passage block for center ID {center_id_str}.")
        return "_Leerer Kontextblock_"

    return continuous_block_text

# --- Modified Core Search Logic (Standard Mode) ---
def perform_search_standard(query, selected_authors, window_size, weight, decay, n_results=MAX_RESULTS_STANDARD):
    """Performs standard search: Embed -> Query -> Re-rank.

    Returns (results, query_embedding, error). `error` is None on success and a
    user-facing message when the search could not be carried out; an empty result list
    with error=None means the query simply had no matches.
    """
    logging.info(f"--- Starting Standard Search --- Query: '{query[:50]}...' | Authors: {selected_authors} | Target Results: {n_results} | Window={window_size}, Weight={weight:.2f}, Decay={decay:.2f}")
    original_query_embedding = None

    # Phase 1: Get Query Embedding. Kept out of the block below so that an embedding
    # failure is reported as such rather than as a generic search error.
    try:
        original_query_embedding = get_embedding(query, task="RETRIEVAL_QUERY")
    except Exception as e:
        logging.error(f"Standard Search: embedding error: {e}", exc_info=True)
        return [], None, ERR_EMBEDDING
    if original_query_embedding is None:
        logging.error("Standard Search: failed to generate query embedding.")
        return [], None, ERR_EMBEDDING

    try:
        # Phase 2: Build Filter
        where_filter = None
        if selected_authors:
            authors_filter_list = selected_authors if isinstance(selected_authors, list) else [selected_authors]
            authors_filter_list = [a for a in authors_filter_list if a and isinstance(a, str)]
            if authors_filter_list:
                where_filter = {"author": {"$in": authors_filter_list}}
                logging.info(f"Applying author filter: {where_filter}")
            else:
                logging.warning("Empty or invalid author filter list provided, searching all authors.")

        # Phase 3: Initial Search
        logging.info(f"Fetching initial {INITIAL_RESULTS_FOR_RERANK} candidates from DB.")
        initial_candidates = _perform_single_query_search(
            query, where_filter, INITIAL_RESULTS_FOR_RERANK, query_embedding=original_query_embedding
        )

        if not initial_candidates:
            logging.info("Standard Search: No initial results found from DB.")
            return [], original_query_embedding, None

        logging.info(f"Found {len(initial_candidates)} initial candidates. Proceeding to 1st pass re-ranking.")

        # Phase 4: Contextual Re-ranking (1st Pass)
        # The author quota applies here because this list is what the user sees.
        reranked_results = rerank_with_context(
            initial_candidates,
            original_query_embedding,
            n_results, # Target number of final results
            weight,    # Use argument
            decay,     # Use argument
            window_size, # Use argument
            MIN_CHARS_FOR_RELEVANT_NEIGHBOR, # Pass constant
            author_quota=MAX_RESULTS_PER_AUTHOR
        )
        logging.info(f"Standard Search: Re-ranked {len(initial_candidates)} -> Found {len(reranked_results)} final results.")

        return reranked_results, original_query_embedding, None

    except (ConnectionError, ValueError, RuntimeError) as e:
        logging.error(f"Standard Search failed: {e}", exc_info=False)
        return [], original_query_embedding, ERR_DB
    except Exception as e:
        logging.error(f"Standard Search encountered an unexpected error: {e}", exc_info=True)
        return [], original_query_embedding, ERR_UNEXPECTED

# --- Search Function (Standard Mode UI Wrapper) ---
def search_standard_mode_ui(search_results, query_embedding, error=None):
    """Prepares Gradio UI updates for the Standard Search results."""
    logging.info("Preparing UI updates for Standard Search results.")
    updates = create_reset_updates() # Start with a clean reset state dictionary

    # Store the received embedding (if valid) in the state used for context highlighting
    if query_embedding is not None:
        updates[direct_embedding_output_holder] = query_embedding
        logging.debug("Stored valid query embedding in direct_embedding_output_holder for standard mode.")
    else:
        updates[direct_embedding_output_holder] = None
        logging.warning("Query embedding was None, stored None in direct_embedding_output_holder for standard mode.")

    # The search never ran. Say so instead of showing it as a query without matches.
    if error:
        logging.error(f"Standard search reported an error: {error}")
        updates[result_accordion] = gr.update(visible=True, label="**Fehler:** Die Suche konnte nicht ausgeführt werden.", open=True)
        updates[result_metadata_display] = gr.update(value=error)
        updates[result_text] = gr.update(value="", visible=True)
        updates[single_result_group] = gr.update(visible=True)
        updates[full_search_results_state] = []
        updates[current_result_index_state] = 0
        updates[active_view_state] = "standard"
        return updates

    if not search_results:
        logging.info("No standard search results found to display.")
        # MODIFIED: Update new components
        updates[result_accordion] = gr.update(visible=True, label="Keine Resultate gefunden.", open=False)
        updates[result_metadata_display] = gr.update(value="")
        updates[result_text] = gr.update(value="", visible=True)
        updates[single_result_group] = gr.update(visible=True)
        # Ensure states are also reset/empty
        updates[full_search_results_state] = []
        updates[current_result_index_state] = 0
        updates[active_view_state] = "standard" # Still set view state even if empty
        return updates # Return the dictionary of updates

    # Populate state and update UI elements if results were found
    logging.info(f"Displaying first of {len(search_results)} standard results.")
    updates[full_search_results_state] = search_results
    updates[current_result_index_state] = 0 # Start at the first result
    updates[active_view_state] = "standard" # Set active view state

    # Format the first result for immediate display using the combined formatter
    # MODIFIED: Call format_result_display and get two parts
    accordion_title, accordion_content_md, text_content = format_result_display(search_results[0], 0, len(search_results), "standard")

    # MODIFIED: Update new components
    updates[result_accordion] = gr.update(visible=True, label=accordion_title, open=False)
    updates[result_metadata_display] = gr.update(value=accordion_content_md)
    updates[result_text] = gr.update(value=text_content, visible=True)

    # Make shared result group and navigation visible
    updates[single_result_group] = gr.update(visible=True)
    updates[standard_nav_row] = gr.update(visible=True)

    # Configure navigation buttons for Standard results
    updates[previous_result_button] = gr.update(visible=True, interactive=False) # Can't go back from first result
    updates[next_result_button] = gr.update(visible=True, interactive=(len(search_results) > 1)) # Enable if more than one result
    updates[weiterlesen_button] = gr.update(visible=True, interactive=True, value="weiterlesen") # Enable context button, ensure value

    return updates # Return the dictionary of updates


# --- Modified Core Search Logic (LLM Mode) ---
def perform_search_llm(query, selected_authors, window_size, weight, decay):
    """Performs LLM Re-Rank Search: Embed -> Query -> Re-rank -> Prep -> LLM -> Parse.

    Returns (results, query_embedding, error). `error` is None on success and a
    user-facing message when the search could not be carried out; an empty result list
    with error=None means the query had no matches, or the LLM judged nothing relevant.
    """
    logging.info(f"--- Starting LLM Re-Rank Search --- Query: '{query[:50]}...' | Authors: {selected_authors} | Window={window_size}, Weight={weight:.2f}, Decay={decay:.2f}")
    original_query_embedding = None

    # --- Phase 0: Get Query Embedding ---
    try:
        original_query_embedding = get_embedding(query, task="RETRIEVAL_QUERY")
    except Exception as embed_e:
        logging.error(f"LLM Re-Rank: Embedding error: {embed_e}", exc_info=True)
        return [], None, ERR_EMBEDDING
    if original_query_embedding is None:
        logging.error("LLM Re-Rank: failed to generate query embedding.")
        return [], None, ERR_EMBEDDING
    logging.info("Query embedding generated successfully for LLM search.")


    # --- Phase 1: Initial Search, Filter & First-Pass Re-ranking ---
    try:
        logging.info(f"LLM ReRank Mode: Initial search for query: '{query[:50]}...'")
        # Build Filter
        where_filter = None
        if selected_authors:
            authors_filter_list = selected_authors if isinstance(selected_authors, list) else [selected_authors]
            authors_filter_list = [a for a in authors_filter_list if a and isinstance(a, str)]
            if authors_filter_list:
                where_filter = {"author": {"$in": authors_filter_list}}
                logging.info(f"LLM ReRank: Applying WHERE filter: {where_filter}")
            else: logging.warning("Empty or invalid author filter list for LLM rerank.")

        # Initial DB Search
        initial_candidates = _perform_single_query_search(
            query, where_filter, INITIAL_RESULTS_FOR_RERANK, query_embedding=original_query_embedding
        )
        if not initial_candidates:
            logging.info("LLM ReRank Mode: No initial results found from DB.")
            return [], original_query_embedding, None

        logging.info(f"Found {len(initial_candidates)} initial candidates. Performing 1st pass re-ranking...")
        # First-Pass Re-ranking (Pass new arguments)
        # No author quota here: this list is only the LLM's input pool. Quota-ing it
        # would mean the LLM never sees a genuinely better fourth passage from a
        # heavily represented author, and could not recover it. Diversity is applied
        # to the LLM's own output below instead.
        first_pass_reranked = rerank_with_context(
            initial_candidates,
            original_query_embedding,
            LLM_RERANK_CANDIDATE_COUNT, # Target N for LLM input pool
            weight,       # Use argument
            decay,        # Use argument
            window_size, # Use argument
            MIN_CHARS_FOR_RELEVANT_NEIGHBOR, # Pass constant
            author_quota=None
        )
        # Select the top candidates to send to the LLM
        candidates_for_llm = first_pass_reranked[:LLM_RERANK_CANDIDATE_COUNT]

        if not candidates_for_llm:
            logging.info("LLM ReRank Mode: No candidates left after first-pass re-ranking.")
            return [], original_query_embedding, None

        logging.info(f"Selected top {len(candidates_for_llm)} candidates after 1st pass for LLM.")

    except (ConnectionError, ValueError, RuntimeError) as search_filter_e:
        logging.error(f"LLM Re-Rank: Initial Search/Filter/Re-rank error: {search_filter_e}", exc_info=True)
        return [], original_query_embedding, ERR_DB
    except Exception as e:
        logging.error(f"LLM Re-Rank: Unexpected error in Phase 1 (Search/Filter/Re-rank): {e}", exc_info=True)
        return [], original_query_embedding, ERR_UNEXPECTED


    # --- Phase 2: Prepare Passage Blocks for LLM Prompt ---
    try:
        logging.info("Preparing passage blocks for LLM prompt using pre-constructed blocks...")
        passage_separator = "\n\n--- PASSAGE SEPARATOR ---\n\n"
        prompt_passage_blocks_list = []

        for cand_data in candidates_for_llm:
            center_id_str = cand_data.get('id')
            context_block = cand_data.get('context_block')

            if not center_id_str or not context_block or context_block in ["_Kontextblock fehlt_", "_Fehler bei Kontext-Erstellung_"]:
                logging.warning(f"Skipping candidate {center_id_str} for LLM prompt due to missing ID or invalid context block.")
                continue

            prompt_block = f"Passage ID: {center_id_str}\nPassage Text:\n{context_block}"
            prompt_passage_blocks_list.append(prompt_block)

        if not prompt_passage_blocks_list:
            logging.warning("No valid context blocks could be prepared for the LLM prompt.")
            return [], original_query_embedding, ERR_LLM_NO_BLOCKS

        passage_blocks_str_for_prompt = passage_separator.join(prompt_passage_blocks_list)
        logging.info(f"Prepared {len(prompt_passage_blocks_list)} passage blocks for the LLM.")

    except Exception as e:
        logging.error(f"LLM Re-Rank: Error during passage block preparation (Phase 2): {e}", exc_info=True)
        return [], original_query_embedding, ERR_UNEXPECTED


    # --- Phase 3: Call LLM for Re-ranking and Truncation ---
    if not llm_rerank_model:
        logging.error("LLM Re-rank model is not available/initialized.")
        return [], original_query_embedding, ERR_LLM_UNAVAILABLE

    try:
        # Format the final prompt using the template
        rerank_prompt = LLM_RERANKING_PROMPT_TEMPLATE_V3.format(
            user_query=query,
            passage_blocks_str=passage_blocks_str_for_prompt, # Use constructed string
            target_count=LLM_RERANK_TARGET_COUNT # Use constant
        )

        logging.debug(f"LLM Rank/Truncate Prompt (first 500 chars):\n{rerank_prompt[:500]}...")
        # Save the full prompt to a file for debugging
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = os.path.join(PROMPT_LOG_DIR, f"{timestamp}_llm_rank_truncate_prompt.txt")
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"--- User Query ---\n{query}\n\n--- Prompt Sent to LLM ({LLM_RERANK_MODEL_NAME}) ---\n{rerank_prompt}")
            logging.info(f"LLM Rank/Truncate prompt saved to: {filename}")
        except IOError as log_e:
            logging.error(f"Error saving LLM Rank/Truncate prompt: {log_e}", exc_info=False)

        # Make the API call to Gemini. Structured output guarantees the response is a
        # JSON document matching LLM_RERANK_RESPONSE_SCHEMA, so no fenced-block
        # extraction is needed. The thinking budget and output cap keep a mechanical
        # re-ranking task from running away.
        logging.info(f"Sending Rank/Truncate request to LLM ({LLM_RERANK_MODEL_NAME})...")
        response = genai_client.models.generate_content(
            model=LLM_RERANK_MODEL_NAME,
            contents=rerank_prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
                response_schema=LLM_RERANK_RESPONSE_SCHEMA,
                max_output_tokens=LLM_MAX_OUTPUT_TOKENS,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=LLM_THINKING_BUDGET),
            )
        )
        logging.info("LLM Rank/Truncate response received.")

        # --- Phase 4: Parse LLM Response and Fetch Metadata ---
        logging.info("Processing LLM response...")

        # ---> START OF ROBUST RESPONSE HANDLING <---
        response_text = None
        finish_reason_name = 'UNKNOWN'

        try:
            if hasattr(response, 'prompt_feedback') and getattr(response.prompt_feedback, 'block_reason', None):
                block_reason = response.prompt_feedback.block_reason
                finish_reason_name = f"PROMPT_BLOCKED_{block_reason}"
                logging.error(f"LLM Rank/Truncate prompt was blocked! Reason: {block_reason}")
                return [], original_query_embedding, f"{ERR_LLM_BLOCKED} (Grund: {block_reason})"

            elif response.candidates:
                first_candidate = response.candidates[0]
                reason_enum = getattr(first_candidate, 'finish_reason', None)
                finish_reason_name = getattr(reason_enum, 'name', str(reason_enum))

                if finish_reason_name == "MAX_TOKENS":
                    # A truncated response is invalid JSON. Treat it as a failure instead
                    # of parsing a half-written document and silently losing results.
                    logging.error(f"LLM Rank/Truncate hit the {LLM_MAX_OUTPUT_TOKENS}-token output cap; response is truncated and cannot be parsed.")
                    return [], original_query_embedding, ERR_LLM_TRUNCATED

                if finish_reason_name == "STOP":
                    # response.text concatenates all non-thought parts; indexing parts[0]
                    # directly is unsafe with a thinking model.
                    response_text = response.text
                    logging.debug("Successfully extracted text from the response.")
                else:
                    logging.warning(f"LLM Rank/Truncate candidate finished with reason: {finish_reason_name}. No text content expected or extracted.")

            else:
                 logging.error("LLM response had no candidates.")

            if not response_text:
                logging.error(f"LLM Rank/Truncate returned no usable text content. Final Finish Reason Check: {finish_reason_name}")
                # Log response details if available for debugging
                logging.debug(f"Full LLM response object structure: {response}")
                return [], original_query_embedding, f"{ERR_LLM_NO_TEXT} (finish_reason: {finish_reason_name})"

        except Exception as resp_check_e:
            logging.error(f"Error checking LLM response structure/finish_reason: {resp_check_e}", exc_info=True)
            logging.debug(f"Full LLM response object structure during check error: {response}")
            return [], original_query_embedding, ERR_LLM_NO_TEXT
        # ---> END OF ROBUST RESPONSE HANDLING <---

        llm_response_text = response_text
        logging.debug(f"LLM Raw Response Text (used for parsing):\n{llm_response_text}")

        # --- Start JSON Parsing ---
        parsed_llm_results = []
        # Map each candidate's ID to the exact text the LLM was shown, so excerpts can
        # be verified against their source.
        source_blocks_by_id = {str(c['id']): c.get('context_block', '') for c in candidates_for_llm if c.get('id')}

        try:
            # response_schema guarantees a bare JSON document; no fence stripping needed.
            parsed_response = json.loads(llm_response_text)

            # Validate the top-level structure
            if "ranked_edited_passages" not in parsed_response or not isinstance(parsed_response["ranked_edited_passages"], list):
                logging.error("LLM JSON response missing 'ranked_edited_passages' list or it's not a list.")
                raise ValueError("JSON response structure invalid: missing 'ranked_edited_passages' list.")

            raw_results = parsed_response["ranked_edited_passages"]
            logging.info(f"LLM returned {len(raw_results)} items in 'ranked_edited_passages'.")

            # Validate and collect individual results from the list
            parsed_llm_results = [] # Reset before processing
            unfaithful_count = 0
            for i, item in enumerate(raw_results):
                if isinstance(item, dict) and 'original_id' in item and 'edited_text' in item:
                    item_id = str(item['original_id']) # Ensure ID is string
                    item_text = str(item['edited_text'])
                    item_rationale = item.get('rationale', '') # Rationale is optional

                    if item_id and item_text.strip(): # Only add if ID and text are non-empty
                        # The excerpt is displayed to the user as a quotation from the
                        # philosopher, so it must actually be the philosopher's words.
                        # A re-ranking model asked to "extract" will occasionally
                        # paraphrase or normalise spelling; fall back to the untouched
                        # source text rather than showing an altered quote.
                        source_block = source_blocks_by_id.get(item_id)
                        verified_text, was_faithful = _verify_excerpt(item_text, source_block)
                        if not was_faithful:
                            unfaithful_count += 1
                            logging.warning(
                                f"LLM excerpt for ID {item_id} is not a verbatim substring of the source passage; "
                                f"falling back to the original text. LLM text: '{item_text[:120]}...'"
                            )
                        parsed_llm_results.append({
                            'id': item_id,
                            'edited_text': verified_text,
                            'rationale': item_rationale,
                            'excerpt_verified': was_faithful,
                        })
                    else:
                        logging.warning(f"Skipping invalid or empty LLM result item at index {i}: {item}")
                else:
                    logging.warning(f"Skipping item with invalid format in 'ranked_edited_passages' at index {i}: {item}")

            # Truncate to the target count if needed (should be handled by LLM, but safe)
            parsed_llm_results = parsed_llm_results[:LLM_RERANK_TARGET_COUNT]
            logging.info(f"Successfully parsed {len(parsed_llm_results)} valid ranked/edited passages from LLM response "
                         f"({unfaithful_count} excerpt(s) failed verbatim verification and were replaced).")

            if not parsed_llm_results:
                # The LLM is explicitly allowed to return fewer passages than asked for,
                # so an empty (but well-formed) list means "nothing relevant", not a fault.
                logging.info("LLM parsing yielded no valid passages.")
                return [], original_query_embedding, None

        except (json.JSONDecodeError, ValueError) as parse_e:
             logging.error(f"LLM Rank/Truncate response JSON parsing error: {parse_e}", exc_info=True)
             logging.error(f"--- LLM Response Text causing JSON error ---\n{llm_response_text}\n--- End Response ---")
             return [], original_query_embedding, ERR_LLM_PARSE
        except Exception as parse_e:
             logging.error(f"Unexpected error during LLM JSON parsing: {parse_e}", exc_info=True)
             return [], original_query_embedding, ERR_LLM_PARSE
        # --- End JSON Parsing ---


        # --- Fetch Metadata for LLM Results ---
        # We need the original metadata (author, book, etc.) from the DB for displaying results correctly.
        result_ids_to_fetch = [res['id'] for res in parsed_llm_results]
        logging.info(f"Fetching metadata directly for {len(result_ids_to_fetch)} final LLM result IDs.")

        if result_ids_to_fetch:
            fetched_metadata_map = fetch_multiple_passage_data(result_ids_to_fetch)
            logging.debug(f"Fetched metadata map contains {len(fetched_metadata_map)} entries for final LLM results.")
        else:
            # If no IDs to fetch (e.g., no results parsed), return empty
            logging.warning("No result IDs to fetch metadata for after LLM parsing.")
            return [], original_query_embedding, None


        # --- Combine parsed text with fetched metadata for the final UI structure ---
        final_llm_results_for_ui = []
        for result in parsed_llm_results:
            passage_id = result['id']
            passage_data = fetched_metadata_map.get(passage_id)
            if passage_data:
                final_llm_results_for_ui.append({
                    'id': passage_id, # Original ID
                    'original_id': passage_id, # Store original_id explicitly for formatter
                    'edited_text': result.get('edited_text', '_Editierter Text fehlt_'), # LLM's edited text
                    'rationale': result.get('rationale', ''), # LLM's rationale
                    'excerpt_verified': result.get('excerpt_verified', False), # Verbatim check outcome
                    'metadata': passage_data.get('meta', {}) # Original metadata from DB fetch
                    # Note: Distance and Initial/Final similarity from previous steps are NOT included
                    # as the LLM result is a new entity, not directly representing a DB passage's score.
                })
            else:
                logging.warning(f"Could not fetch metadata from DB for final LLM result ID: {passage_id}. Skipping this result.")

        if not final_llm_results_for_ui:
            logging.error("Failed to fetch metadata for any of the LLM's ranked passages.")
            # Still return the original query embedding if available
            return [], original_query_embedding, ERR_LLM_METADATA

        # --- Apply the author quota to the LLM's ranking ---
        # The first pass deliberately skipped the quota so the LLM could judge the full
        # candidate pool; diversity is enforced here, on its final ordering. The target
        # count matters: without it the quota would drop the LLM's surplus passages
        # instead of moving them down the list, and there is nothing further upstream
        # to backfill from at this point.
        final_llm_results_for_ui = _apply_author_quota(
            final_llm_results_for_ui, MAX_RESULTS_PER_AUTHOR, LLM_RERANK_TARGET_COUNT
        )

        # --- Success ---
        logging.info(f"LLM Re-Rank Search successful. Returning {len(final_llm_results_for_ui)} processed results.")
        # Return the list of results and the original query embedding
        return final_llm_results_for_ui, original_query_embedding, None

    except Exception as e:
        logging.error(f"LLM Rank/Truncate general processing error after API call: {e}", exc_info=True)
        return [], original_query_embedding, ERR_UNEXPECTED


# --- Search Function (LLM Re-Rank Mode UI Wrapper) ---
def search_llm_rerank_mode_ui(llm_results, query_embedding, error=None):
    """Prepares Gradio UI updates for the LLM Re-Rank Search results."""
    logging.info("Preparing UI updates for LLM Re-Rank Search results.")
    updates = create_reset_updates() # Start with reset state

    # Store the received embedding for context highlighting
    if query_embedding is not None:
        updates[direct_embedding_output_holder] = query_embedding
        logging.debug("Stored valid query embedding in direct_embedding_output_holder for LLM mode.")
    else:
        updates[direct_embedding_output_holder] = None
        logging.warning("Query embedding was None for LLM mode.")

    # Set active view state early
    updates[active_view_state] = "llm"

    # The search never ran. Say what went wrong instead of showing it as "no passages".
    if error:
        logging.error(f"LLM search reported an error: {error}")
        # Use the shared display group
        updates[single_result_group] = gr.update(visible=True)
        # MODIFIED: Update new components
        updates[result_accordion] = gr.update(visible=True, label="**Fehler:** LLM Re-Ranking fehlgeschlagen.", open=True)
        updates[result_metadata_display] = gr.update(value=f"{error}\n\n_Weitere Details siehe Server-Logs._")
        updates[result_text] = gr.update(value="", visible=True)
        # Ensure states are empty
        updates[llm_results_state] = []
        updates[llm_result_index_state] = 0
        return updates

    # Check if results list is empty (no relevant passages found/parsed, but no error)
    if not llm_results:
        logging.info("LLM search returned no relevant passages.")
        # Use the shared display group
        updates[single_result_group] = gr.update(visible=True)
        # MODIFIED: Update new components
        updates[result_accordion] = gr.update(visible=True, label="LLM Resultate", open=False)
        updates[result_metadata_display] = gr.update(value="_(Keine relevanten Passagen nach LLM Re-Ranking gefunden.)_")
        updates[result_text] = gr.update(value="", visible=True)
        # Ensure states are empty
        updates[llm_results_state] = []
        updates[llm_result_index_state] = 0
        return updates

    # Got results, update UI
    logging.info(f"Displaying first of {len(llm_results)} LLM re-ranked results.")
    updates[llm_results_state] = llm_results
    updates[llm_result_index_state] = 0 # Start at first result

    # Format and display the first result using the combined formatter
    # MODIFIED: Call format_result_display and get two parts
    accordion_title, accordion_content_md, text_content = format_result_display(llm_results[0], 0, len(llm_results), "llm")

    # MODIFIED: Update new components
    updates[result_accordion] = gr.update(visible=True, label=accordion_title, open=False)
    updates[result_metadata_display] = gr.update(value=accordion_content_md)
    updates[result_text] = gr.update(value=text_content, visible=True)


    # Make shared result group and navigation visible
    updates[single_result_group] = gr.update(visible=True)
    updates[standard_nav_row] = gr.update(visible=True)

    # Configure navigation buttons for LLM results
    updates[previous_result_button] = gr.update(visible=True, interactive=False)
    updates[next_result_button] = gr.update(visible=True, interactive=(len(llm_results) > 1))
    updates[weiterlesen_button] = gr.update(visible=True, interactive=True, value="im Original weiterlesen") # Enable context button, change value

    return updates

# --- Result Navigation Function (Standard Mode) ---
def navigate_results(direction, current_index, full_results):
    """Handles UI updates for navigating standard search results."""
    logging.info(f"Navigating standard results: Direction={direction}, Index={current_index}")
    # Define default updates (hide context, show standard results, etc.)
    updates = {
        standard_nav_row: gr.update(visible=True), # Show the shared nav row
        single_result_group: gr.update(visible=True), # Show the shared result group
        # MODIFIED: Clear new components instead of single_result_display_md
        result_accordion: gr.update(label="...", open=False, visible=True),
        result_metadata_display: gr.update(value=""),
        result_text: gr.update(value="", visible=True),
        # Buttons in standard_nav_row will be managed based on index below
        previous_result_button: gr.update(visible=True),
        next_result_button: gr.update(visible=True),
        weiterlesen_button: gr.update(visible=True, value="weiterlesen"), # Standard search weiterlesen

        context_area: gr.update(visible=False), # Hide context
        back_to_results_button: gr.update(visible=False), # Hide back button
        current_result_index_state: current_index, # Store potentially new index
        full_search_results_state: full_results, # Pass state through
        active_view_state: "standard" # Ensure view state is correct
    }

    if not full_results or not isinstance(full_results, list):
        logging.warning("Cannot navigate: No standard results available in state.")
        updates[current_result_index_state] = 0
        # MODIFIED: Update new components
        updates[result_accordion] = gr.update(visible=True, label="Keine Resultate zum Navigieren.", open=False)
        updates[result_metadata_display] = gr.update(value="")
        updates[result_text] = gr.update(value="", visible=True)
        # Hide all navigation elements in the shared row
        updates[previous_result_button] = gr.update(interactive=False, visible=False)
        updates[next_result_button] = gr.update(interactive=False, visible=False)
        updates[weiterlesen_button] = gr.update(visible=False)
        updates[standard_nav_row] = gr.update(visible=False) # Hide the nav row itself
        updates[single_result_group] = gr.update(visible=False) # Hide the result group itself
        return updates # Return the dictionary of updates


    total_results = len(full_results)
    new_index = current_index

    # Calculate new index based on direction
    if direction == 'previous':
        new_index = max(0, current_index - 1)
    elif direction == 'next':
        new_index = min(total_results - 1, current_index + 1)

    # Update display if index is valid
    if 0 <= new_index < total_results:
        result_data = full_results[new_index]
        # MODIFIED: Use the combined formatter and get two parts
        accordion_title, accordion_content_md, text_content = format_result_display(result_data, new_index, total_results, "standard")

        # MODIFIED: Update new components
        updates[result_accordion] = gr.update(visible=True, label=accordion_title, open=False)
        updates[result_metadata_display] = gr.update(value=accordion_content_md)
        updates[result_text] = gr.update(value=text_content, visible=True)

        updates[current_result_index_state] = new_index # Update state with new index
        # Update button interactivity based on new index
        updates[previous_result_button] = gr.update(interactive=(new_index > 0))
        updates[next_result_button] = gr.update(interactive=(new_index < total_results - 1))
        updates[weiterlesen_button] = gr.update(interactive=True) # Always possible from a result
        logging.info(f"Navigated standard results to index {new_index}")
    else:
        # Should not happen with bounds checking, but handle defensively
        logging.error(f"Navigation error: New index {new_index} out of bounds [0, {total_results-1}]")
        # MODIFIED: Update new components on error
        updates[result_accordion] = gr.update(visible=True, label="Fehler beim Navigieren der Resultate.", open=False)
        updates[result_metadata_display] = gr.update(value="")
        updates[result_text] = gr.update(value="", visible=True)
        updates[previous_result_button] = gr.update(interactive=False)
        updates[next_result_button] = gr.update(interactive=False)
        updates[weiterlesen_button] = gr.update(interactive=False)


    return updates

# --- Navigation Function for LLM Results ---
def navigate_llm_results(direction, current_index, llm_results):
    """Handles UI updates for navigating LLM re-ranked results."""
    logging.info(f"Navigating LLM results: Direction={direction}, Index={current_index}")
    # Define default updates (show LLM results, hide others)
    updates = {
        standard_nav_row: gr.update(visible=True), # Show the shared nav row
        single_result_group: gr.update(visible=True), # Show the shared result group
        # MODIFIED: Clear new components instead of single_result_display_md
        result_accordion: gr.update(label="...", open=False, visible=True),
        result_metadata_display: gr.update(value=""),
        result_text: gr.update(value="", visible=True),
        # Buttons in standard_nav_row will be managed based on index below
        previous_result_button: gr.update(visible=True),
        next_result_button: gr.update(visible=True),
        weiterlesen_button: gr.update(visible=True, value="im Original weiterlesen"), # LLM search weiterlesen

        context_area: gr.update(visible=False), # Hide context
        back_to_results_button: gr.update(visible=False), # Hide back button
        llm_results_state: llm_results, # Pass state through
        llm_result_index_state: current_index, # Store potentially new index
        active_view_state: "llm" # Ensure view state is correct
    }

    if not llm_results or not isinstance(llm_results, list):
        logging.warning("Cannot navigate: No LLM results available in state.")
        # MODIFIED: Update new components
        updates[result_accordion] = gr.update(visible=True, label="Keine LLM-Resultate vorhanden.", open=False)
        updates[result_metadata_display] = gr.update(value="")
        updates[result_text] = gr.update(value="", visible=True)
        # Hide navigation elements in the shared row
        updates[previous_result_button] = gr.update(interactive=False, visible=False)
        updates[next_result_button] = gr.update(interactive=False, visible=False)
        updates[weiterlesen_button] = gr.update(visible=False)
        updates[standard_nav_row] = gr.update(visible=False) # Hide the nav row itself
        updates[single_result_group] = gr.update(visible=False) # Hide the result group itself
        # Reset state
        updates[llm_results_state] = []
        updates[llm_result_index_state] = 0
        return updates

    total_results = len(llm_results)
    new_index = current_index

    # Calculate new index
    if direction == 'previous':
        new_index = max(0, current_index - 1)
    elif direction == 'next':
        new_index = min(total_results - 1, current_index + 1)

    # Update display if index is valid
    if 0 <= new_index < total_results:
        result_data = llm_results[new_index]
        # MODIFIED: Use the combined formatter and get two parts
        accordion_title, accordion_content_md, text_content = format_result_display(result_data, new_index, total_results, "llm")

        # MODIFIED: Update new components
        updates[result_accordion] = gr.update(visible=True, label=accordion_title, open=False)
        updates[result_metadata_display] = gr.update(value=accordion_content_md)
        updates[result_text] = gr.update(value=text_content, visible=True)

        updates[llm_result_index_state] = new_index # Update state
        # Update button interactivity
        updates[previous_result_button] = gr.update(interactive=(new_index > 0))
        updates[next_result_button] = gr.update(interactive=(new_index < total_results - 1))
        updates[weiterlesen_button] = gr.update(interactive=True)
        logging.info(f"Navigated LLM results to index {new_index}")
    else:
        logging.error(f"LLM Navigation error: New index {new_index} out of bounds [0, {total_results-1}]")
        # MODIFIED: Update new components on error
        updates[result_accordion] = gr.update(visible=True, label="Fehler beim Navigieren der LLM-Resultate.", open=False)
        updates[result_metadata_display] = gr.update(value="")
        updates[result_text] = gr.update(value="", visible=True)
        updates[previous_result_button] = gr.update(interactive=False)
        updates[next_result_button] = gr.update(interactive=False)
        updates[weiterlesen_button] = gr.update(interactive=False)


    return updates

# --- Navigation Function for Favourites ---
def navigate_best_results(direction, current_index, best_results):
    """Handles UI updates for navigating favourite results."""
    logging.info(f"Navigating favourite results: Direction={direction}, Index={current_index}")
    # Define default updates (show favourites, hide others)
    updates = {
        standard_nav_row: gr.update(visible=True), # Show the shared nav row
        single_result_group: gr.update(visible=True), # Show the shared result group
        # MODIFIED: Clear new components instead of single_result_display_md
        result_accordion: gr.update(label="...", open=False, visible=True),
        result_metadata_display: gr.update(value=""),
        result_text: gr.update(value="", visible=True),
        # Buttons in standard_nav_row will be managed based on index below
        previous_result_button: gr.update(visible=True),
        next_result_button: gr.update(visible=True),
        weiterlesen_button: gr.update(visible=True, value="weiterlesen"), # Favourites weiterlesen

        context_area: gr.update(visible=False), # Hide context
        back_to_results_button: gr.update(visible=False), # Hide back button
        best_results_state: best_results, # Pass state through
        best_index_state: current_index, # Store potentially new index
        active_view_state: "favourites" # Ensure view state is correct
    }

    if not best_results or not isinstance(best_results, list):
        logging.warning("Cannot navigate: No favourite results available in state.")
        updates[best_index_state] = 0
        # MODIFIED: Update new components
        updates[result_accordion] = gr.update(visible=True, label="_Keine Favoriten zum Navigieren._", open=False)
        updates[result_metadata_display] = gr.update(value="")
        updates[result_text] = gr.update(value="", visible=True)
        # Hide navigation elements in the shared row
        updates[previous_result_button] = gr.update(interactive=False, visible=False)
        updates[next_result_button] = gr.update(interactive=False, visible=False)
        updates[weiterlesen_button] = gr.update(visible=False)
        updates[standard_nav_row] = gr.update(visible=False) # Hide the nav row itself
        updates[single_result_group] = gr.update(visible=False) # Hide the result group itself
        # Reset state
        updates[best_results_state] = []
        updates[best_index_state] = 0
        return updates


    total_results = len(best_results)
    new_index = current_index

    # Calculate new index
    if direction == 'previous':
        new_index = max(0, current_index - 1)
    elif direction == 'next':
        new_index = min(total_results - 1, current_index + 1)

    # Update display if index is valid
    if 0 <= new_index < total_results:
        result_data = best_results[new_index]
        # MODIFIED: Use the combined formatter and get two parts
        accordion_title, accordion_content_md, text_content = format_result_display(result_data, new_index, total_results, "favourites")

        # MODIFIED: Update new components
        updates[result_accordion] = gr.update(visible=True, label=accordion_title, open=False)
        updates[result_metadata_display] = gr.update(value=accordion_content_md)
        updates[result_text] = gr.update(value=text_content, visible=True)

        updates[best_index_state] = new_index # Update state
        # Update button interactivity
        updates[previous_result_button] = gr.update(interactive=(new_index > 0))
        updates[next_result_button] = gr.update(interactive=(new_index < total_results - 1))
        updates[weiterlesen_button] = gr.update(interactive=True) # Always possible from a favourite
        logging.info(f"Navigated favourite results to index {new_index}")
    else:
        logging.error(f"Favourite Navigation error: New index {new_index} out of bounds [0, {total_results-1}]")
        # MODIFIED: Update new components on error
        updates[result_accordion] = gr.update(visible=True, label="Fehler beim Navigieren der Favoriten.", open=False)
        updates[result_metadata_display] = gr.update(value="")
        updates[result_text] = gr.update(value="", visible=True)
        updates[previous_result_button] = gr.update(interactive=False)
        updates[next_result_button] = gr.update(interactive=False)
        updates[weiterlesen_button] = gr.update(interactive=False)


    return updates


# --- Move Standard Result to Reading Area (UI Logic) ---
def move_to_reading_area_ui(current_index, full_results, query_embedding_value, result_type):
    """Handles UI updates and data fetching for moving a result (Standard, LLM, or Favourite)
       to the context reading area."""
    logging.info(f"--- Moving {result_type} Result (Index: {current_index}) to Reading Area ---")
    # Define UI changes: Hide results, show context area, set loading message
    updates = {
        standard_nav_row: gr.update(visible=False), # Hide the shared results nav
        single_result_group: gr.update(visible=False), # Hide the shared results group
        context_area: gr.update(visible=True), # Show context area immediately
        context_display: gr.update(value="Lade Paragraphen..."), # Loading message
        load_previous_button: gr.update(visible=True, interactive=True),
        load_next_button: gr.update(visible=True, interactive=True),
        back_to_results_button: gr.update(visible=True, interactive=True)
    }
    # Define state changes separately
    state_updates = {
        # Preserve the relevant state indices and lists based on result_type
        full_search_results_state: [], # Will be replaced by full_results if result_type is standard
        current_result_index_state: 0,
        llm_results_state: [], # Will be replaced by full_results if result_type is llm
        llm_result_index_state: 0,
        best_results_state: [], # Will be replaced by full_results if result_type is favourites
        best_index_state: 0,
        displayed_context_passages: [], # Reset context state before loading
        direct_embedding_output_holder: query_embedding_value # Pass embedding
    }

    if result_type == "standard":
         state_updates[full_search_results_state] = full_results
         state_updates[current_result_index_state] = current_index
         state_updates[active_view_state] = "context_from_standard"
    elif result_type == "llm":
         state_updates[llm_results_state] = full_results # Note: full_results holds LLM results here
         state_updates[llm_result_index_state] = current_index
         state_updates[active_view_state] = "context_from_llm"
    elif result_type == "favourites":
         state_updates[best_results_state] = full_results # Note: full_results holds favourite results here
         state_updates[best_index_state] = current_index
         state_updates[active_view_state] = "context_from_favourites" # New state for favourites context
         # For favourites, the query embedding is not directly relevant for highlighting the original text,
         # as the favourite was selected based on its score. However, we keep the state updated in case needed later.
         # Maybe set to None or a specific marker if we don't want query highlighting? Let's keep it for now.
         # state_updates[direct_embedding_output_holder] = None


    # Log the received embedding for debugging highlighting
    logging.debug(f"move_to_reading_area_ui: Received query_embedding_value type: {type(query_embedding_value)}, len/shape: {len(query_embedding_value) if isinstance(query_embedding_value, (list, np.ndarray)) else 'N/A'}, result_type: {result_type}")


    # Validate input
    if not full_results or not isinstance(full_results, list) or not (0 <= current_index < len(full_results)):
        logging.error(f"Invalid {result_type} result reference for moving to reading area.")
        updates[context_display] = gr.update(value="Fehler: Ungültige Resultat-Referenz zum Lesen.")
        updates[load_previous_button] = gr.update(interactive=False)
        updates[load_next_button] = gr.update(interactive=False)
        return {**updates, **state_updates}

    try:
        # Get data for the selected result
        target_result_data = full_results[current_index]
        passage_meta = target_result_data.get('metadata', {})
        selected_passage_id = target_result_data.get('id') # Use 'id' for favourites too

        # Extract metadata needed to fetch the paragraph
        author = passage_meta.get('author')
        book = passage_meta.get('book')
        paragraph_idx = passage_meta.get('paragraph_index') # Should be integer or None

        # Check if necessary metadata is present
        if author is None or book is None or paragraph_idx is None or not isinstance(paragraph_idx, int) or paragraph_idx < 0:
            logging.error(f"Missing necessary metadata (author/book/paragraph_index) for {result_type} result ID {selected_passage_id}: Meta={passage_meta}")
            updates[context_display] = gr.update(value="Fehler: Metadaten unvollständig. Paragraph kann nicht geladen werden.")
            updates[load_previous_button] = gr.update(interactive=False)
            updates[load_next_button] = gr.update(interactive=False)
            return {**updates, **state_updates}

        logging.info(f"Fetching initial paragraph for context: Author='{author}', Book='{book}', ParagraphIndex={paragraph_idx}")
        # Fetch the full paragraph data (including embeddings)
        initial_paragraph_sentences = fetch_paragraph_data(author, book, paragraph_idx)

        if not initial_paragraph_sentences:
            logging.error(f"Could not fetch paragraph sentences for {author}/{book}/P{paragraph_idx}")
            updates[context_display] = gr.update(value="Fehler: Der zugehörige Paragraph konnte nicht geladen werden (möglicherweise leer?). Die Navigation zum nächsten/vorherigen Paragraphen ist weiterhin aktiv.")
            # Buttons remain interactive=True

            # Still need to update the state, even if empty sentences were returned,
            # to correctly reflect that the context area is active.
            state_updates[displayed_context_passages] = []
            return {**updates, **state_updates}


        # Format the fetched paragraph using the VALID query embedding received as input
        logging.info(f"Formatting paragraph {paragraph_idx} with {len(initial_paragraph_sentences)} sentences for display.")
        formatted_passage_md = format_context_markdown(initial_paragraph_sentences, query_embedding_value) # Use the passed embedding
        updates[context_display] = gr.update(value=formatted_passage_md) # Update display
        # Update state with the fetched sentences
        state_updates[displayed_context_passages] = initial_paragraph_sentences
        # Buttons are already interactive=True from the initial update dict
        logging.info(f"Paragraph {paragraph_idx} (for passage ID {selected_passage_id}) displayed in context area.")

    except Exception as e:
        logging.error(f"Error moving {result_type} passage to reading area: {e}", exc_info=True)
        updates[context_display] = gr.update(value=f"**Fehler:** Der Paragraph konnte nicht angezeigt werden. Details siehe Server-Logs.")
        updates[load_previous_button] = gr.update(interactive=False)
        updates[load_next_button] = gr.update(interactive=False)

    return {**updates, **state_updates}

# --- Go Back To Results Function ---
# ... (go_back_to_results_wrapper remains the same in logic, but updates new UI components) ...
def go_back_to_results_wrapper(last_active_view, std_results, std_index, llm_results, llm_index, best_results, best_index, current_fav_signal_value, query_embedding_value):
    """Handles UI updates for returning from the context view to the appropriate results view."""
    logging.info(f"Triggered: go_back_to_results_wrapper from view: {last_active_view}")

    updates_dict = {
        # Reset context area visibility
        context_area: gr.update(visible=False),
        context_display: gr.update(value=""), # Clear context display
        displayed_context_passages: [], # Reset context state

        # Pass through existing results and indices states
        full_search_results_state: std_results, current_result_index_state: std_index,
        llm_results_state: llm_results, llm_result_index_state: llm_index,
        best_results_state: best_results, best_index_state: best_index,
        direct_embedding_output_holder: query_embedding_value, # Keep embedding so highlighting keeps working
        fav_signal: gr.update(value=current_fav_signal_value), # <--- Pass through fav_signal state
        active_view_state: "none", # Reset active view temporarily before setting correct one

        # MODIFIED: Ensure the new result components are cleared before potentially showing results
        result_accordion: gr.update(label="...", open=False, visible=False),
        result_metadata_display: gr.update(value=""),
        result_text: gr.update(value="", visible=False),
    }
    # Hide status message
    updates_dict[status_message] = gr.update(value="", visible=False)


    # Determine which result view to show based on where we came from
    target_view = "none"
    target_results_list = []
    target_index = 0
    result_type = "unknown" # Used for formatting

    if last_active_view == "context_from_standard":
        updates_dict[standard_nav_row] = gr.update(visible=True)
        updates_dict[single_result_group] = gr.update(visible=True)
        target_view = "standard"
        target_results_list = std_results
        target_index = std_index
        result_type = "standard"
        logging.info("Going back to Standard results.")
    elif last_active_view == "context_from_llm":
        updates_dict[standard_nav_row] = gr.update(visible=True) # Assuming LLM uses standard nav row layout
        updates_dict[single_result_group] = gr.update(visible=True) # Assuming LLM uses standard group layout
        target_view = "llm"
        target_results_list = llm_results
        target_index = llm_index
        result_type = "llm"
        logging.info("Going back to LLM results.")
    elif last_active_view == "context_from_favourites":
         # Assuming favourites use the same display/nav components but potentially managed differently
         updates_dict[standard_nav_row] = gr.update(visible=True)
         updates_dict[single_result_group] = gr.update(visible=True)
         target_view = "favourites"
         target_results_list = best_results
         target_index = best_index
         result_type = "favourites"
         logging.info("Going back to Favourites.")
    else:
        logging.warning(f"Back button triggered from unexpected state: {last_active_view}")
        # Default to showing standard search if view is unknown or error state
        updates_dict[standard_nav_row] = gr.update(visible=True)
        updates_dict[single_result_group] = gr.update(visible=True)
        # MODIFIED: Set initial state for new components
        updates_dict[result_accordion] = gr.update(label="Kontextansicht verlassen.", open=False, visible=True)
        updates_dict[result_metadata_display] = gr.update(value="")
        updates_dict[result_text] = gr.update(value="", visible=True)
        target_view = "standard" # Fallback view
        # Ensure buttons are hidden if no data is available

        updates_dict[previous_result_button] = gr.update(visible=False, interactive=False)
        updates_dict[next_result_button] = gr.update(visible=False, interactive=False)
        updates_dict[weiterlesen_button] = gr.update(visible=False, interactive=False)

        # Return here if we hit an unknown state
        updates_dict[active_view_state] = target_view # Set fallback view state
        return updates_dict


    # Update the active_view state to the results view we returned to
    updates_dict[active_view_state] = target_view

    # Now manually update the result display and navigation buttons for the target view
    if target_results_list and isinstance(target_results_list, list) and 0 <= target_index < len(target_results_list):
         result_data = target_results_list[target_index]
         # MODIFIED: Use the combined formatter and update new components
         accordion_title, accordion_content_md, text_content = format_result_display(result_data, target_index, len(target_results_list), result_type)
         updates_dict[result_accordion] = gr.update(visible=True, label=accordion_title, open=False)
         updates_dict[result_metadata_display] = gr.update(value=accordion_content_md)
         updates_dict[result_text] = gr.update(value=text_content, visible=True)

         # Update button interactivity based on the selected index and total results
         updates_dict[previous_result_button] = gr.update(visible=True, interactive=(target_index > 0))
         updates_dict[next_result_button] = gr.update(visible=True, interactive=(target_index < len(target_results_list) - 1))
         updates_dict[weiterlesen_button] = gr.update(visible=True, interactive=True, value="weiterlesen" if result_type != "llm" else "im Original weiterlesen")

    else:
         # If the result list is empty or invalid, show appropriate message
         error_msg_label = f"_{target_view.capitalize()}-Resultate nicht verfügbar._"
         error_msg_content = "" # No content for metadata
         updates_dict[result_accordion] = gr.update(visible=True, label=error_msg_label, open=False)
         updates_dict[result_metadata_display] = gr.update(value=error_msg_content)
         updates_dict[result_text] = gr.update(value="", visible=True) # Clear text area

         # Hide navigation buttons as there are no results to navigate
         updates_dict[previous_result_button] = gr.update(visible=False, interactive=False)
         updates_dict[next_result_button] = gr.update(visible=False, interactive=False)
         updates_dict[weiterlesen_button] = gr.update(visible=False, interactive=False)

    return updates_dict


# --- Load More Context Function ---
def load_more_context(direction, current_passages_state, query_embedding_value):
    """Loads the previous or next paragraph in the reading view."""
    logging.info(f"--- Loading More Context: Direction={direction} ---")
    # Log embedding details for debugging highlighting
    logging.debug(f"load_more_context: Received query_embedding_value type: {type(query_embedding_value)}, len/shape: {len(query_embedding_value) if isinstance(query_embedding_value, (list, np.ndarray)) else 'N/A'}")


    # --- Initial Checks ---
    if collection is None:
        logging.error("Cannot load more context: DB collection not available.")
        err_msg = format_context_markdown(current_passages_state or [], query_embedding_value) + "\n\n**Fehler: Datenbank nicht verfügbar.**"
        return err_msg, current_passages_state # Return existing state


    if not current_passages_state or not isinstance(current_passages_state, list):
        logging.warning("load_more_context called with empty or invalid current passage state.")
        return "_Keine Passage geladen, kann nicht mehr Kontext laden._", []

    # Define marker IDs used to indicate boundaries
    START_MARKER_ID = '-1' # Represents reaching the beginning
    END_MARKER_ID = 'END_MARKER_ID' # Represents reaching the end


    try:
        # --- Determine Boundary and Target Paragraph ---
        # Ensure current state is sorted (should be, but safe)
        current_passages_state.sort(key=lambda x: (x.get('paragraph_index', -1), x.get('sentence_sort_key', float('inf'))))

        boundary_passage = None
        target_paragraph_index = -1 # Target index to fetch
        add_at_beginning = False # Flag to prepend or append new paragraph


        if direction == 'previous':
            add_at_beginning = True
            # Find the first non-missing passage to use as the boundary reference
            first_content_passage = next((p for p in current_passages_state if p.get('role') != 'missing'), None)

            if not first_content_passage:
                 logging.warning("Context state contains only markers or is empty. Cannot load previous paragraph.")
                 # Format existing (only markers) and return current state
                 return format_context_markdown(current_passages_state, query_embedding_value), current_passages_state

            boundary_passage = first_content_passage

            # Check if we are already at the start boundary (by looking at the ID of the very first item)
            if current_passages_state[0].get('id') == START_MARKER_ID:
                logging.info("Already at the start boundary marker. No previous paragraph to load.")
                # Reformat existing content (no change expected) and return current state
                return format_context_markdown(current_passages_state, query_embedding_value), current_passages_state


            current_para_idx = boundary_passage.get('paragraph_index')
            # Calculate target index, handle None or 0 index
            if current_para_idx is None or not isinstance(current_para_idx, int) or current_para_idx <= 0:
                target_paragraph_index = -2 # Indicates we've hit the conceptual start (index < 0)
            else:
                target_paragraph_index = current_para_idx - 1


        elif direction == 'next':
            add_at_beginning = False
            # Find the last non-missing passage to use as the boundary reference
            last_content_passage = next((p for p in reversed(current_passages_state) if p.get('role') != 'missing'), None)

            if not last_content_passage:
                 logging.warning("Context state contains only markers or is empty. Cannot load next paragraph.")
                 return format_context_markdown(current_passages_state, query_embedding_value), current_passages_state

            boundary_passage = last_content_passage

            # Check if we are already at the end boundary (by looking at the ID of the very last item)
            if current_passages_state[-1].get('id') == END_MARKER_ID:
                logging.info("Already at the end boundary marker. No next paragraph to load.")
                return format_context_markdown(current_passages_state, query_embedding_value), current_passages_state


            current_para_idx = boundary_passage.get('paragraph_index')
            # Check for missing index on the boundary passage
            if current_para_idx is None or not isinstance(current_para_idx, int):
                logging.error("Cannot load next paragraph: current boundary passage is missing a valid paragraph index.")
                err_msg = format_context_markdown(current_passages_state, query_embedding_value) + "\n\n**Fehler: Interner Zustand inkonsistent (fehlender Paragraph-Index).**"
                return err_msg, current_passages_state

            target_paragraph_index = current_para_idx + 1
        else:
             logging.error(f"Invalid direction '{direction}' provided to load_more_context.")
             return format_context_markdown(current_passages_state, query_embedding_value), current_passages_state # Return unchanged


        # --- Fetch New Paragraph Data ---
        new_paragraph_sentences = []
        boundary_hit = False # Flag if we reached start/end of book/section
        new_passage_added = False # Flag if actual content was added/changed


        # Extract author/book from the boundary passage's metadata
        boundary_meta = boundary_passage.get('meta', {}) if boundary_passage else {}
        author = boundary_meta.get('author')
        book = boundary_meta.get('book')


        # Fetch if target index is valid and we have author/book context
        if target_paragraph_index >= 0 and author and book:
            logging.info(f"Attempting to load paragraph {target_paragraph_index} for {author}/{book}")
            new_paragraph_sentences = fetch_paragraph_data(author, book, target_paragraph_index)
            if not new_paragraph_sentences:
                # Successfully queried but found no sentences -> boundary hit
                boundary_hit = True
                logging.info(f"Boundary hit: No sentences found for paragraph {target_paragraph_index}.")
            else:
                # Successfully fetched new sentences
                new_passage_added = True
                logging.info(f"Successfully fetched {len(new_paragraph_sentences)} sentences for paragraph {target_paragraph_index}.")
        elif target_paragraph_index == -2:
             # Explicitly hit the start boundary based on index calculation
             boundary_hit = True
             logging.info("Boundary hit: Reached beginning (index <= 0).")
        else:
            # Invalid state (e.g., missing author/book on boundary passage)
            logging.error(f"Cannot load more context: Invalid target index ({target_paragraph_index}) or missing author/book from boundary passage {boundary_passage.get('id') if boundary_passage else 'N/A'}.")
            boundary_hit = True # Treat as boundary hit to potentially add marker


        # --- Update Passages State ---
        updated_passages = list(current_passages_state) # Create a mutable copy

        # Remove existing boundary markers before adding new content/markers
        updated_passages = [p for p in updated_passages if p.get('role') != 'missing']


        if new_passage_added:
            # Add the newly fetched sentences
            if add_at_beginning:
                updated_passages = new_paragraph_sentences + updated_passages # Prepend
            else:
                updated_passages.extend(new_paragraph_sentences) # Append
        # Only add boundary marker if new content wasn't added AND we hit a boundary
        # (or if it was a boundary hit but fetch_paragraph_data returned empty).
        # This prevents adding a boundary marker if the next paragraph exists but is empty,
        # unless we are at the absolute start/end (target_paragraph_index == -2 or the fetch returns empty).
        # Also ensure we don't add duplicate markers.
        if boundary_hit:
             if add_at_beginning: # Hit previous boundary
                 if not updated_passages or updated_passages[0].get('id') != START_MARKER_ID:
                     updated_passages.insert(0, {'id': START_MARKER_ID, 'paragraph_index': -1, 'role': 'missing', 'doc': '_(Anfang des Buches/Abschnitts)_', 'meta': {}, 'sentence_sort_key': float('-inf'), 'embedding': None})
                     # new_passage_added = True # Marker addition counts as change

             else: # Hit next boundary
                 if not updated_passages or updated_passages[-1].get('id') != END_MARKER_ID:
                     updated_passages.append({'id': END_MARKER_ID, 'paragraph_index': float('inf'), 'role': 'missing', 'doc': '_(Ende des Buches/Abschnitts)_', 'meta': {}, 'sentence_sort_key': float('inf'), 'embedding': None})
                     # new_passage_added = True # Marker addition counts as change


        # --- Reformat and Return ---
        # Reformat only if the content of `updated_passages` actually changed (new passage or marker added)
        # or if the original state had markers removed.
        # Compare length or check if new_passage_added or boundary_hit.
        content_changed = new_passage_added or (boundary_hit and len(updated_passages) != len(current_passages_state)) # Simple check for now

        if content_changed or not updated_passages: # Also reformat if state became empty
             # Ensure final list is sorted correctly including any added markers/paragraphs
             updated_passages.sort(key=lambda x: (x.get('paragraph_index', -1), x.get('sentence_sort_key', float('inf'))))
             logging.info(f"Reformatting context with {len(updated_passages)} total passages after loading more.")

             # Use the VALID query embedding passed into the function for consistent highlighting
             context_md = format_context_markdown(updated_passages, query_embedding_value)
             # Return the new Markdown and the updated state list
             return context_md, updated_passages
        else:
             # No new passage or boundary marker state change.
             # Reformat existing content just in case metadata/sorting needed fixing, return original state list
             logging.debug(f"Load Context: No change in passages or boundary marker state for direction '{direction}'. Reformatting existing state.")
             # Re-sort the original state list just in case, then format it.
             current_passages_state.sort(key=lambda x: (x.get('paragraph_index', -1), x.get('sentence_sort_key', float('inf'))))
             original_context_md = format_context_markdown(current_passages_state, query_embedding_value)
             # Return the reformatted original markdown and the original state list
             return original_context_md, current_passages_state


    except Exception as e:
        logging.error(f"Error loading more context (paragraph mode): {e}", exc_info=True)
        # Format existing content + error message, return original state
        error_message = format_context_markdown(current_passages_state or [], query_embedding_value) + f"\n\n**Fehler beim Laden des nächsten/vorherigen Paragraphen.**"
        return error_message, current_passages_state


# --- Load More Context Function ---
def load_more_context_wrapper(direction, current_passages_state, query_embedding_value):
    """Loads the previous or next paragraph in the reading view."""
    logging.info(f"Triggered: load_more_context_wrapper direction={direction}")
    # This function's outputs are only context_display and displayed_context_passages state.
    # It does NOT affect the overall UI layout or result list navigation buttons.
    output_components = [context_display, displayed_context_passages]
    try:
        context_md, updated_passages_state = load_more_context(direction, current_passages_state, query_embedding_value)
        # load_more_context returns a tuple (markdown_str, updated_state_list)
        # Map these directly to the output components
        updates_list = [
             gr.update(value=context_md), # update context_display
             updated_passages_state # update displayed_context_passages state
        ]
        logging.debug(f"load_more_context_wrapper: Returning {len(updates_list)} updates.")
        return updates_list
    except Exception as e:
        logging.error(f"Error in load_more_context wrapper: {e}", exc_info=True)
        # On error, return error message and original state
        error_md = format_context_markdown(current_passages_state or [], query_embedding_value) + f"\n\n**Fehler beim Laden des nächsten/vorherigen Paragraphen.**"
        updates_list = [
             gr.update(value=error_md),
             current_passages_state # Return original state on error
        ]
        return updates_list


# --- Modified _on_fav function ---
# This function is triggered by the hidden button click via api_name
# It expects the passage_id as its argument, provided by the JS Client API predict call.
def _on_fav(passage_id): # Removed type hint str for debugging
    """Handles favourite signal from JS, only increments and updates status."""
    # Log the type and value of the received argument
    logging.info(f"Triggered: _on_fav with received argument: {passage_id!r} (Type: {type(passage_id)})")

    updates_dict = {
        fav_signal: gr.update(value=""), # Always clear the signal textbox after processing
        status_message: gr.update(visible=False, value="") # Clear status initially
    }

    # Check if passage_id is a non-empty string
    if not isinstance(passage_id, str) or not passage_id.strip():
        logging.warning(f"_on_fav called with invalid passage_id: {passage_id!r}.")
        updates_dict[status_message] = gr.update(visible=True, value="**Fehler:** Ungültige Favoriten-ID erhalten.")
        return updates_dict # Return the updates dictionary

    try:
        # Call the core logic to increment the favourite score
        new_score = inc_favourite(passage_id) # Use the valid passage_id string
        logging.info(f"Successfully incremented favourite for ID {passage_id}. New score: {new_score}")
        # Update the status message to inform the user
        updates_dict[status_message] = gr.update(visible=True, value=f"⭐ Favorit gespeichert! (Score: {new_score})")
    except Exception as e:
        logging.error(f"Error in _on_fav processing ID {passage_id}: {e}", exc_info=True)
        # Update status message with error info
        updates_dict[status_message] = gr.update(visible=True, value=f"**Fehler beim Speichern des Favoriten:** {e}")

    # This function returns a dictionary of updates for its bound outputs.
    # These are just the fav_signal state (to reset it) and the status_message UI element.
    return updates_dict


js_code = """
// ------------------------------------------------------------
//  FAVOURITE HANDLER  (uses Gradio JS Client predict endpoint)
// ------------------------------------------------------------
let gradioApp = null;           // will hold the connected client
const ENDPOINT = "/fav";         // same name you set in api_name
const STATUS_SEL = '#status-message'; // Selector for the markdown status element
// const FAV_SIGNAL_ID = 'fav-signal'; // No longer directly interacting with fav-signal textbox from JS click handler
// const DEBUG_ID_SEL = '#clicked-id-debug input'; // Original selector
// const DEBUG_ELEM_ID = 'clicked-id-debug'; // The elem_id for the debug textbox container <--- REMOVE THIS

// 1 ‒ connect once, then re‑use
async function initializeFavClient() {
    console.log("JS: Initializing fav client…");
    try {
        // Assuming Client is made global by the <script type="module"> tag in head
        if (typeof Client === "undefined") {
            console.error("JS: window.Client not defined (script order?)");
            return;
        }
        gradioApp = await Client.connect(window.location.origin);
        console.log("JS: Gradio Client connected.");

    } catch (e) {
        console.error("JS: Could not connect:", e);
    }
}
setTimeout(initializeFavClient, 100); // Initialize client after a short delay

// Basic HTML escape function for safety in JS error display
function htmlEscape(str) {
    return str.replace(/&/g, '&amp;')
              .replace(/</g, '&lt;')
              .replace(/>/g, '&gt;')
              .replace(/"/g, '&quot;')
              .replace(/'/g, '&#039;');
}


// 2 ‒ call backend when user clicks a sentence
async function gradio_fav(id) {
    const statusEl = document.querySelector(STATUS_SEL);
    if (statusEl) {
        statusEl.style.display = ''; // Make visible
        statusEl.innerHTML = "Speichere Favorit…"; // Set loading message using innerHTML
    }
    console.log(`JS: Calling backend ${ENDPOINT} with ID: ${id}`); // Log before calling predict

    if (!gradioApp) {
        console.warn("JS: client not ready yet for /fav call.");
        if (statusEl) statusEl.innerHTML = "**Fehler:** Gradio Client nicht verbunden.";
        return;
    }
    try {
        // Pass the ID as a string in an array - matches backend inputs=[fav_signal]
        const res = await gradioApp.predict(ENDPOINT, [String(id)]);
        console.log(`JS: ${ENDPOINT} predict call response:`, res); // Log the full response

        // Expected response structure from _on_fav is [updated_fav_signal_value, updated_status_message_value]
        // We only care about the status message update
        const msg = res?.data?.[1]?.value ?? "⭐ Favorit gespeichert!"; // Get the updated value for status_message (index 1)
        const is_status_visible = res?.data?.[1]?.visible ?? true; // Check if status should be visible

        if (statusEl) {
            statusEl.innerHTML = msg;
            statusEl.style.display = is_status_visible ? '' : 'none'; // Set visibility
        }

    } catch (e) {
        console.error(`JS: backend ${ENDPOINT} error:`, e);
        // Attempt to get a more specific error message if available
        let errorMsg = "Unbekannter Fehler";
        if (e && typeof e === 'object' && e.message) {
            errorMsg = e.message;
        } else if (typeof e === 'string') {
            errorMsg = e;
        } else if (e && typeof e === 'object' && e.name) {
             errorMsg = `${e.name}: ${errorMsg}`;
        } else if (e && typeof e === 'object' && e.stack) {
             errorMsg = `${errorMsg} (See console for stack trace)`;
        }

        if (statusEl) {
            statusEl.style.display = ''; // Make visible
            statusEl.innerHTML = `**Fehler:** ${htmlEscape(errorMsg)}`; // Escape error message for safety
        }
    }
}

// 3 ‒ delegate clicks on any span.clickable‑sentence
document.addEventListener("click", ev => {
    const span = ev.target.closest("span.clickable-sentence[data-id]");
    if (!span) return; // Not a clickable sentence

    const passageId = span.dataset.id; // Get the ID from the data attribute
    console.log(`JS: Clicked sentence. Found data-id: ${passageId}`); // Log the found ID

    // --- DEBUG: Update debug textbox ---
    // REMOVE ALL THE DEBUG TEXTBOX JS CODE FROM HERE
    // const debugElement = document.getElementById(DEBUG_ELEM_ID); // Get element by elem_id
    // let clickedIdDebugInput = null;
    // ... rest of debug js code ...
    // --- END DEBUG ---


    if (passageId && String(passageId).trim() !== '' && String(passageId) !== 'undefined' && String(passageId) !== 'null') {
        gradio_fav(passageId); // Call the function with the ID (as string)
    } else {
        console.warn("JS: Clickable span found, but missing or empty data-id attribute.");
    }
});
"""


# --- Gradio UI Definition ---
# Pass the JavaScript code and Custom CSS to the 'head' and 'css' parameters of gr.Blocks
custom_css = """
/* Style for clickable sentences */
span.clickable-sentence {
    cursor: pointer; /* Ensure pointer cursor */
}

/* Style for highlighted sentences (base style) */
/* Uses a CSS variable for dynamic alpha */
span.clickable-sentence.highlighted { /* Target the single span when it has both classes */
    /* Base highlight color using the dynamic alpha variable */
    background-color: hsla(var(--highlight-hue, 60), var(--highlight-saturation, 100%), var(--highlight-lightness, 90%), var(--highlight-alpha));
    /* Fixed styles for highlighting shape */
    padding: 1px 3px;
    border-radius: 3px;
    /* Prevents highlight from breaking awkwardly across lines */
    box-decoration-break: clone;
    -webkit-box-decoration-break: clone; /* For older WebKit browsers */
}


/* Style for sentences on hover (applies to ALL clickable spans, highlighted or not) */
/* This rule has higher specificity than span.clickable-sentence.highlighted */
span.clickable-sentence:hover {
    /* Hover background color - this will override the base highlight color */
    background-color: hsla(60, 100%, 70%, 0.8); /* Yellow-ish, more opaque */
    transition: background-color 0.2s ease; /* Smooth transition */
}


/* Style for the status message to make it stand out */
#status-message {
    margin-top: 10px; /* Space above the message */
    padding: 8px; /* Padding inside the message box */
    border-radius: 5px; /* Rounded corners */
    background-color: #fff3cd; /* Light yellow background (for info/success) */
    color: #664d03; /* Dark yellow text */
    border: 1px solid #ffecb5; /* Yellow border */
    visibility: visible; /* Make it visible initially */
    opacity: 1; /* Fully opaque */
    transition: opacity 0.5s ease-in-out; /* Fade effect */
}

/* Style for error status message */
#status-message strong {
    color: #842029; /* Dark red for errors */
}
/* You could add data-error="true" using JS/Gradio update for specific error styling */
/* #status-message[data-error="true"] {
    background-color: #f8d7da;
    color: #721c24;
    border-color: #f5c6cb;
} */
"""

with gr.Blocks(theme = gr.themes.Default(
    primary_hue="yellow",
    secondary_hue="blue",
    text_size="lg",
    spacing_size="md",
    radius_size="md",
),
                head=f"""
    <script type="module">
    import {{ Client as GradioClient }} from
      "https://cdn.jsdelivr.net/npm/@gradio/client/dist/index.min.js";
    window.Client = GradioClient;                      // expose for the page
    </script>

    <script>
    {js_code}
    </script>
                """,
                css=custom_css # Add the custom CSS here
               ) as demo:

    gr.Markdown("# Thought Loop")
    gr.Markdown("Semantische Suche")

    # --- State Variables ---
    full_search_results_state = gr.State([]) # Stores results from Standard search
    current_result_index_state = gr.State(0) # Index for Standard search results
    llm_results_state = gr.State([])         # Stores results from LLM search
    llm_result_index_state = gr.State(0)     # Index for LLM search results
    best_results_state = gr.State([])        # Stores results from Favourites view
    best_index_state = gr.State(0)         # Index for Favourites results

    displayed_context_passages = gr.State([]) # Stores passages currently in context view
    # active_view_state tracks which view is active:
    # "standard", "llm", "favourites", "context_from_standard", "context_from_llm", "context_from_favourites", "none"
    active_view_state = gr.State("none")
    # Holds the query embedding for highlighting in the context view.
    # Needs to be passed through UI events that transition *to* the context view.
    direct_embedding_output_holder = gr.State(None)

    # --- UI Layout ---
    with gr.Row():
        query_input = gr.Textbox(label="Gedanken eingeben", placeholder="Sollte Technologie nicht zu immer krasserer Arbeitsteilung führen, sodass wir in Zukunft...", lines=2, scale=4)
        author_dropdown = gr.Dropdown(label="Autoren auswählen (optional)", choices=unique_authors, multiselect=True, scale=2)

    with gr.Accordion("Feinabstimmung Rankierung", open=False) as result_tuning_accordion:
        with gr.Row():
            window_size_slider = gr.Slider(
                minimum=0, maximum=5, step=1, value=RERANK_WINDOW_SIZE,
                label="Kontext-Fenstergröße (+/- Sätze)",
                info="Wie viele Sätze vor/nach dem Treffer-Satz für Kontext-Score & Anzeige berücksichtigt werden (0-5)."
            )
            weight_slider = gr.Slider(
                minimum=0.0, maximum=1.0, step=0.05, value=RERANK_WEIGHT,
                label="Kontext-Gewichtung",
                info="Wie stark der Kontext-Score das ursprüngliche Ranking beeinflusst (0.0 = kein Einfluss, 1.0 = stark)."
            )
            decay_slider = gr.Slider(
                minimum=0.0, maximum=1.0, step=0.05, value=RERANK_DECAY,
                label="Kontext-Abfallfaktor",
                info="Wie schnell der Einfluss von Nachbarn mit der Distanz abnimmt (0.0 = kein Abfall, 1.0 = stark)."
            )

    with gr.Row():
        search_button = gr.Button("Embeddingsuche", variant="secondary", scale=1)
        llm_rerank_button = gr.Button("Embeddingsuche + LLM Auswahl", variant="secondary", scale=1, interactive=(API_KEY is not None and llm_rerank_model is not None))
        best_of_button     = gr.Button("⭐⭐⭐", variant="secondary", scale=1)

    # --- Shared Results/Favourites Area ---
    # We reuse standard_nav_row and single_result_group for all result types
    with gr.Row(visible=False) as standard_nav_row:
        # These buttons will be shown/hidden based on active_view_state
        previous_result_button = gr.Button("⬅️", min_width=80, visible=False) # General Previous
        next_result_button = gr.Button("➡️", min_width=80, visible=False) # General Next
        weiterlesen_button = gr.Button("weiterlesen", variant="secondary", visible=False) # General Weiterlesen

    with gr.Group(visible=False) as single_result_group:
        # MODIFIED: Replaced single_result_display_md with an Accordion and a Textbox
        result_accordion = gr.Accordion(label="Feinabstimmung", open=False) # Accordion for heading and metadata
        with result_accordion:
            # The content of the accordion will be a Markdown component
            result_metadata_display = gr.Markdown("...") # Placeholder for metadata and scores

        # This Textbox will contain the actual passage text
        result_text = gr.Textbox(label="", lines=5, interactive=False, visible=True)


    # --- Status Message Area ---
    # Added elem_id for JS to target
    status_message = gr.Markdown("", visible=False, elem_id="status-message") # Changed to visible=False initially

    # --- Hidden Signaling Components ---
    # Hidden textbox to hold the ID (will be used as input in client API call)
    # JS click handler now uses the client API directly, no longer sets this textbox value
    # This component's *value* is still used as an output by _on_fav to reset it.
    fav_signal = gr.Textbox(
        visible=False,
        elem_id="fav-signal", # Still useful for potential future JS interactions or debugging
        value="" # Initialize with empty value
    )
    # Hidden button triggered by JS (used to expose the backend function via its api_name binding)
    # The Client API calls the function bound to the api_name, not the button's click *event*.
    # This button component is mainly here to provide a place for the api_name binding.
    fav_trigger_button = gr.Button(
        visible=False,
        elem_id="fav-trigger-button" # Still useful for JS to get a reference if needed, though not clicked directly anymore
    )

    # --- Reading Area ---
    with gr.Column(visible=False) as context_area:
        back_to_results_button = gr.Button("⬅️ Zurück ", variant="secondary", visible=False)
        load_previous_button = gr.Button("⬆️", variant="secondary", visible=False) # Added text
        # --- MODIFIED: Added elem_id to context_display ---
        context_display = gr.HTML(label="Lesebereich", value="<div>_Kontext wird hier angezeigt._</div>", elem_id="context-display-markdown") # gr.HTML needs valid HTML, so wrap placeholder in div
        load_next_button = gr.Button("⬇️", variant="secondary", visible=False) # Added text

     # --- Utility function to create a reset update dictionary ---
    # This function needs to be defined AFTER all the components it references
    def create_reset_updates():
        """Creates a dictionary of Gradio updates to reset the UI and state."""
        updates = {}
        # List all components that need resetting/hiding, *excluding* the sliders and the Accordion content display
        components_to_reset = [
            # States
            full_search_results_state, current_result_index_state, displayed_context_passages,
            llm_results_state, llm_result_index_state, active_view_state,
            direct_embedding_output_holder,
            best_results_state, best_index_state,
            fav_signal, # <-- Included here as a state to reset its value
            # Shared Result UI - Containers
            standard_nav_row, single_result_group,
            # Shared Result UI - New Components
            result_accordion, result_metadata_display, result_text,
            # Tuning Accordion 
            result_tuning_accordion,
            # Buttons in shared row
            previous_result_button, next_result_button, weiterlesen_button,
            # Context Area UI
            context_area, context_display, load_previous_button, load_next_button,
            back_to_results_button,
            # Status message
            status_message,
             # fav_trigger_button is intentionally excluded here as its visibility/interactivity isn't controlled by this reset.
        ]

        for comp in components_to_reset:
             if isinstance(comp, gr.State):
                 if comp in [current_result_index_state, llm_result_index_state, best_index_state]: updates[comp] = 0
                 elif comp == active_view_state: updates[comp] = "none"
                 elif comp == direct_embedding_output_holder: updates[comp] = None
                 # Note: fav_signal state value is reset below explicitly
                 elif comp in [full_search_results_state, displayed_context_passages, llm_results_state, best_results_state]: updates[comp] = []
             else: # UI Components
                 if isinstance(comp, gr.Markdown):
                     updates[comp] = gr.update(value="") # Clear Markdown content
                 elif isinstance(comp, gr.HTML):
                     updates[comp] = gr.update(value="<div>_Kontext wird hier angezeigt._</div>") # Reset HTML content
                 elif isinstance(comp, gr.Textbox): # Handle Textboxes
                     # result_text needs value reset, visibility handled by single_result_group
                     if comp == result_text:
                         updates[comp] = gr.update(value="", interactive=False) # Keep interactive=False for results view
                     # fav_signal needs value reset AND explicit visibility set to False
                     elif comp == fav_signal:
                         updates[comp] = gr.update(value="", visible=False)
                     # Add any other Textboxes here if needed


                 elif isinstance(comp, gr.Accordion): # New Accordion
                     updates[comp] = gr.update(label="Feinabstimmung", open=False, visible=True) # Reset label, close, keep visible. Visibility controlled by single_result_group.

                 if isinstance(comp, (gr.Row, gr.Group, gr.Column)):
                     # Keep tuning accordion open/visible (Accordion itself isn't in this list, but its contents are)
                     if comp not in []: # Add any other components that should NOT be hidden here
                          updates[comp] = gr.update(visible=False)


                 if isinstance(comp, gr.Button):
                     updates[comp] = gr.update(visible=False, interactive=False)

                 if comp == status_message:
                     updates[comp] = gr.update(value="", visible=False)


        # Explicitly set tuning sliders to be visible and interactive on reset,
        # but *don't* reset their values here. Their current values will be retained.
        # These sliders are NOT included in the components_to_reset list above,
        # so they won't be affected by the generic hide logic.
        updates[window_size_slider] = gr.update(visible=True, interactive=True)
        updates[weight_slider] = gr.update(visible=True, interactive=True)
        updates[decay_slider] = gr.update(visible=True, interactive=True)

        # The result_metadata_display (inside the accordion) also needs resetting
        updates[result_metadata_display] = gr.update(value="...")


        logging.debug(f"Created reset updates dict with {len(updates)} items.")
        return updates

    
    # --- Wrapper Functions for Gradio Bindings ---
    # These wrappers prepare the inputs and outputs for the Gradio event handlers.
    # They return a dictionary of updates which is then converted to a list by Gradio.

    def search_standard_wrapper(query, selected_authors, window_size, weight, decay):
        logging.info(f"Triggered: search_standard_wrapper with window={window_size}, weight={weight:.2f}, decay={decay:.2f}")
        # Start with a reset state (Includes hiding context area and its buttons)
        updates_dict = create_reset_updates()
        try:
            search_results, query_embedding, error = perform_search_standard(
                query, selected_authors,
                window_size, weight, decay
            )
            # Merge updates from the mode-specific UI function (Shows results area)
            # search_standard_mode_ui now handles updating the new components
            updates_dict.update(search_standard_mode_ui(search_results, query_embedding, error))
        except Exception as e:
            logging.error(f"Error in search_standard_wrapper: {e}", exc_info=True)
            # MODIFIED: Update the new components on error
            updates_dict[result_accordion] = gr.update(label=f"**Fehler bei der Suche:**", open=False, visible=True)
            updates_dict[result_metadata_display] = gr.update(value=str(e)) # Display error message in metadata area
            updates_dict[result_text] = gr.update(value="", visible=True)
            updates_dict[single_result_group] = gr.update(visible=True) # Ensure the result group is visible
            updates_dict[direct_embedding_output_holder] = None

        # --- FIX: Ensure context area and its buttons are hidden when showing search results ---
        # Although create_reset_updates is called, add explicit updates for robustness
        updates_dict[context_area] = gr.update(visible=False)
        updates_dict[load_previous_button] = gr.update(visible=False)
        updates_dict[load_next_button] = gr.update(visible=False)
        updates_dict[back_to_results_button] = gr.update(visible=False)
        # --- END FIX ---


        # Return the dictionary of updates
        return updates_dict

    def search_llm_rerank_wrapper(query, selected_authors, window_size, weight, decay):
        logging.info(f"Triggered: search_llm_rerank_wrapper with window={window_size}, weight={weight:.2f}, decay={decay:.2f}")
        # Start with a reset state (Includes hiding context area and its buttons)
        updates_dict = create_reset_updates()
        try:
            llm_results, query_embedding, error = perform_search_llm(
                query, selected_authors,
                window_size, weight, decay
            )
            # Merge updates from the mode-specific UI function (Shows LLM results area)
            # search_llm_rerank_mode_ui now handles updating the new components
            updates_dict.update(search_llm_rerank_mode_ui(llm_results, query_embedding, error))
        except Exception as e:
            logging.error(f"Error in search_llm_rerank_wrapper: {e}", exc_info=True)
            # MODIFIED: Update the new components on error
            updates_dict[result_accordion] = gr.update(label=f"**Fehler bei der LLM-Suche:**", open=False, visible=True)
            updates_dict[result_metadata_display] = gr.update(value=str(e)) # Display error message
            updates_dict[result_text] = gr.update(value="", visible=True)
            updates_dict[single_result_group] = gr.update(visible=True) # Ensure group is visible
            updates_dict[direct_embedding_output_holder] = None


        # --- FIX: Ensure context area and its buttons are hidden when showing LLM results ---
        # Although create_reset_updates is called, add explicit updates for robustness
        updates_dict[context_area] = gr.update(visible=False)
        updates_dict[load_previous_button] = gr.update(visible=False)
        updates_dict[load_next_button] = gr.update(visible=False)
        updates_dict[back_to_results_button] = gr.update(visible=False)
        # --- END FIX ---

        # Return the dictionary of updates
        return updates_dict

    def refresh_best_wrapper():
        """Wrapper for _refresh_best to prepare UI updates."""
        logging.info("Triggered: refresh_best_wrapper")
        # Start with a reset state (Includes hiding context area and its buttons)
        updates_dict = create_reset_updates()
        # Ensure status message is hidden on view change
        updates_dict[status_message] = gr.update(value="", visible=False)
        try:
            favs = top_favourites(MAX_FAVOURITES)
            if not favs:
                logging.info("No favourites to display.")
                # MODIFIED: Update the new components for no results
                updates_dict[result_accordion] = gr.update(label="_Noch keine Favoriten gesammelt.", open=False, visible=True)
                updates_dict[result_metadata_display] = gr.update(value="")
                updates_dict[result_text] = gr.update(value="", visible=True)
                updates_dict[single_result_group] = gr.update(visible=True) # Ensure group is visible
                updates_dict[best_results_state] = []
                updates_dict[best_index_state] = 0
                updates_dict[active_view_state] = "favourites" # Set view even if empty

            else:
                logging.info(f"Displaying first of {len(favs)} favourite results.")
                # format_result_display returns (accordion_title, accordion_content_md, text_content)
                accordion_title, accordion_content_md, text_content = format_result_display(favs[0], 0, len(favs), "favourites")

                # MODIFIED: Update the new components with formatted data
                updates_dict[result_accordion] = gr.update(label=accordion_title, open=False, visible=True)
                updates_dict[result_metadata_display] = gr.update(value=accordion_content_md)
                updates_dict[result_text] = gr.update(value=text_content, visible=True)

                updates_dict[single_result_group] = gr.update(visible=True) # Ensure group is visible
                updates_dict[standard_nav_row] = gr.update(visible=True)
                updates_dict[previous_result_button] = gr.update(visible=True, interactive=False) # First result is not navigable prev
                updates_dict[next_result_button] = gr.update(visible=True, interactive=(len(favs) > 1)) # Enable if more than one fav
                updates_dict[weiterlesen_button] = gr.update(visible=True, interactive=True, value="weiterlesen") # Enable context button
                updates_dict[best_results_state] = favs
                updates_dict[best_index_state] = 0
                updates_dict[active_view_state] = "favourites" # Set active view state



        except Exception as e:
            logging.error(f"Error in refresh_best_wrapper: {e}", exc_info=True)
            # MODIFIED: Update the new components on error
            updates_dict[result_accordion] = gr.update(label=f"**Fehler beim Laden der Favoriten:**", open=False, visible=True)
            updates_dict[result_metadata_display] = gr.update(value=str(e)) # Display error message
            updates_dict[result_text] = gr.update(value="", visible=True)
            updates_dict[single_result_group] = gr.update(visible=True) # Ensure group is visible
            updates_dict[best_results_state] = []
            updates_dict[best_index_state] = 0
            updates_dict[active_view_state] = "none" # Indicate error state

        # --- FIX: Ensure context area and its buttons are hidden when showing Favourites ---
        # Although create_reset_updates is called, add explicit updates for robustness
        updates_dict[context_area] = gr.update(visible=False)
        updates_dict[load_previous_button] = gr.update(visible=False)
        updates_dict[load_next_button] = gr.update(visible=False)
        updates_dict[back_to_results_button] = gr.update(visible=False)
        # --- END FIX ---


        # Return the dictionary of updates
        return updates_dict

    def navigate_results_wrapper(direction, current_index, full_results, llm_results, llm_index, best_results, best_index, active_view):
        logging.info(f"Triggered: navigate_results_wrapper direction={direction}, active_view={active_view}")

        updates_dict = {
             # Default updates to preserve relevant state based on active view
            full_search_results_state: full_results,
            current_result_index_state: current_index,
            llm_results_state: llm_results,
            llm_result_index_state: llm_index,
            best_results_state: best_results,
            best_index_state: best_index,
            active_view_state: active_view, # Preserve active view

            # MODIFIED: Clear new components when navigating (before displaying the next one)
            result_accordion: gr.update(label="...", open=False, visible=True),
            result_metadata_display: gr.update(value=""),
            result_text: gr.update(value="", visible=True),
        }

        try:
            if active_view == "standard":
                # navigate_results now updates the new components directly
                nav_updates = navigate_results(direction, current_index, full_results)
                updates_dict.update(nav_updates)
            elif active_view == "llm":
                 # navigate_llm_results now updates the new components directly
                 nav_updates = navigate_llm_results(direction, llm_index, llm_results)
                 updates_dict.update(nav_updates)
            elif active_view == "favourites":
                 # navigate_best_results now updates the new components directly
                 nav_updates = navigate_best_results(direction, best_index, best_results)
                 updates_dict.update(nav_updates)
            else:
                 logging.warning(f"Navigation triggered in unexpected view state: {active_view}")
                 # MODIFIED: Update new components on error
                 updates_dict[result_accordion] = gr.update(label="Navigation nicht möglich.", open=False, visible=True)
                 updates_dict[result_metadata_display] = gr.update(value="Ungültiger Status.")
                 updates_dict[result_text] = gr.update(value="", visible=True)
                 # Hide nav buttons as navigation is not possible
                 updates_dict[previous_result_button] = gr.update(interactive=False)
                 updates_dict[next_result_button] = gr.update(interactive=False)
                 updates_dict[weiterlesen_button] = gr.update(interactive=False)


        except Exception as e:
            logging.error(f"Error in navigation wrapper: {e}", exc_info=True)
            # MODIFIED: Update new components on error
            updates_dict[result_accordion] = gr.update(label=f"**Navigationsfehler:**", open=False, visible=True)
            updates_dict[result_metadata_display] = gr.update(value=str(e))
            updates_dict[result_text] = gr.update(value="", visible=True)
            # On error, disable navigation buttons
            updates_dict[previous_result_button] = gr.update(interactive=False)
            updates_dict[next_result_button] = gr.update(interactive=False)
            updates_dict[weiterlesen_button] = gr.update(interactive=False)


        # Return the dictionary of updates
        # Note: The individual navigate_* functions within the try/except
        # already populate the updates_dict with the specifics.
        # We just handle the top-level error/unexpected state here.
        return updates_dict


    def go_back_to_results_wrapper(last_active_view, std_results, std_index, llm_results, llm_index, best_results, best_index, current_fav_signal_value, query_embedding_value):
        """Handles UI updates for returning from the context view to the appropriate results view."""
        logging.info(f"Triggered: go_back_to_results_wrapper from view: {last_active_view}")

        updates_dict = {
            # Reset context area visibility
            context_area: gr.update(visible=False),
            context_display: gr.update(value=""), # Clear context display
            displayed_context_passages: [], # Reset context state

            # Pass through existing results and indices states
            full_search_results_state: std_results, current_result_index_state: std_index,
            llm_results_state: llm_results, llm_result_index_state: llm_index,
            best_results_state: best_results, best_index_state: best_index,
            # Keep the query embedding alive: it belongs to the current search, not to a
            # single visit of the reading area. Clearing it here disabled the highlighting
            # for every paragraph opened after the first one.
            direct_embedding_output_holder: query_embedding_value,
            fav_signal: gr.update(value=current_fav_signal_value), # <--- Pass through fav_signal state
            active_view_state: "none", # Reset active view temporarily before setting correct one

            # Ensure the new result components are initially hidden when returning
            result_accordion: gr.update(label="Feinabstimmung", open=False, visible=False),
            result_metadata_display: gr.update(value=""),
            result_text: gr.update(value="", visible=False),

            # Ensure shared result row and group are initially hidden
            standard_nav_row: gr.update(visible=False),
            single_result_group: gr.update(visible=False),

            # Also ensure all result nav buttons are hidden initially
            previous_result_button: gr.update(visible=False, interactive=False),
            next_result_button: gr.update(visible=False, interactive=False),
            weiterlesen_button: gr.update(visible=False, interactive=False),
        }
        # Hide status message
        updates_dict[status_message] = gr.update(value="", visible=False)


        # Determine which result view to show based on where we came from
        target_view = "none"
        target_results_list = []
        target_index = 0
        result_type = "unknown" # Used for formatting

        if last_active_view == "context_from_standard":
            target_view = "standard"
            target_results_list = std_results
            target_index = std_index
            result_type = "standard"
            logging.info("Going back to Standard results.")
        elif last_active_view == "context_from_llm":
            target_view = "llm"
            target_results_list = llm_results
            target_index = llm_index
            result_type = "llm"
            logging.info("Going back to LLM results.")
        elif last_active_view == "context_from_favourites":
             target_view = "favourites"
             target_results_list = best_results
             target_index = best_index
             result_type = "favourites"
             logging.info("Going back to Favourites.")
        else:
            logging.warning(f"Back button triggered from unexpected state: {last_active_view}")
            # Default to showing an error message if view is unknown
            updates_dict[result_accordion] = gr.update(label="Zurück aus unbekanntem Zustand.", open=False, visible=True)
            updates_dict[result_metadata_display] = gr.update(value="Resultate konnten nicht geladen werden.")
            updates_dict[result_text] = gr.update(value="", visible=True)
            updates_dict[single_result_group] = gr.update(visible=True) # Ensure group is visible
            updates_dict[standard_nav_row] = gr.update(visible=True) # Ensure nav row is visible (even if buttons are hidden)
            target_view = "none" # Stay in error state
            return updates_dict # Return early on error


        # Update the active_view state to the results view we returned to
        updates_dict[active_view_state] = target_view

        # Show the shared result group and nav row
        updates_dict[single_result_group] = gr.update(visible=True)
        updates_dict[standard_nav_row] = gr.update(visible=True)


        # Update the result display and navigation buttons for the target view
        if target_results_list and isinstance(target_results_list, list) and 0 <= target_index < len(target_results_list):
             result_data = target_results_list[target_index]
             # MODIFIED: Use the combined formatter and update new components
             accordion_title, accordion_content_md, text_content = format_result_display(result_data, target_index, len(target_results_list), result_type)
             updates_dict[result_accordion] = gr.update(visible=True, label=accordion_title, open=False)
             updates_dict[result_metadata_display] = gr.update(value=accordion_content_md)
             updates_dict[result_text] = gr.update(value=text_content, visible=True)

             # Update button interactivity based on the selected index and total results
             updates_dict[previous_result_button] = gr.update(visible=True, interactive=(target_index > 0))
             updates_dict[next_result_button] = gr.update(visible=True, interactive=(target_index < len(target_results_list) - 1))
             updates_dict[weiterlesen_button] = gr.update(visible=True, interactive=True, value="weiterlesen" if result_type != "llm" else "im Original weiterlesen")

        else:
             # If the result list is empty or invalid after returning, show appropriate message
             error_msg_label = f"_{target_view.capitalize()}-Resultate nicht verfügbar._"
             error_msg_content = "" # No content for metadata
             updates_dict[result_accordion] = gr.update(visible=True, label=error_msg_label, open=False)
             updates_dict[result_metadata_display] = gr.update(value=error_msg_content)
             updates_dict[result_text] = gr.update(value="", visible=True) # Clear text area

             # Hide navigation buttons as there are no results to navigate
             updates_dict[previous_result_button] = gr.update(visible=False, interactive=False)
             updates_dict[next_result_button] = gr.update(visible=False, interactive=False)
             updates_dict[weiterlesen_button] = gr.update(visible=False, interactive=False)

        return updates_dict


    def move_to_reading_wrapper(std_results, std_index, llm_results, llm_index, best_results, best_index, active_view, query_embedding_value, current_fav_signal_value):
        logging.info(f"Triggered: move_to_reading_wrapper active_view={active_view}")

        updates_dict = {
            # Preserve all state variables by default
            full_search_results_state: std_results, current_result_index_state: std_index,
            llm_results_state: llm_results, llm_result_index_state: llm_index,
            best_results_state: best_results, best_index_state: best_index,
            active_view_state: active_view, # Preserve active view temporarily
            direct_embedding_output_holder: query_embedding_value,
            fav_signal: gr.update(value=current_fav_signal_value) # <--- Pass through fav_signal state
        }
        # Hide status message when changing view
        updates_dict[status_message] = gr.update(value="", visible=False)


        try:
            target_results_list = []
            target_index = 0
            result_type = "unknown"

            # Identify which result list and index to use based on active_view
            if active_view == "standard":
                target_results_list = std_results
                target_index = std_index
                result_type = "standard"
            elif active_view == "llm":
                target_results_list = llm_results
                target_index = llm_index
                result_type = "llm"
            elif active_view == "favourites":
                target_results_list = best_results
                target_index = best_index
                result_type = "favourites"
            else:
                logging.warning(f"Weiterlesen triggered in unexpected view state: {active_view}")
                updates_dict[context_display] = gr.update(value="Kann Kontext in diesem Zustand nicht laden.")
                updates_dict[context_area] = gr.update(visible=True)
                updates_dict[load_previous_button] = gr.update(interactive=False)
                updates_dict[load_next_button] = gr.update(interactive=False)
                updates_dict[back_to_results_button] = gr.update(visible=True, interactive=True)
                updates_dict[active_view_state] = "none" # Indicate an error/transition state
                return updates_dict # Return early on error

            # Call the UI function that fetches and formats the initial context
            # Pass only the data it needs (index within the target list, the list itself, embedding, and type)
            # The move_to_reading_area_ui function should return a dictionary of updates for UI components like context_display and displayed_context_passages state
            read_updates = move_to_reading_area_ui(target_index, target_results_list, query_embedding_value, result_type)

            # Update the active_view state to reflect entering context mode
            # This state will be used by load_more and back buttons
            updates_dict[active_view_state] = f"context_from_{result_type}"

            # Merge the UI updates returned by move_to_reading_area_ui
            updates_dict.update(read_updates)


        except Exception as e:
            logging.error(f"Error in move_to_reading wrapper: {e}", exc_info=True)
            updates_dict[context_display] = gr.update(value=f"**Fehler:** Konnte Paragraph nicht in Lesebereich laden: {e}")
            updates_dict[context_area] = gr.update(visible=True)
            updates_dict[load_previous_button] = gr.update(interactive=False)
            updates_dict[load_next_button] = gr.update(interactive=False)
            updates_dict[back_to_results_button] = gr.update(visible=True, interactive=True)
            updates_dict[active_view_state] = "error_context" # Indicate an error state


        return updates_dict


    # This wrapper function remains the same, it's bound to load_previous_button and load_next_button
    def load_more_context_wrapper(direction, current_passages_state, query_embedding_value):
        logging.info(f"Triggered: load_more_context_wrapper direction={direction}")
        # This function's outputs are only context_display and displayed_context_passages state.
        # It does NOT affect the overall UI layout or result list navigation buttons.
        output_components = [context_display, displayed_context_passages]
        try:
            context_md, updated_passages_state = load_more_context(direction, current_passages_state, query_embedding_value)
            # load_more_context returns a tuple (markdown_str, updated_state_list)
            # Map these directly to the output components
            updates_list = [
                 gr.update(value=context_md), # update context_display
                 updated_passages_state # update displayed_context_passages state
            ]
            logging.debug(f"load_more_context_wrapper: Returning {len(updates_list)} updates.")
            return updates_list
        except Exception as e:
            logging.error(f"Error in load_more_context wrapper: {e}", exc_info=True)
            # On error, return error message and original state
            error_md = format_context_markdown(current_passages_state or [], query_embedding_value) + f"\n\n**Fehler beim Laden des nächsten/vorherigen Paragraphen.**"
            updates_list = [
                 gr.update(value=error_md),
                 current_passages_state # Return original state on error
            ]
            return updates_list


     # --- Define the combined list of all potential UI outputs ---
    # This list is needed for functions that can trigger updates across multiple parts of the UI.
    # We add the direct_embedding_output_holder state as well.
    # fav_trigger_button is NOT in this list because it's strictly
    # a hidden signaling component updated only by the fav logic binding's outputs.
    # This list needs to be defined AFTER all components are defined in the Blocks context
    all_ui_outputs = [
        # States
        full_search_results_state, current_result_index_state, displayed_context_passages,
        llm_results_state, llm_result_index_state, active_view_state,
        direct_embedding_output_holder,
        best_results_state, best_index_state,
        fav_signal,
        # Shared Result UI Containers
        standard_nav_row, single_result_group,
        # MODIFIED: New Result UI Components
        result_accordion, result_metadata_display, result_text,
        # Tuning Accordion
        result_tuning_accordion,
        # Buttons in shared row
        previous_result_button, next_result_button, weiterlesen_button,
        # Context Area UI
        context_area, context_display, load_previous_button, load_next_button,
        back_to_results_button,
        # Tuning Sliders (Keep them in the list because wrappers might update their visibility/interactivity,
        # but the reset function explicitly avoids changing their values)
        window_size_slider, weight_slider, decay_slider,
        # Status message
        status_message,
    ]
    logging.info(f"Length of all_ui_outputs list (used for comprehensive updates): {len(all_ui_outputs)}")


    # --- Bindings: Connect UI elements to functions ---

    # Bind search buttons to their wrapper functions.
    # These wrappers will return a dictionary of updates for the *entire* UI state.
    search_button.click(
        search_standard_wrapper,
        inputs=[query_input, author_dropdown, window_size_slider, weight_slider, decay_slider],
        # We must list ALL potential outputs here, including states and UI elements that might change visibility or content.
        # Gradio will use the dictionary returned by the wrapper to update the matching outputs in this list.
        outputs=all_ui_outputs
    )
    llm_rerank_button.click(
        search_llm_rerank_wrapper,
        inputs=[query_input, author_dropdown, window_size_slider, weight_slider, decay_slider],
        outputs=all_ui_outputs
    )

    # Bind the favourites button to its wrapper
    best_of_button.click(
        refresh_best_wrapper,
        inputs=[], # No direct inputs, it fetches from the fav_scores state
        outputs=all_ui_outputs # It updates results display, navigation, and state
    )


    # Bind navigation buttons to a single wrapper that handles different view states
    # Inputs include all state variables needed to know the current view and data
    nav_inputs = [
         current_result_index_state, full_search_results_state, # Standard state
         llm_results_state, llm_result_index_state, # LLM state
         best_results_state, best_index_state, # Favourites state
         active_view_state # Current view indicator
    ]
    # Outputs include all UI elements and states that might change during navigation
    nav_outputs = all_ui_outputs # Navigation can affect the result display and state
    previous_result_button.click(
        lambda *args: navigate_results_wrapper("previous", *args), # Pass 'previous' as first arg
        inputs=nav_inputs,
        outputs=nav_outputs
    )
    next_result_button.click(
        lambda *args: navigate_results_wrapper("next", *args), # Pass 'next' as first arg
        inputs=nav_inputs,
        outputs=nav_outputs
    )


    # Bind the "weiterlesen" button to a wrapper that handles different view states
    # Inputs need state necessary to determine which result (standard, llm, fav) to load context for
    # We also need fav_signal's current value to pass it through in the outputs.
    read_inputs = [
        full_search_results_state, current_result_index_state, # Standard state
        llm_results_state, llm_result_index_state, # LLM state
        best_results_state, best_index_state, # Favourites state
        active_view_state, # Current view indicator (e.g., 'standard', 'llm', 'favourites')
        direct_embedding_output_holder, # Embedding for highlighting in context
        fav_signal # <--- ADDED fav_signal here as an input
    ]

    # Outputs include all UI elements and states that change when entering context view
    # This is why all_ui_outputs is used here.
    read_outputs = all_ui_outputs

    weiterlesen_button.click(
         move_to_reading_wrapper,
         inputs=read_inputs,
         outputs=read_outputs
     )


    # Bind context navigation buttons
    # load_more_context_wrapper already returns updates as a list [context_display_update, state_update]
    # These only update the context display and state, not the main results area.
    load_previous_button.click(
        load_more_context_wrapper,
        inputs=[gr.State('previous'), displayed_context_passages, direct_embedding_output_holder],
        outputs=[context_display, displayed_context_passages], # Only update context display and state
        scroll_to_output=False
    )
    load_next_button.click(
        load_more_context_wrapper,
        inputs=[gr.State('next'), displayed_context_passages, direct_embedding_output_holder],
        outputs=[context_display, displayed_context_passages], # Only update context display and state
        scroll_to_output=False
    )

    # Bind the "Zurück" button to a wrapper that handles returning to results list
    # Inputs need states relevant to restoring the correct results view.
    # We also need fav_signal's current value to pass it through in the outputs.
    back_inputs = [
        active_view_state, # Need to know which view we came from to go back correctly
        full_search_results_state, current_result_index_state, # Standard state
        llm_results_state, llm_result_index_state, # LLM state
        best_results_state, best_index_state, # Favourites state
        fav_signal, # <--- ADDED fav_signal here as an input
        direct_embedding_output_holder # Pass the embedding through so highlighting survives the round trip
    ]

    # Outputs include all UI elements and states that change when returning to results view
    back_outputs = all_ui_outputs

    back_to_results_button.click(
        go_back_to_results_wrapper,
        inputs=back_inputs,
        outputs=back_outputs
    )

    # --- Binding for favourite signaling ---
    # This binding exposes the _on_fav function to the Gradio Client API via api_name="fav".
    # The JS client will call the backend function associated with this api_name,
    # providing a value for the component(s) in the 'inputs' list.
    # _on_fav expects the value of fav_signal as its single argument.
    # It returns updates for fav_signal (to clear it) and status_message.
    fav_trigger_button.click(
        _on_fav,
        inputs=[fav_signal], # This tells Gradio that the API call for /fav expects ONE input, which should correspond to fav_signal's value.
        outputs=[fav_signal, status_message], # These are the components _on_fav will update
        api_name="fav"           # <-- Exposes route /fav
    )

# --- Launch the Application ---
if __name__ == "__main__":
    print("\n" + "="*50)
    print("--- Performing Startup Checks ---")
    startup_warnings = []
    if collection is None: startup_warnings.append("--- ERROR: ChromaDB Collection could not be loaded/initialized.")
    elif collection.count() == 0: startup_warnings.append("--- WARNUNG: ChromaDB Collection is empty. Search will yield no results.")
    elif not unique_authors: startup_warnings.append("--- WARNUNG: No unique authors found in DB metadata (check 'author' key). Filter will be empty.")
    if not API_KEY: startup_warnings.append("--- WARNUNG: GEMINI_API_KEY not found. Embedding/LLM features WILL FAIL.")
    if API_KEY and llm_rerank_model is None: startup_warnings.append(f"--- WARNUNG: Gemini LLM Re-Rank Model ({LLM_RERANK_MODEL_NAME}) failed to initialize despite API key being present.")
    if not os.path.exists(PROMPT_LOG_DIR) or not os.path.isdir(PROMPT_LOG_DIR): startup_warnings.append(f"--- WARNUNG: Prompt log directory '{PROMPT_LOG_DIR}' not found or is not a directory.")

    if startup_warnings:
        print("!!! Startup Issues Found !!!")
        for w in startup_warnings: print(w)
    else:
        print("--- Configuration checks passed successfully. ---")

    print("\n" + "--- Configuration Summary ---")
    print(f"- Embedding Model: {EMBEDDING_MODEL}")
    print(f"- LLM Re-Rank Model: {LLM_RERANK_MODEL_NAME}")
    print(f"- Initial DB Fetch Size: {INITIAL_RESULTS_FOR_RERANK}")
    print(f"- 1st Pass Re-rank Window: +/- {RERANK_WINDOW_SIZE} sentences")
    print(f"- 1st Pass Re-rank Weight: {RERANK_WEIGHT:.2f}, Decay: {RERANK_DECAY:.2f}")
    print(f"- LLM Candidate Count: {LLM_RERANK_CANDIDATE_COUNT}")
    print(f"- LLM Target Result Count: {LLM_RERANK_TARGET_COUNT}")
    print(f"- Max Results per Author (Final): {MAX_RESULTS_PER_AUTHOR}")
    print(f"- Max Favourites Displayed: {MAX_FAVOURITES}")
    print(f"- LLM Prompts logged to: '{PROMPT_LOG_DIR}'")
    print(f"- Favourites saved to: '{FAV_FILE}'") # Log fav file location
    print("--- End Summary ---")

    print("\nStarting Gradio Interface...")
    print("="*50 + "\n")

    demo.launch(
        server_name="0.0.0.0",
        share=False,
        debug=True # Keep debug=True for now to see all logs
    )