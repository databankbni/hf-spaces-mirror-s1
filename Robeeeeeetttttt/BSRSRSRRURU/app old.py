import os
import re
import json
import numpy as np
import pandas as pd
import streamlit as st
from openai import AzureOpenAI
from datasets import load_dataset
from huggingface_hub import login

# --- 1. SYSTEM SECURITY & SESSION LOGIN PERSISTENCE ---
SECRET_PASSCODE = os.getenv("APP_PASSWORD", "").strip()

if not SECRET_PASSCODE:
    st.error("🔒 Security Setup Error: Missing 'APP_PASSWORD' secret inside Hugging Face Settings. Please configure it first.")
    st.stop()

if "security_authenticated" not in st.session_state:
    st.session_state.security_authenticated = False

def check_login_credentials():
    """Validates the input passphrase to grant persistent session access."""
    if st.session_state["entered_password"] == SECRET_PASSCODE:
        st.session_state.security_authenticated = True
        del st.session_state["entered_password"]
    else:
        st.session_state.security_authenticated = False
        st.error("❌ Invalid Passcode. Access Denied.")

if not st.session_state.security_authenticated:
    st.set_page_config(page_title="🔒 Locked Workspace", page_icon="🔒")
    st.title("🔒 Compliance Workspace Authorization Gate")
    st.write("This workspace is locked for internal audit safety. Please enter your secure passphrase below.")
    st.text_input(label="Enter Secure Application Password:", type="password", key="entered_password", on_change=check_login_credentials)
    st.stop()

# --- 2. AZURE OPENAI CLIENT INITIALIZATION ---
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
AZURE_KEY = os.getenv("AZURE_OPENAI_KEY", "").strip()

CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or "gpt-4o-mini"
EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or "text-embedding-3-small"

if not AZURE_ENDPOINT or not AZURE_KEY:
    st.error("⚠️ System Setup Error: Missing 'AZURE_OPENAI_ENDPOINT' or 'AZURE_OPENAI_KEY' secrets.")
    st.stop()

if "/openai" in AZURE_ENDPOINT: AZURE_ENDPOINT = AZURE_ENDPOINT.split("/openai")[0]
if "/v1" in AZURE_ENDPOINT: AZURE_ENDPOINT = AZURE_ENDPOINT.split("/v1")[0]
if AZURE_ENDPOINT.endswith("/"): AZURE_ENDPOINT = AZURE_ENDPOINT[:-1]

client = AzureOpenAI(azure_endpoint=AZURE_ENDPOINT, api_key=AZURE_KEY, api_version="2024-06-01")

# --- 3. HUGGINGFACE DATASET LOADER (JSONL ENGINE) ---
HF_DATASET_REPO = os.getenv("HF_DATASET_REPO", "").strip()  # e.g., "your-username/maritime-legal-laws"
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()

if HF_TOKEN:
    login(token=HF_TOKEN)

@st.cache_resource
def load_hf_canonical_dataset():
    """Loads reconstructed canonical legal articles from Hugging Face dataset."""
    try:
        # Load directly from public repo
        ds = load_dataset("Robeeeeeetttttt/testingdataSetMarLaw", split="train")
        return ds.to_list()
    except Exception as e:
        st.error(f"Error loading Hugging Face dataset: {e}")
        return None

canonical_database = load_hf_canonical_dataset()

# Derive available legal frameworks/laws dynamically from the JSONL entries
if canonical_database:
    ALL_AVAILABLE_FRAMEWORKS = sorted(list(set([
        item.get("law_name", "UNKNOWN").strip() for item in canonical_database
    ])))
else:
    ALL_AVAILABLE_FRAMEWORKS = ["MARITIME STATUTORY LAW"]

# Precompute vector embeddings on startup if not present inside JSONL
@st.cache_resource
def get_cached_embeddings(_dataset_records):
    """Generates or extracts embeddings for fast cosine similarity scoring."""
    embeddings_matrix = []
    if not _dataset_records:
        return embeddings_matrix
    
    # Batch embedding creation for full verbatim text
    texts = [rec["full_verbatim_text"] for rec in _dataset_records]
    batch_size = 32
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        res = client.embeddings.create(input=batch, model=EMBEDDING_DEPLOYMENT)
        for item in res.data:
            embeddings_matrix.append(item.embedding)
            
    return np.array(embeddings_matrix, dtype=np.float32)

if canonical_database:
    vector_embeddings = get_cached_embeddings(canonical_database)
else:
    vector_embeddings = None

def get_embedding(text):
    """Generates a query vector using your Azure embedding deployment."""
    try:
        response = client.embeddings.create(
            input=[text],
            model=EMBEDDING_DEPLOYMENT
        )
        return response.data[0].embedding
    except Exception as e:
        st.error(f"Embedding API Error: {e}")
        return None

def cosine_similarity(v1, v2):
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return float(dot_product / (norm_v1 * norm_v2))

