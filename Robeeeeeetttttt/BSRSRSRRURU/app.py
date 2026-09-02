import streamlit as st
import os
import json
import re
import math
from pathlib import Path
from openai import AzureOpenAI


# ================================================================
# 1. PAGE CONFIG
# ================================================================

st.set_page_config(
    page_title="Statutory Auditor Workspace",
    page_icon="⚖️",
    layout="wide"
)


# ================================================================
# 2. SECURITY / LOGIN
# ================================================================

SECRET_PASSCODE = os.getenv(
    "APP_PASSWORD",
    ""
).strip()

if not SECRET_PASSCODE:
    st.error(
        "🔒 Security Setup Error: Missing 'APP_PASSWORD' "
        "secret inside Hugging Face Settings."
    )
    st.stop()

if "security_authenticated" not in st.session_state:
    st.session_state.security_authenticated = False


def check_login_credentials():
    entered = st.session_state.get(
        "entered_password",
        ""
    )

    if entered == SECRET_PASSCODE:
        st.session_state.security_authenticated = True

        if "entered_password" in st.session_state:
            del st.session_state["entered_password"]

    else:
        st.session_state.security_authenticated = False
        st.error("❌ Invalid Passcode. Access Denied.")


if not st.session_state.security_authenticated:

    st.title("🔒 Compliance Workspace Authorization Gate")

    st.write(
        "This workspace is locked for internal audit safety. "
        "Please enter your secure passphrase below."
    )

    st.text_input(
        label="Enter Secure Application Password:",
        type="password",
        key="entered_password",
        on_change=check_login_credentials
    )

    st.stop()


# ================================================================
# 3. AZURE OPENAI
# ================================================================

AZURE_ENDPOINT = os.getenv(
    "AZURE_OPENAI_ENDPOINT",
    ""
).strip()

AZURE_KEY = os.getenv(
    "AZURE_OPENAI_KEY",
    ""
).strip()

CHAT_DEPLOYMENT = (
    os.getenv(
        "AZURE_OPENAI_DEPLOYMENT_NAME"
    )
    or "gpt-4o-mini"
)


if not AZURE_ENDPOINT or not AZURE_KEY:
    st.error(
        "⚠️ System Setup Error: Missing "
        "'AZURE_OPENAI_ENDPOINT' or "
        "'AZURE_OPENAI_KEY' secrets."
    )
    st.stop()


# Normalize endpoint

if "/openai" in AZURE_ENDPOINT:
    AZURE_ENDPOINT = AZURE_ENDPOINT.split("/openai")[0]

if "/v1" in AZURE_ENDPOINT:
    AZURE_ENDPOINT = AZURE_ENDPOINT.split("/v1")[0]

AZURE_ENDPOINT = AZURE_ENDPOINT.rstrip("/")


@st.cache_resource
def create_azure_client():

    return AzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=AZURE_KEY,
        api_version="2024-06-01"
    )


client = create_azure_client()


# ================================================================
# 4. DATASET PATHS
# ================================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"

FRAMEWORK_PATHS = {
    "BSRR":
        DATA_DIR
        / "BSRR"
        / "context_aware_search_index.json"
}


# ================================================================
# 5. LOAD CONTEXT-AWARE INDEX
# ================================================================

