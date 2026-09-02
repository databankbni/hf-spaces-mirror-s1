import streamlit as st
import os
import pandas as pd
import re
from openai import AzureOpenAI

# --- 1. AZURE OPENAI CLIENT INITIALIZATION ---
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
AZURE_KEY = os.getenv("AZURE_OPENAI_KEY", "").strip()
DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT") or "gpt-4o-mini"

if not AZURE_ENDPOINT or not AZURE_KEY:
    st.error("⚠️ System Setup Error: Missing Secrets in Space Environment configuration.")
    st.stop()

if "/openai" in AZURE_ENDPOINT:
    AZURE_ENDPOINT = AZURE_ENDPOINT.split("/openai")[0]
if "/v1" in AZURE_ENDPOINT:
    AZURE_ENDPOINT = AZURE_ENDPOINT.split("/v1")[0]
if AZURE_ENDPOINT.endswith("/"):
    AZURE_ENDPOINT = AZURE_ENDPOINT[:-1]

client = AzureOpenAI(azure_endpoint=AZURE_ENDPOINT, api_key=AZURE_KEY, api_version="2024-06-01")

# --- 2. LOAD COMPLIANCE MASTER REPOSITORY ---
MASTER_CSV_FILENAME = "global_maritime_statutory_master.csv"

@st.cache_data
def load_statutory_master():
    """Safely loads and caches the master rules list at runtime."""
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

# --- 3. HIGH-PRECISION CITATION AUDITOR ENGINE WITH GLOSSARY AWARENESS ---
def ai_audit_training_phrase(user_sentence):
    """Maps training snippets to precise provisions using structured auditing controls and glossary grounding."""
    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT_NAME,
            temperature=0.0, # Zero temperature guarantees high reliability execution paths
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert maritime legal auditor mapping technical training slides back to "
                        "high-level statutory frameworks (BSRA, BSRR, HKC, MEPC, BLA, BLR).\n\n"
                        
                        "OFFICIAL OPERATIONAL GLOSSARY MAP:\n"
                        "- BSRB = Bangladesh Ship Recycling Board (Competent Authority)\n"
                        "- DASR = Document of Authorization for ship recycling\n"
                        "- SRF = Ship Recycling Facility\n"
                        "- SRFP = Ship Recycling Facility Plan\n"
                        "- NOC = No Objection Certificate\n"
                        "- PTW = Permit to Work\n"
                        "- SRP = Ship Recycling Plan\n"
                        "- PPE = Personal Protection Equipment\n"
                        "- IHM = Inventory of Hazardous Materials\n\n"
                        
                        "CORE LEGAL KNOWLEDGE DIRECTORY:\n"
                        "- Employing untrained, uncertified, or unqualified workers in ship recycling = BSRA Section 35\n"
                        "- Workers operating or engaging in recycling without appropriate PPE / safety gears = BSRA Section 37\n"
                        "- Environmentally sound waste management, SRFP guidelines, and handling sequences before cutting = BSRR Rule 15\n\n"
                        
                        "CROSS-SOURCE FALLBACK & HALLUCINATION GUARDRAILS:\n"
                        "If the input phrase lacks compliance substance, is vague, random, or cannot be realistically "
                        "correlated with a verified statutory target provision, you MUST classify it as 'Hallucination' "
                        "and output 'Not Found' in the code slot.\n\n"
                        
                        "STRICT CITATION LAYOUTS:\n"
                        "- DO NOT use markdown asterisks (**) or bolding formatting on any rule or section digits.\n"
                        "- Ensure rule outputs match standard formatting lengths (e.g., 'BSRA Section 35', 'BSRR Rule 15').\n\n"
                        
                        "OUTPUT FORMAT:\n"
                        "You must reply with exactly three lines separated by ':::' tokens. No extra text or markdown wrappers:\n"
                        "[Match/Misclassified/Hallucination]:::[Insert brief candidate rule coverage analysis summary, detailing the extent matching the text context]:::[Insert the exact overarching statutory reference label layout, like 'BSRA Section 35' or 'BSRR Rule 15' OR write 'Not Found']"
                    )
                },
                {"role": "user", "content": f"Audit this training item: '{user_sentence}'"}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Hallucination:::Failed to connect to API: {str(e)}:::Not Found"