# --- 4. PRESENTATION TEXT PREPROCESSOR ---
def strip_glossary_noise(text_content):
    if not isinstance(text_content, str):
        return text_content
    cleaned = re.sub(r'\[Glossary Mapping:[^\]]*\]', '', text_content)
    return " ".join(cleaned.split()).strip()

GLOSSARY_PATTERNS = {
    re.compile(r"\bihm\b", re.IGNORECASE): "inventory of hazardous materials",
    re.compile(r"\bptw\b", re.IGNORECASE): "permit to work",
    re.compile(r"\bppe\b", re.IGNORECASE): "personal protection equipment",
    re.compile(r"\bosh\b", re.IGNORECASE): "occupational safety and health",
    re.compile(r"\bsrf\b", re.IGNORECASE): "ship recycling facility",
    re.compile(r"\bsrfp\b", re.IGNORECASE): "ship recycling facility plan",
    re.compile(r"\bsrp\b", re.IGNORECASE): "ship recycling plan",
    re.compile(r"\bnoc\b", re.IGNORECASE): "no objection certificate",
    re.compile(r"\bdasr\b", re.IGNORECASE): "document of authorization for ship recycling",
    re.compile(r"\bbsrb\b", re.IGNORECASE): "bangladesh ship recycling board"
}

# --- 5. GOOGLE-STYLE SEMANTIC VECTOR MATCH ENGINE ---
def extract_best_database_candidates(user_query, active_frameworks, max_candidates=15):
    if not canonical_database or vector_embeddings is None:
        return []
        
    expanded_query = user_query.strip()
    for pattern, full_text in GLOSSARY_PATTERNS.items():
        expanded_query = pattern.sub(full_text, expanded_query)
        
    query_vector = get_embedding(expanded_query)
    if query_vector is None:
        return []
        
    scored_candidates = []
    
    for idx, item in enumerate(canonical_database):
        item_framework = item.get("law_name", "UNKNOWN").strip()
        
        # Scope filter matching
        if item_framework in active_frameworks:
            item_vector = vector_embeddings[idx]
            similarity = cosine_similarity(query_vector, item_vector)
            
            # Map canonical JSONL schema fields
            art_num = item.get("article_number", "N/A")
            sec = item.get("section") or item.get("chapter") or "N/A"
            art_title = item.get("article_title") or "Untitled Section"
            
            scored_candidates.append({
                "Framework": item_framework,
                "Standardized Rule No": f"Article {art_num} ({sec})",
                "Contextual Title": art_title,
                "Atomic Statutory Content": item.get("full_verbatim_text", ""),
                "Jurisdiction": item.get("jurisdiction", "N/A"),
                "Source Pages": item.get("source_pages", []),
                "relevance_score": similarity
            })
            
    # Sort descending by semantic similarity score
    scored_candidates.sort(key=lambda x: x["relevance_score"], reverse=True)
    return scored_candidates[:max_candidates]

# --- 6. EXPLICIT AUDITING EXPERT SYSTEM PASS ---
def query_auditor_selection(user_query, candidates):
    if not candidates:
        return "Hallucination:::No valid candidate provisions found inside selected framework bounds.:::Not Found"
        
    context_blocks = []
    for idx, item in enumerate(candidates[:5]): 
        context_blocks.append(
            f"CANDIDATE #{idx+1} IDENTIFIER: [{item['Framework']} - {item['Standardized Rule No']}]\n"
            f"Jurisdiction: {item['Jurisdiction']}\n"
            f"Section Heading: {item['Contextual Title']}\n"
            f"Source Pages: {item['Source Pages']}\n"
            f"Clause Content:\n{item['Atomic Statutory Content']}\n"
            f"----------------------------------------"
        )
    joined_context = "\n\n".join(context_blocks)

    try:
        response = client.chat.completions.create(
            model=CHAT_DEPLOYMENT,
            temperature=0.0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert maritime legal auditor verifying operational scenarios against technical statutory frameworks.\n"
                        "Your job is to read the user's scenario query alongside a ranked list of relevant regulatory clauses pulled from a vector index.\n"
                        "Evaluate the chunks, determine which single clause is the absolute most appropriate rule to govern the query, and provide a legal analysis. Do not hallucinate or use external citation frameworks like US OSHA (29 CFR).\n\n"
                        "OUTPUT CONSTRAINTS:\n"
                        "You must reply with exactly three lines separated by ':::' tokens. Do not use bolding or markdown wrappers:\n"
                        "[Match/Misclassified/Hallucination]:::[Provide a deep analysis explaining exactly why the single selected rule is the absolute most appropriate choice to cite for this specific query scenario step-by-step]:::[Insert the exact text identification string of the chosen best match, e.g., 'Article 14' or 'Merchant Shipping Act Article 9']"
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"User Search Query Scenario: '{user_query}'\n\n"
                        f"--- REAL RETRIEVED LEGAL FRAMEWORK PROVISIONS (RANKED BY COCHLEAR VECTOR SIMILARITY) ---\n"
                        f"{joined_context}"
                    )
                }
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Manual Review Required:::API connection timed out: {str(e)}:::Not Found"