@st.cache_data
def load_framework_index(framework):

    if framework not in FRAMEWORK_PATHS:
        return None

    index_path = FRAMEWORK_PATHS[framework]

    if not index_path.exists():
        return None

    with open(
        index_path,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


bsrr_index = load_framework_index("BSRR")


if bsrr_index is None:

    st.error(
        "⚠️ BSRR index could not be loaded.\n\n"
        "Expected file:\n"
        f"`{FRAMEWORK_PATHS['BSRR']}`"
    )

    st.stop()


# ================================================================
# 6. DATASET INFORMATION
# ================================================================

SEARCHABLE_UNITS = (
    bsrr_index
    .get("searchable_units", [])
)

PAGES = (
    bsrr_index
    .get("pages", {})
)

DOCUMENT_INFO = (
    bsrr_index
    .get("document", {})
)


# ================================================================
# 7. GLOSSARY / QUERY NORMALIZATION
# ================================================================

GLOSSARY_PATTERNS = {

    re.compile(
        r"\bihm\b",
        re.IGNORECASE
    ):
        "inventory of hazardous materials",

    re.compile(
        r"\bptw\b",
        re.IGNORECASE
    ):
        "permit to work",

    re.compile(
        r"\bppe\b",
        re.IGNORECASE
    ):
        "personal protective equipment",

    re.compile(
        r"\bosh\b",
        re.IGNORECASE
    ):
        "occupational safety and health",

    re.compile(
        r"\bsrf\b",
        re.IGNORECASE
    ):
        "ship recycling facility",

    re.compile(
        r"\bsrfp\b",
        re.IGNORECASE
    ):
        "ship recycling facility plan",

    re.compile(
        r"\bsrp\b",
        re.IGNORECASE
    ):
        "ship recycling plan",

    re.compile(
        r"\bnoc\b",
        re.IGNORECASE
    ):
        "no objection certificate",

    re.compile(
        r"\bdasr\b",
        re.IGNORECASE
    ):
        "document of authorization for ship recycling",

    re.compile(
        r"\bbsrb\b",
        re.IGNORECASE
    ):
        "Bangladesh Ship Recycling Board"
}


def normalize_query(query):

    expanded = query.strip()

    for pattern, replacement in GLOSSARY_PATTERNS.items():
        expanded = pattern.sub(
            replacement,
            expanded
        )

    return expanded


# ================================================================
# 8. LOCAL TEXT RETRIEVAL
# ================================================================
#
# First prototype:
#   - no Azure embedding call
#   - no external vector database
#   - high-recall lexical retrieval
#
# This is deliberately simple.
# We will replace/improve this later.
# ================================================================

STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "for",
    "of",
    "to",
    "in",
    "on",
    "at",
    "by",
    "with",
    "and",
    "or",
    "can",
    "must",
    "may",
    "shall",
    "should",
    "does",
    "do",
    "how",
    "what",
    "who",
    "when",
    "where",
    "why",
    "a",
    "yard"
}


def tokenize(text):

    if not isinstance(text, str):
        return []

    tokens = re.findall(
        r"[A-Za-z0-9]+",
        text.lower()
    )

    return [
        token
        for token in tokens
        if token not in STOPWORDS
    ]


def build_searchable_text(unit):

    pieces = []

    text = unit.get(
        "text",
        ""
    )

    pieces.append(text)

    annotation = (
        unit.get("annotation")
        or {}
    )

    for key in [
        "marker",
        "unit_type",
        "search_concepts",
        "entities",
        "deontic_terms",
        "actions"
    ]:

        value = annotation.get(key)

        if isinstance(value, list):
            pieces.extend(
                str(x)
                for x in value
            )

        elif value:
            pieces.append(
                str(value)
            )

    return " ".join(pieces)


def score_local_match(
    query,
    unit
):

    query_tokens = set(
        tokenize(query)
    )

    if not query_tokens:
        return 0.0

    searchable_text = build_searchable_text(
        unit
    )

    text_lower = searchable_text.lower()

    text_tokens = set(
        tokenize(searchable_text)
    )

    if not text_tokens:
        return 0.0

    overlap = (
        len(
            query_tokens
            & text_tokens
        )
        / len(query_tokens)
    )

    # Exact phrase bonus
    phrase_bonus = 0.0

    normalized_query = (
        query.lower().strip()
    )

    original_text = (
        unit.get("text", "")
        .lower()
    )

    if (
        len(normalized_query) > 8
        and normalized_query in original_text
    ):
        phrase_bonus = 0.35

    # Annotation concept bonus
    annotation_bonus = 0.0

    annotation = (
        unit.get("annotation")
        or {}
    )

    concepts = []

    for key in [
        "search_concepts",
        "entities",
        "deontic_terms",
        "actions"
    ]:

        value = annotation.get(key)

        if isinstance(value, list):
            concepts.extend(
                str(x).lower()
                for x in value
            )

    for token in query_tokens:

        if any(
            token in concept
            for concept in concepts
        ):
            annotation_bonus += 0.03

    annotation_bonus = min(
        annotation_bonus,
        0.20
    )

    score = (
        overlap
        + phrase_bonus
        + annotation_bonus
    )

    return float(
        min(score, 1.0)
    )