# --- 4. STREAMLIT INTERACTIVE USER INTERFACE ---
st.set_page_config(page_title="Statutory Reference Workspace", page_icon="⚖️", layout="wide")

st.title("⚖️ Statutory Reference Lookup & Verification Workspace")
st.write("Cross-reference training snippets directly with your master CSV dataset rows under structured auditing controls.")

if statutory_df is None:
    st.warning(f"⚠️ Master Database Missing: Please upload `{MASTER_CSV_FILENAME}` to your root directory.")

user_sentence = st.text_area(
    label="Enter Training Text or Scenario to Audit:",
    placeholder="Type or paste your compliance phrase here... (e.g., 'Workers engaged in recycling without appropriate PPE')",
    height=110
)

if "audit_status" not in st.session_state: st.session_state.audit_status = ""
if "audit_analysis" not in st.session_state: st.session_state.audit_analysis = ""
if "predicted_code" not in st.session_state: st.session_state.predicted_code = ""
if "verified_content_list" not in st.session_state: st.session_state.verified_content_list = []

if st.button("🔍 Run Audited Database Match", use_container_width=True):
    if user_sentence.strip() and statutory_df is not None:
        with st.spinner("Executing deep auditing lookup rules..."):
            
            raw_output = ai_audit_training_phrase(user_sentence)
            parts = raw_output.split(":::")
            
            if len(parts) == 3:
                status = parts[0].strip()
                analysis = parts[1].strip()
                predicted_label = parts[2].strip()
                
                st.session_state.audit_status = status
                st.session_state.audit_analysis = analysis
                st.session_state.predicted_code = predicted_label
                
                # Reset repository display loops
                verified_records = []
                
                if "Not Found" not in predicted_label and status != "Hallucination":
                    # Break down framework vs section number parts safely
                    label_elements = predicted_label.split(" ")
                    if len(label_elements) >= 3:
                        framework_pred = label_elements[0].upper().strip()
                        # Extract the primary section number digit sequence (e.g., "35" or "15")
                        digits = re.findall(r'\d+', predicted_label)
                        
                        if digits:
                            # Filter local rows strictly by framework block match first
                            sub_df = statutory_df[statutory_df["Framework"] == framework_pred]
                            # Use regex word boundaries to prevent pulling partial numbers or "None" fields
                            num_mask = sub_df["Standardized Rule No"].str.contains(r'\b' + digits[0] + r'\b', regex=True, na=False)
                            matched_rows = sub_df[num_mask]
                            
                            for _, row in matched_rows.iterrows():
                                # Lock out any accidental parsing artifacts that defaulted to string none values
                                if "none" in str(row["Standardized Rule No"]).lower():
                                    continue
                                verified_records.append({
                                    "Framework": row["Framework"],
                                    "RuleNo": row["Standardized Rule No"],
                                    "Content": row["Atomic Statutory Content"]
                                })
                
                st.session_state.verified_content_list = verified_records
    else:
        st.warning("Please provide an input text snippet first.")

# --- 5. RENDER AUDITED DATA CARDS SIDE-BY-SIDE ---
if st.session_state.audit_status:
    st.markdown("---")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown("### 🤖 Auditor Classification")
        with st.container(border=True):
            if st.session_state.audit_status == "Match":
                st.success(f"📋 Status: {st.session_state.audit_status}")
            elif st.session_state.audit_status == "Misclassified":
                st.info(f"📋 Status: {st.session_state.audit_status}")
            else:
                st.error(f"📋 Status: {st.session_state.audit_status}")
                
            st.markdown(f"**Target Citation Code:** `{st.session_state.predicted_code}`")
            st.markdown(f"💡 **Coverage Extent Analysis:**\n*{st.session_state.audit_analysis}*")
                
    with col2:
        st.markdown("### 📜 Local CSV Ground-Truth Content")
        if st.session_state.audit_status == "Hallucination" or not st.session_state.verified_content_list:
            st.error("❌ Not Found: This training phrase could not be validated or matched against any clean statutory row in your local repository.")
        else:
            for idx, rec in enumerate(st.session_state.verified_content_list):
                with st.container(border=True):
                    head_c1, head_c2 = st.columns([3, 1])
                    head_c1.markdown(f"#### {rec['Framework']} — {rec['RuleNo']}")
                    head_c2.warning("⚠️ AI search - might wrong please verify")
                    
                    st.code(rec["Content"], language=None, wrap_lines=True)