# --- 7. STREAMLIT WORKSPACE LAYOUT CANVAS ---
st.set_page_config(page_title="Statutory Auditor Workspace", page_icon="⚖️", layout="wide")
st.title("⚖️ High-Precision Statutory Reference Search Workspace")

if not canonical_database:
    st.error("⚠️ Initialization Error: Could not load `canonical_articles.jsonl` from Hugging Face Hub or local directory.")
    st.info("Ensure `HF_DATASET_REPO` environment variable is configured in Hugging Face Space Settings.")
    st.stop()

# Interactive Filter Controls
st.sidebar.markdown("### 🛠️ Framework Scope Filters")
selected_frameworks = st.sidebar.multiselect(
    label="Choose target legal frameworks to query:", 
    options=ALL_AVAILABLE_FRAMEWORKS, 
    default=ALL_AVAILABLE_FRAMEWORKS
)

if not selected_frameworks:
    st.warning("⚠️ Please select at least one framework in the sidebar to run analysis loops.")
    st.stop()

user_search_input = st.text_input(label="Enter Specific Training Slide Component, Acronym, or Scenario to Audit:", placeholder="e.g., 'DASR' or 'registration of British ship'")

if "status_verdict" not in st.session_state: st.session_state.status_verdict = ""
if "analysis_text" not in st.session_state: st.session_state.analysis_text = ""
if "best_rule_code" not in st.session_state: st.session_state.best_rule_code = ""
if "all_retrieved_hits" not in st.session_state: st.session_state.all_retrieved_hits = []

if st.button("🔍 Analyze Frameworks & Search Correlated Rules", use_container_width=True):
    if user_search_input.strip():
        with st.spinner("Scoring vector indices and compiling correlated statutory provisions..."):
            
            # 1. Search engine pass over canonical JSONL database
            matched_candidates = extract_best_database_candidates(user_search_input, selected_frameworks)
            
            if matched_candidates:
                st.session_state.all_retrieved_hits = matched_candidates
                
                # 2. Expert auditing system pass
                raw_report = query_auditor_selection(user_search_input, matched_candidates)
                
                parts = raw_report.split(":::")
                verdict = parts[0].strip("[] ") if len(parts) == 3 else "Manual Review Required"
                analysis = parts[1].strip() if len(parts) == 3 else "No description provided."
                predicted_label = parts[2].replace("**", "").replace("[", "").replace("]", "").strip() if len(parts) == 3 else "Not Found"
                
                st.session_state.status_verdict = verdict
                st.session_state.analysis_text = analysis
                st.session_state.best_rule_code = predicted_label
            else:
                st.error("No correlated matches found for the selected framework filters.")
                st.session_state.all_retrieved_hits = []
    else:
        st.warning("Please enter a term or scenario phrase into the search bar first.")

# --- 8. RENDER DYNAMIC COMPONENT LAYOUTS ---
if st.session_state.status_verdict:
    st.markdown("---")
    
    # Split view: Left for AI verification analysis report, Right for matching provisions list
    left_column, right_column = st.columns([1, 2])
    
    with left_column:
        st.markdown("### 🤖 Auditor Verification")
        
        with st.expander("📋 View Auditor Verdict & Analysis Details", expanded=True):
            if st.session_state.status_verdict == "Match": 
                st.success(f"📋 Status: {st.session_state.status_verdict}")
            elif st.session_state.status_verdict == "Misclassified": 
                st.info(f"📋 Status: {st.session_state.status_verdict}")
            else: 
                st.error(f"📋 Status: {st.session_state.status_verdict}")
                
            st.markdown(f"**Determined Most Appropriate Rule:** `{st.session_state.best_rule_code}`")
            st.markdown(f"💡 **Auditor Compliance Analysis:**\n\n{st.session_state.analysis_text}")
            
    with right_column:
        st.markdown(f"### 🔍 Correlated Statutory Search Results ({len(st.session_state.all_retrieved_hits)} matches found)")
        st.caption("Provisions are listed below in descending order of direct mathematical semantic similarity to your query.")
        
        for idx, item in enumerate(st.session_state.all_retrieved_hits):
            is_chosen_one = st.session_state.best_rule_code.lower() in f"{item['Framework']} {item['Standardized Rule No']}".lower()
            
            if idx == 0 or is_chosen_one:
                expander_title = f"🎯 [{idx+1}] {item['Framework']} — {item['Standardized Rule No']} (Top Match Fit)"
                should_auto_open = True
            else:
                expander_title = f"📜 [{idx+1}] Correlated: {item['Framework']} — {item['Standardized Rule No']}"
                should_auto_open = False
                
            with st.expander(f"{expander_title} | Score: {item['relevance_score']:.4f}", expanded=should_auto_open):
                st.markdown(f"**Jurisdiction:** *{item['Jurisdiction']}* | **Cited Source Pages:** `{item['Source Pages']}`")
                st.markdown(f"**Context / Header:** *{item['Contextual Title']}*")
                
                clean_clause_text = strip_glossary_noise(item['Atomic Statutory Content'])
                st.code(clean_clause_text, language=None, wrap_lines=True)