def extract_best_database_candidates(
    user_query,
    max_candidates=15
):

    expanded_query = normalize_query(
        user_query
    )

    scored = []

    for unit in SEARCHABLE_UNITS:

        score = score_local_match(
            expanded_query,
            unit
        )

        if score <= 0:
            continue

        scored.append({

            "source_unit_id":
                unit.get(
                    "source_unit_id"
                ),

            "page":
                unit.get(
                    "page_number"
                ),

            "block_id":
                unit.get(
                    "block_id"
                ),

            "text":
                unit.get(
                    "text",
                    ""
                ),

            "annotation":
                unit.get(
                    "annotation",
                    {}
                ),

            "relevance_score":
                score
        })

    scored.sort(
        key=lambda x:
            x["relevance_score"],
        reverse=True
    )

    return scored[:max_candidates]


# ================================================================
# 9. CROSS-PAGE CONTEXT EXPANSION
# ================================================================

def get_page_number_list():

    numbers = []

    for key in PAGES.keys():

        try:
            numbers.append(
                int(key)
            )
        except Exception:
            pass

    return sorted(numbers)


PAGE_NUMBERS = get_page_number_list()


def get_page_record(page_number):

    if page_number in PAGES:
        return PAGES[page_number]

    string_key = str(page_number)

    if string_key in PAGES:
        return PAGES[string_key]

    return None


def collect_context_pages(
    candidate,
    pages_before=1,
    pages_after=1
):

    target_page = int(
        candidate["page"]
    )

    available = PAGE_NUMBERS

    previous = [
        p
        for p in available
        if (
            target_page
            - pages_before
            <= p
            < target_page
        )
    ]

    following = [
        p
        for p in available
        if (
            target_page
            < p
            <= target_page
            + pages_after
        )
    ]

    return (
        previous
        + [target_page]
        + following
    )


def build_context_for_candidates(
    candidates
):

    context_pages = set()

    for candidate in candidates:

        for page in collect_context_pages(
            candidate
        ):

            context_pages.add(page)

    context_pages = sorted(
        context_pages
    )

    page_context = []

    for page_number in context_pages:

        page_record = get_page_record(
            page_number
        )

        if not page_record:
            continue

        page_context.append({

            "page_number":
                page_number,

            "units":
                page_record.get(
                    "units",
                    []
                )
        })

    return page_context


# ================================================================
# 10. BUILD AZURE EVIDENCE PACKAGE
# ================================================================

def build_ai_evidence_package(
    query,
    candidates
):

    context_pages = (
        build_context_for_candidates(
            candidates
        )
    )

    return {

        "document": {
            "filename":
                DOCUMENT_INFO.get(
                    "filename"
                ),

            "document_id":
                DOCUMENT_INFO.get(
                    "document_id"
                ),

            "page_count":
                DOCUMENT_INFO.get(
                    "page_count"
                )
        },

        "user_query":
            query,

        "candidate_units":
            candidates,

        "context_pages":
            context_pages
    }


# ================================================================
# 11. AZURE SOURCE-GROUNDED REASONING
# ================================================================

