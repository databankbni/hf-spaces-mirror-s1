import streamlit as st
import os
import pandas as pd
import re
from openai import AzureOpenAI

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
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT") or "gpt-4o-mini"

if not AZURE_ENDPOINT or not AZURE_KEY:
    st.error("⚠️ System Setup Error: Missing 'AZURE_OPENAI_ENDPOINT' or 'AZURE_OPENAI_KEY' secrets.")
    st.stop()

if "/openai" in AZURE_ENDPOINT: AZURE_ENDPOINT = AZURE_ENDPOINT.split("/openai")[0]
if "/v1" in AZURE_ENDPOINT: AZURE_ENDPOINT = AZURE_ENDPOINT.split("/v1")[0]
if AZURE_ENDPOINT.endswith("/"): AZURE_ENDPOINT = AZURE_ENDPOINT[:-1]

client = AzureOpenAI(azure_endpoint=AZURE_ENDPOINT, api_key=AZURE_KEY, api_version="2024-06-01")

# --- 3. LOAD COMPLIANCE MASTER REPOSITORY ---
MASTER_CSV_FILENAME = "global_maritime_statutory_master.csv"

@st.cache_data
def load_statutory_master():
    if not os.path.exists(MASTER_CSV_FILENAME):
        return None
    try:
        df = pd.read_csv(MASTER_CSV_FILENAME, encoding="utf-8-sig")
        df["Framework"] = df["Framework"].astype(str).str.upper().str.strip()
        df["Standardized Rule No"] = df["Standardized Rule No"].astype(str).str.strip()
        df["Atomic Statutory Content"] = df["Atomic Statutory Content"].astype(str).str.strip()
        return df
    except Exception as e:
        st.error(f"Error loading master CSV: {e}")
        return None

statutory_df = load_statutory_master()

# --- 4. PRESENTATION TEXT PREPROCESSOR ---
def strip_glossary_noise(text_content):
    """Eradicates structural metadata padding strings before UI rendering."""
    if not isinstance(text_content, str):
        return text_content
    cleaned = re.sub(r'\[Glossary Mapping:[^\]]*\]', '', text_content)
    return " ".join(cleaned.split()).strip()

# --- 5. HIGH-PRECISION FILTERED CANDIDATE SEARCH MATRIX ---
def extract_best_database_candidates(user_query, active_frameworks, max_candidates=15):
    if statutory_df is None:
        return pd.DataFrame()
        
    working_df = statutory_df[statutory_df["Framework"].isin(active_frameworks)]
    if working_df.empty:
        return pd.DataFrame()
        
    clean_query = user_query.strip().lower()
    
    # Core Regulatory Glossary Maps (HKC, ILO, OSH, MEPC Guidelines, and Bangladesh Rules)
    glossary = {
        r"\bihm\b": "inventory of hazardous materials",
        r"\bptw\b": "permit to work",
        r"\bppe\b": "personal protection equipment",
        r"\bosh\b": "occupational safety and health",
        r"\bsrf\b": "ship recycling facility",
        r"\bsrfp\b": "ship recycling facility plan",
        r"\bsrp\b": "ship recycling plan",
        r"\bnoc\b": "no objection certificate",
        r"\bdasr\b": "document of authorization for ship recycling",
        r"\bbsrb\b": "bangladesh ship recycling board"
    }
    
    expanded_query = clean_query
    for acronym, full_text in glossary.items():
        expanded_query = re.sub(acronym, full_text, expanded_query)
        
    search_words = [w for w in re.split(r'\W+', expanded_query) if len(w) > 3]
    if not search_words:
        return working_df.head(max_candidates)
        
    def calculate_relevance_score(row):
        content = str(row["Atomic Statutory Content"]).lower()
        rule_no = str(row["Standardized Rule No"]).lower()
        score = 0
        if clean_query in content: score += 100
        if expanded_query in content: score += 80
        
        for word in search_words:
            if word in content: score += 10
            if word in rule_no: score += 15
        return score

    temp_df = working_df.copy()
    temp_df["relevance_score"] = temp_df.apply(calculate_relevance_score, axis=1)
    return temp_df[temp_df["relevance_score"] > 0].sort_values(by="relevance_score", ascending=False).head(max_candidates)