def query_auditor_selection(
    user_query,
    candidates
):

    if not candidates:

        return {

            "classification":
                "NOT_VERIFIED",

            "answer":
                "No sufficiently relevant provision "
                "was retrieved from the indexed BSRR source.",

            "reasoning":
                "The local retrieval layer did not identify "
                "a sufficiently relevant source unit.",

            "confidence":
                0.0,

            "matched_sources": [],

            "limitations": [
                "No sufficiently relevant local candidates."
            ]
        }


    evidence_package = (
        build_ai_evidence_package(
            user_query,
            candidates
        )
    )


    system_prompt = """
You are the source-grounded reasoning component of a
maritime regulatory search application.

The source document is a ship recycling / shipbreaking
regulatory document.

Your task is to determine what the supplied source actually
establishes about the user's question.

============================================================
ABSOLUTE SOURCE RULE
============================================================

Use ONLY the supplied source evidence.

Do not use external legal knowledge.

Do not import requirements from other regulations,
countries, conventions, industry practice, or general
knowledge.

The source text is authoritative.

AI annotations are supporting metadata only.

============================================================
DOMAIN CONTEXT
============================================================

The document concerns ship recycling / shipbreaking.

The user may use informal terms such as:

- yard
- shipbreaking yard
- recycling yard
- ship recycler

Possible source terminology includes:

- ship recycling facility
- SRF
- ship recycler
- Ship Recycling Board
- competent authority
- Safety Officer
- ship recycling plan
- hazardous waste
- dismantling
- cutting operations

Use these concepts to interpret the query.

However, domain context is NOT evidence.

Do not assume that two terms are legally identical unless
the supplied source supports that interpretation.

============================================================
CROSS-PAGE CONTEXT
============================================================

A provision can continue across a page boundary.

Never assume that a page ending means that the provision ends.

Use surrounding page evidence when necessary.

============================================================
VERIFICATION
============================================================

Classify the answer as exactly one:

VERIFIED
PARTIALLY_VERIFIED
NOT_VERIFIED
CONTRADICTED
UNCERTAIN

VERIFIED:
The source explicitly establishes the proposition.

PARTIALLY_VERIFIED:
The source establishes only part of the proposition.

NOT_VERIFIED:
Relevant provisions exist, but they do not establish the
requested proposition.

CONTRADICTED:
The source explicitly indicates something inconsistent
with the proposition.

UNCERTAIN:
The supplied evidence is insufficient to determine the answer.

IMPORTANT:

A relevant provision is NOT automatically a verified answer.

============================================================
SOURCE CITATIONS
============================================================

Every substantive conclusion must cite actual source units.

Never invent source_unit_id values.

Never invent section numbers.

Never invent quotations.

When a provision spans multiple units, cite all relevant
units.

============================================================
ANSWER STYLE
============================================================

The user wants a practical regulatory search result.

Give:

1. Direct answer.
2. Verification classification.
3. Short reasoning.
4. Most relevant rule/provision.
5. Exact source text.
6. Page and block identification.
7. Confidence.
8. Any limitation.

============================================================
OUTPUT JSON
============================================================

Return JSON only:

{
  "classification": "VERIFIED",
  "answer": "...",
  "reasoning": "...",
  "best_match": {
    "source_unit_id": "...",
    "page": 0,
    "block_id": "...",
    "text": "..."
  },
  "matched_sources": [
    {
      "source_unit_id": "...",
      "page": 0,
      "block_id": "...",
      "text": "...",
      "relevance": 0.0,
      "reason": "..."
    }
  ],
  "confidence": 0.0,
  "limitations": []
}
"""


    user_prompt = f"""
USER QUESTION:

{user_query}

============================================================
RETRIEVED EVIDENCE
============================================================

{json.dumps(
    evidence_package,
    ensure_ascii=False,
    indent=2
)}

============================================================
TASK
============================================================

Determine whether the indexed source verifies the user's
question.

Use the surrounding page context where necessary.

Do not infer an obligation merely because the topic is related.

Return JSON only.
"""


    try:

        response = client.chat.completions.create(

            model=CHAT_DEPLOYMENT,

            temperature=0,

            messages=[

                {
                    "role":
                        "system",

                    "content":
                        system_prompt
                },

                {
                    "role":
                        "user",

                    "content":
                        user_prompt
                }

            ],

            response_format={
                "type": "json_object"
            },

            max_tokens=5000
        )


        content = (
            response
            .choices[0]
            .message
            .content
        )


        return json.loads(
            content
        )


    except Exception as e:

        return {

            "classification":
                "UNCERTAIN",

            "answer":
                "The AI verification step could not "
                "be completed.",

            "reasoning":
                f"Azure OpenAI error: {str(e)}",

            "best_match":
                None,

            "matched_sources":
                candidates,

            "confidence":
                0.0,

            "limitations": [
                "Azure reasoning request failed."
            ]
        }


# ================================================================
# 12. STREAMLIT SESSION STATE
# ================================================================

if "status_verdict" not in st.session_state:
    st.session_state.status_verdict = ""

if "analysis_text" not in st.session_state:
    st.session_state.analysis_text = ""

if "best_rule_code" not in st.session_state:
    st.session_state.best_rule_code = ""

if "best_match" not in st.session_state:
    st.session_state.best_match = None

if "all_retrieved_hits" not in st.session_state:
    st.session_state.all_retrieved_hits = []

if "confidence" not in st.session_state:
    st.session_state.confidence = 0.0

if "limitations" not in st.session_state:
    st.session_state.limitations = []


# ================================================================
# 13. MAIN UI
# ================================================================

st.title(
    "⚖️ High-Precision Statutory Reference Search Workspace"
)

st.caption(
    "Source-grounded maritime regulatory search — BSRR"
)


# ---------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------

st.sidebar.markdown(
    "### 🛠️ Framework Scope Filters"
)

selected_frameworks = st.sidebar.multiselect(

    label=
        "Choose target legal frameworks to query:",

    options=[
        "BSRR"
    ],

    default=[
        "BSRR"
    ]
)


st.sidebar.markdown("---")

st.sidebar.markdown(
    "### 📊 BSRR Index"
)

st.sidebar.caption(
    f"Pages: {len(PAGES)}"
)

st.sidebar.caption(
    f"Searchable units: "
    f"{len(SEARCHABLE_UNITS)}"
)

st.sidebar.caption(
    f"Document: "
    f"{DOCUMENT_INFO.get('filename', 'BSRR')}"
)


# ---------------------------------------------------------------
# Search box
# ---------------------------------------------------------------

user_search_input = st.text_input(

    label=
        "Enter Regulatory Question or Scenario:",

    placeholder=
        "e.g. Can a yard delegate statutory obligation "
        "to a subcontractor?"
)


# ---------------------------------------------------------------
# Search button
# ---------------------------------------------------------------

if st.button(
    "🔍 Analyze Frameworks & Search Correlated Rules",
    use_container_width=True
):

    if not selected_frameworks:

        st.warning(
            "Please select BSRR."
        )

    elif not user_search_input.strip():

        st.warning(
            "Please enter a regulatory question."
        )

    else:

        with st.spinner(
            "Retrieving source provisions and "
            "checking regulatory context..."
        ):

            # ----------------------------------------------------
            # Step 1: Local retrieval
            # ----------------------------------------------------

            matched_candidates = (
                extract_best_database_candidates(
                    user_search_input,
                    max_candidates=15
                )
            )


            st.session_state.all_retrieved_hits = (
                matched_candidates
            )


            if matched_candidates:

                # ------------------------------------------------
                # Step 2: Azure reasoning
                # ------------------------------------------------

                result = (
                    query_auditor_selection(
                        user_search_input,
                        matched_candidates
                    )
                )

                # ------------------------------------------------
                # Save result
                # ------------------------------------------------

                st.session_state.status_verdict = (
                    result.get(
                        "classification",
                        "UNCERTAIN"
                    )
                )

                st.session_state.analysis_text = (
                    result.get(
                        "reasoning",
                        ""
                    )
                )

                st.session_state.best_match = (
                    result.get(
                        "best_match"
                    )
                )

                st.session_state.confidence = (
                    float(
                        result.get(
                            "confidence",
                            0.0
                        )
                    )
                )

                st.session_state.limitations = (
                    result.get(
                        "limitations",
                        []
                    )
                )

                best_match = (
                    result.get(
                        "best_match"
                    )
                    or {}
                )


                if best_match:

                    st.session_state.best_rule_code = (
                        f"BSRR — "
                        f"Page "
                        f"{best_match.get('page', '?')}"
                        f" — "
                        f"{best_match.get('block_id', '?')}"
                    )

                else:

                    st.session_state.best_rule_code = (
                        "No verified source provision"
                    )

            else:

                st.session_state.status_verdict = (
                    "NOT_VERIFIED"
                )

                st.session_state.analysis_text = (
                    "No sufficiently relevant provision "
                    "was retrieved from the indexed BSRR source."
                )

                st.session_state.best_rule_code = (
                    "Not Found"
                )

                st.session_state.best_match = None

                st.session_state.confidence = 0.0

                st.session_state.limitations = [
                    "No sufficiently relevant local candidates."
                ]


# ================================================================
# 14. RESULTS
# ================================================================