# --- 6. EXPLICIT AUDITING EXPERT SYSTEM PASS ---
def query_auditor_selection(user_query, candidates_df):
    if candidates_df.empty:
        return "Hallucination:::No valid candidate provisions found inside selected framework bounds.:::Not Found"
        
    context_blocks = []
    for idx, (_, row) in enumerate(candidates_df.iterrows()):
        context_blocks.append(f"Candidate #{idx+1} ID: [{row['Framework']} {row['Standardized Rule No']}]\nContent: {row['Atomic Statutory Content']}")
    joined_context = "\n\n".join(context_blocks)

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            temperature=0.0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert maritime legal auditor mapping technical requirements back to high-level statutory frameworks.\n"
                        "Your goal is to select the absolute single best-fit rule from the provided candidate list that directly covers or defines the user's query.\n\n"
                        "OUTPUT FORMAT CONSTRAINTS:\n"
                        "You must reply with exactly three lines separated by ':::' tokens. Do not use bolding or markdown wrappers:\n"
                        "[Match/Misclassified/Hallucination]:::[Provide a deep analysis explaining why this specific rule is the absolute best fit to cover the requirement, referencing its specific clauses]:::[Insert the exact text ID label of the chosen rule, e.g., 'BSRR Rule 22' or 'BSRA Section 37']"
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"User Search Bar Query: '{user_query}'\n\n"
                        f"--- VALID GROUND-TRUTH CANDIDATE TEXT ROWS FROM CSV ---\n{joined_context}"
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

if statutory_df is None:
    st.error(f"⚠️ Initialization Error: Missing critical master reference file `{MASTER_CSV_FILENAME}` in Space root directory.")
    st.stop()

# Interactive Filter Controls
st.sidebar.markdown("### 🛠️ Framework Scope Filters")
all_available_frameworks = ["BSRA", "BSRR", "BLA", "BLR", "HKC", "MEPC"]
selected_frameworks = st.sidebar.multiselect(label="Choose target legal frameworks to query:", options=all_available_frameworks, default=all_available_frameworks)

if not selected_frameworks:
    st.warning("⚠️ Please select at least one framework in the sidebar to run analysis loops.")
    st.stop()

user_search_input = st.text_input(label="Enter Specific Training Slide Component, Acronym (e.g., IHM, PPE), or Scenario to Audit:", placeholder="Type here... (e.g., 'Notify BSRB within 2 hours')")

if "status_verdict" not in st.session_state: st.session_state.status_verdict = ""
if "analysis_text" not in st.session_state: st.session_state.analysis_text = ""
if "best_rule_code" not in st.session_state: st.session_state.best_rule_code = ""
if "primary_match_card" not in st.session_state: st.session_state.primary_match_card = None
if "backup_candidates_list" not in st.session_state: st.session_state.backup_candidates_list = []