if st.session_state.status_verdict:

    st.markdown("---")


    left_column, right_column = st.columns(
        [1, 2]
    )


    # ============================================================
    # LEFT — AI VERIFICATION
    # ============================================================

    with left_column:

        st.markdown(
            "### 🤖 Auditor Verification"
        )


        with st.expander(
            "📋 View Auditor Verdict & Analysis Details",
            expanded=True
        ):

            verdict = (
                st.session_state.status_verdict
            )


            if verdict == "VERIFIED":

                st.success(
                    f"📋 Status: {verdict}"
                )

            elif verdict == "PARTIALLY_VERIFIED":

                st.warning(
                    f"📋 Status: {verdict}"
                )

            elif verdict == "CONTRADICTED":

                st.error(
                    f"📋 Status: {verdict}"
                )

            elif verdict == "NOT_VERIFIED":

                st.info(
                    f"📋 Status: {verdict}"
                )

            else:

                st.warning(
                    f"📋 Status: {verdict}"
                )


            st.markdown(
                "### Answer"
            )

            # We don't store answer separately in this first
            # prototype, so derive it from the result if needed.
            #
            # The best_match / reasoning remain the primary
            # inspectable evidence.

            best_match = (
                st.session_state.best_match
            )

            if best_match:

                st.markdown(
                    f"**Most Relevant Source:** "
                    f"`{st.session_state.best_rule_code}`"
                )

            else:

                st.markdown(
                    "**Most Relevant Source:** "
                    "`No verified source provision`"
                )


            st.markdown(
                "### 💡 Reasoning"
            )

            st.write(
                st.session_state.analysis_text
            )


            confidence = (
                st.session_state.confidence
            )

            st.metric(
                "AI Verification Confidence",
                f"{confidence * 100:.1f}%"
            )


            limitations = (
                st.session_state.limitations
            )

            if limitations:

                st.markdown(
                    "### ⚠️ Limitations"
                )

                for limitation in limitations:

                    st.write(
                        f"• {limitation}"
                    )


            # ----------------------------------------------------
            # Best exact source
            # ----------------------------------------------------

            if best_match:

                st.markdown(
                    "### 📖 Exact Source"
                )

                st.caption(
                    f"Page {best_match.get('page', '?')} "
                    f"| Block {best_match.get('block_id', '?')} "
                    f"| {best_match.get('source_unit_id', '?')}"
                )

                st.code(
                    best_match.get(
                        "text",
                        ""
                    ),
                    language=None
                )


    # ============================================================
    # RIGHT — RETRIEVED PROVISIONS
    # ============================================================

    with right_column:

        hits = (
            st.session_state.all_retrieved_hits
        )


        st.markdown(
            f"### 🔍 Correlated Statutory Search Results "
            f"({len(hits)} matches found)"
        )

        st.caption(
            "Results are retrieved from the indexed BSRR "
            "source before AI verification."
        )


        best_match = (
            st.session_state.best_match
            or {}
        )

        best_source_id = (
            best_match.get(
                "source_unit_id"
            )
        )


        for idx, item in enumerate(hits):

            is_chosen = (
                item.get(
                    "source_unit_id"
                )
                == best_source_id
            )


            if is_chosen:

                expander_title = (
                    f"🎯 [{idx + 1}] "
                    f"BSRR — Page "
                    f"{item.get('page', '?')} "
                    f"(AI Selected)"
                )

                should_open = True

            else:

                expander_title = (
                    f"📜 [{idx + 1}] "
                    f"BSRR — Page "
                    f"{item.get('page', '?')}"
                )

                should_open = (
                    idx == 0
                )


            with st.expander(
                f"{expander_title} | "
                f"Score: "
                f"{item.get('relevance_score', 0):.4f}",
                expanded=should_open
            ):

                st.markdown(
                    f"**Source Unit:** "
                    f"`{item.get('source_unit_id', 'N/A')}`"
                )

                st.markdown(
                    f"**Page:** "
                    f"{item.get('page', 'N/A')} "
                    f"| **Block:** "
                    f"{item.get('block_id', 'N/A')}"
                )


                annotation = (
                    item.get(
                        "annotation"
                    )
                    or {}
                )


                marker = annotation.get(
                    "marker"
                )

                unit_type = annotation.get(
                    "unit_type"
                )


                if marker:

                    st.markdown(
                        f"**Marker:** `{marker}`"
                    )


                if unit_type:

                    st.markdown(
                        f"**Unit type:** `{unit_type}`"
                    )


                st.markdown(
                    "**Source Text:**"
                )

                st.code(
                    item.get(
                        "text",
                        ""
                    ),
                    language=None
                )


                # ------------------------------------------------
                # Context pages
                # ------------------------------------------------

                context_pages = (
                    collect_context_pages(
                        item
                    )
                )


                st.caption(
                    "Available context pages: "
                    + ", ".join(
                        str(p)
                        for p in context_pages
                    )
                )


# ================================================================
# 15. FOOTER
# ================================================================

st.markdown("---")

st.caption(
    "BSRR source-grounded prototype • "
    "Search retrieval and AI verification are "
    "based on the indexed source dataset."
)