if st.button("🔍 Analyze CSV for Most Fit Rule", use_container_width=True):
    if user_search_input.strip():
        with st.spinner("Extracting filtered structures and scanning legal alignment matrices..."):
            
            matched_candidates = extract_best_database_candidates(user_search_input, selected_frameworks)
            raw_report = query_auditor_selection(user_search_input, matched_candidates)
            
            parts = raw_report.split(":::")
            verdict = parts[0].strip("[] ") if len(parts) == 3 else "Manual Review Required"
            analysis = parts[1].strip() if len(parts) == 3 else "No description provided."
            predicted_label = parts[2].replace("**", "").replace("[", "").replace("]", "").strip() if len(parts) == 3 else "Not Found"
            
            st.session_state.status_verdict = verdict
            st.session_state.analysis_text = analysis
            st.session_state.best_rule_code = predicted_label
            
            # --- FIXED SUB-STRING MATCH MATRIX PASS WITH WORD BOUNDARIES ---
            detected_fw = None
            for tag in all_available_frameworks:
                if tag in predicted_label.upper():
                    detected_fw = tag
                    break
            
            primary_row = None
            backup_rows = []
            
            if detected_fw:
                fw_df = statutory_df[statutory_df["Framework"] == detected_fw]
                
                # Check 1: Try an exact string matching test first
                exact_rule_mask = fw_df["Standardized Rule No"].str.lower() == predicted_label.lower()
                primary_matches = fw_df[exact_rule_mask]
                
                # Check 2: Advanced Token Extraction to handle nested sub-indices like Rule 22(22)
                if primary_matches.empty:
                    clause_digits_match = re.search(r'\d+(?:\([^)]+\))*', predicted_label)
                    clean_clause_digits = clause_digits_match.group(0) if clause_digits_match else ""
                    
                    if clean_clause_digits:
                        # Split by major digits to isolate parent number (e.g., extracting "22" out of "22")
                        base_digit = re.findall(r'\d+', clean_clause_digits)[0]
                        
                        # High-Precision Constraint: Match parent framework rule number exactly using strict boundaries
                        # This prevents "Rule 22" from matching noise strings inside "Rule 3(22)"
                        token_pattern = r'\bRule\s+' + re.escape(base_digit) + r'\b|\bSection\s+' + re.escape(base_digit) + r'\b|\bRegulation\s+' + re.escape(base_digit) + r'\b'
                        strict_mask = fw_df["Standardized Rule No"].str.contains(token_pattern, regex=True, case=False, na=False)
                        primary_matches = fw_df[strict_mask]
                
                if not primary_matches.empty:
                    hit = primary_matches.iloc[0]
                    primary_row = {
                        "Framework": hit["Framework"],
                        "RuleNo": hit["Standardized Rule No"],
                        "Title": hit["Contextual Title"],
                        "Content": strip_glossary_noise(hit["Atomic Statutory Content"])
                    }
            
            # Populate alternative backup items from matched entries
            for _, row in matched_candidates.iterrows():
                clean_content = strip_glossary_noise(row["Atomic Statutory Content"])
                if primary_row and row["Standardized Rule No"].lower() == primary_row["RuleNo"].lower():
                    continue
                backup_rows.append({
                    "Framework": row["Framework"],
                    "RuleNo": row["Standardized Rule No"],
                    "Title": row["Contextual Title"],
                    "Content": clean_content
                })
                    
            if primary_row is None and not matched_candidates.empty:
                top_hit = matched_candidates.iloc[0]
                primary_row = {
                    "Framework": top_hit["Framework"],
                    "RuleNo": top_hit["Standardized Rule No"],
                    "Title": top_hit["Contextual Title"],
                    "Content": strip_glossary_noise(top_hit["Atomic Statutory Content"])
                }
                if len(backup_rows) > 0: backup_rows.pop(0)
                
            st.session_state.primary_match_card = primary_row
            st.session_state.backup_candidates_list = backup_rows[:2]
    else:
        st.warning("Please enter a term or requirement phrase into the search bar first.")

# --- 8. RENDER DISPLAY COMPONENTS ---
if st.session_state.status_verdict:
    st.markdown("---")
    left_column, right_column = st.columns([1, 2])
    
    with left_column:
        st.markdown("### 🤖 Auditor Classification")
        with st.container(border=True):
            if st.session_state.status_verdict == "Match": st.success(f"📋 Status: {st.session_state.status_verdict}")
            elif st.session_state.status_verdict == "Misclassified": st.info(f"📋 Status: {st.session_state.status_verdict}")
            else: st.error(f"📋 Status: {st.session_state.status_verdict}")
                
            st.markdown(f"**Target Citation Code:** `{st.session_state.best_rule_code}`")
            st.markdown(f"💡 **Coverage Extent Analysis:**\n*{st.session_state.analysis_text}*")
            
    with right_column:
        st.markdown("### 🎯 Absolute Best Fit Statutory Provision")
        if st.session_state.primary_match_card:
            with st.container(border=True):
                st.markdown(f"#### 🔥 {st.session_state.primary_match_card['Framework']} — {st.session_state.primary_match_card['RuleNo']}")
                st.caption(f"**Context:** {st.session_state.primary_match_card['Title']}")
                st.code(st.session_state.primary_match_card["Content"], language=None, wrap_lines=True)
        else:
            st.info("No primary match could be validated within the selected framework parameters.")
            
        if st.session_state.backup_candidates_list:
            st.markdown("#### 📜 Highly Relevant Alternative Candidates")
            for idx, item in enumerate(st.session_state.backup_candidates_list):
                with st.container(border=True):
                    st.markdown(f"**Alternative #{idx + 1}: {item['Framework']} — {item['RuleNo']}**")
                    st.caption(f"**Context:** {item['Title']}")
                    st.code(item["Content"], language=None, wrap_lines=True)