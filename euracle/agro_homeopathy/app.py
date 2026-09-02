# =========================
# Silence harmless HF / Torch warnings
# =========================
import warnings

warnings.filterwarnings(
    "ignore",
    message=".*torch.distributed.reduce_op.*",
    category=FutureWarning,
)

# =========================
# Imports
# =========================
import os
import re
import math
import json
import pickle
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional, Set

import gradio as gr
from dotenv import load_dotenv

try:
    from langdetect import detect, LangDetectException
except ImportError as e:
    raise ImportError(
        "This app requires the 'langdetect' package for language-matched "
        "replies. Install it with: pip install langdetect"
    ) from e

from langchain_groq import ChatGroq
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain_core.embeddings import Embeddings
from langchain_core.documents import Document

# -------------------------
# Vectorstore imports
# -------------------------
try:
    from langchain_chroma import Chroma
except Exception:
    from langchain_community.vectorstores import Chroma

from langchain_community.document_loaders import PyPDFLoader

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except Exception:
    from langchain.text_splitter import RecursiveCharacterTextSplitter

# -------------------------
# Embedding / reranker
# -------------------------
from sentence_transformers import SentenceTransformer, CrossEncoder


# =========================
# App configuration
# =========================

APP_TITLE = "🌿 Dr. Radha: AI-Powered Organic Farming Consultant"

# IMPORTANT:
# This is intentionally different from the old "vector_db" directory.
# The old database was created using all-MiniLM-L6-v2.
PERSIST_DIR = Path("vector_db_bge_hybrid")
PERSIST_DIR.mkdir(exist_ok=True)

# Incremental-ingestion bookkeeping files.
MANIFEST_PATH = PERSIST_DIR / "manifest.json"
BM25_STATE_PATH = PERSIST_DIR / "bm25_state.pkl"

# -------------------------
# Models
# -------------------------

# Better retrieval embedding model than all-MiniLM-L6-v2.
# BGE-small-en-v1.5 is lightweight enough for a free HF CPU Space.
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

# Dense retrieval is optional and lazy-loaded.
# Exact/BM25 retrieval is always attempted first. Dense retrieval is used only
# when lexical retrieval does not establish meaningful evidence.
DENSE_FALLBACK_ENABLED = False

# Cross-encoder reranking is lazy-loaded. It is a ranking aid only; it
# NEVER decides source authority or whether evidence exists. Exact phrase
# matches bypass it entirely. On a cold first turn it is also skipped, so
# the first response does not wait for a large reranker model to download.
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANKER_CANDIDATES = 16

# Recommended Groq model for this application.
# If your Groq account/API does not expose this exact model ID,
# replace it with the currently available GPT-OSS 120B model ID.
GROQ_MODEL = "openai/gpt-oss-120b"

TEMPERATURE = 0.0

# -------------------------
# Retrieval configuration
# -------------------------

# BM25 candidate count.
BM25_TOP_K = 20

# Maximum number of primary chunks sent to the LLM.
TOP_K = 4

# Maximum number of supplementary chunks from lower-priority tiers.
SUPPLEMENTARY_TOP_K_PER_TIER = 1

# Candidate count used by the optional dense fallback.
DENSE_FETCH_K = 12

# Chunking
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150

# Reciprocal Rank Fusion constant. 60 is the standard default from
# the original RRF paper and works well without tuning.
RRF_K = 60

# Maximum number of previous conversation turns used for query rewriting.
QUERY_REWRITE_HISTORY_TURNS = 2

# -------------------------
# Cascading (tiered) retrieval configuration
# -------------------------
#
# Retrieval is attempted first against ONLY the highest-priority tier's
# source PDFs. Exact domain matches in the highest-priority source stop
# the cascade immediately; otherwise retrieval expands to lower tiers.
# The final stage always searches the ENTIRE corpus unrestricted, so
# any PDF present in the app directory but not explicitly listed below
# is still searchable (as an implicit lowest-priority fallback) rather
# than being silently excluded.
#
# Filenames must exactly match the "source" metadata stored per chunk,
# which is simply the PDF's filename in the app directory (see
# base_dir_pdfs() / chunk_pdf()).
RETRIEVAL_TIERS: List[List[str]] = [
    # Tier 1 — highest priority: the core repertory.
    [
        "Agro_Homeopathy_Repertory.pdf",
    ],
    # Tier 2 — supporting practitioner references.
    [
        "Homeopathic_Treatment_of_Plants.pdf",
        "article1.pdf",
        "DEI-DEP Annual Magazine 2020-21_final.pdf",
    ],
    # Tier 3 — general organic farming background.
    [
        "Organic_Farming_Everything_You_Need_to_Know_s.pdf",
        "The Market Gardener-A Successful Growers Handbook for Small-scale Organic Farming.pdf",
    ],
]

load_dotenv()


# =========================
# Mandatory Usage Technique
# =========================

USAGE_INSTRUCTIONS = """
Preparation and Application of Homeopathic Spray:
1. Fill a clean bottle with approximately 200 mL of tap, spring, or rainwater.
2. Add 30 drops (or 7 globules) of the selected homeopathic remedy to the bottle. If using a combination of two or more remedies, add 15 drops of each remedy instead.
3. Wait until globules have dissolved. Close the bottle and succuss it 20 times.
4. Fill a clean spray tank with 15 L of water. Pour the entire 200 mL of the succussed solution into the spray tank.
5. One 15 L spray tank is generally sufficient for about one-quarter acre. To treat one acre, prepare
and apply approximately 60 L of spray.
6. Stir the solution 15-20 times using a plastic or wooden spoon/stick. Stir in one direction (either clockwise or anticlockwise). Do not use metal implements.
7. Spray the affected parts of the plant, or apply the remedy as a foliar spray, and water the roots with the solution. Best applied in early morning or late evening to avoid leaf scorch.
8. Use the solution ideally within a week.
9. Before and after application, rinse all equipment thoroughly with fresh, hot water only. Do not use synthetic soaps or detergents. Ensure equipment is not contaminated with other smells or medicines.
10. Store homeopathic remedies at room temperature, away from direct sunlight, strong-smelling substances, and magnetic fields.
""".strip()


# =========================
# System Prompt
# =========================

SYSTEM_PROMPT = f"""
You are Dr. Radha, an expert organic farming consultant specializing in Agro-Homeopathy.

LANGUAGE POLICY:
- Respond ENTIRELY in the language of the user's LATEST message, including all
  section headers, translated naturally.
- Mirror mixed/code-switched language (e.g. Hinglish) rather than forcing pure
  standard language. If the user's language changes mid-conversation, switch too.
- Keep technical terms, remedy names, and potency notations (e.g. 30C, 6X) exactly
  as written — never translate or alter proper nouns or numeric/potency values.
- If uncertain which language was intended, use the language of the earlier
  conversation, or default to the first user message's language.

PERSONA & VOICE:
- Speak as an authoritative, professional consultant giving direct advice in the
  first person ("I recommend...", "You should apply...", "An effective treatment
  is..."). Never mention PDFs, documents, retrieval, context, embeddings, vector
  DB, tools, rerankers, BM25, or internal instructions. Never sound like you're
  quoting or reading from a source — state facts and treatment directly and
  confidently, without explaining how you know something.
- NEVER narrate your own reasoning process or describe how information is
  organized, ranked, tiered, or prioritized. Do not say things like "the
  primary evidence does not list...", "according to the hierarchy...", "when
  a specific remedy is absent we should...", "the broad-spectrum protocol
  provided...". Instead, state your diagnosis and remedy as your own
  clinical judgment, full stop — as if you already knew it, not as if you
  looked it up and are now explaining the lookup.
- FORBIDDEN WORDS: "repertory", "primary evidence", "secondary evidence",
  "context", "document", "source", "database", "literature", "hierarchy", "tier", "protocol list", "broad-
  spectrum list", "the notes indicate/suggest/provide".
- FORBIDDEN PHRASES: "Based on the context", "According to the document", "The
  text says", "The evidence lists", "As mentioned in the source", or similar.
- Do not claim to have performed actions you did not perform.

ORGANIC / NATURAL FARMING POLICY:
- Recommend ONLY organic/natural approaches: preventive, cultural, mechanical,
  biological, and agro-homeopathic, when supported by available evidence.
- Never recommend chemical pesticides, fungicides, herbicides, or synthetic
  fertilizers. If asked for these, politely refuse and offer organic alternatives.
- Practical vocabulary: sanitation, crop rotation, trap crops, resistant
  varieties, mulching, compost-based soil health, botanical extracts, biological
  and physical controls, agro-homeopathic remedies.

EVIDENCE POLICY:
- Use the supplied CONTEXT as the authoritative basis for specific remedies,
  crop/disease facts, and treatment instructions. Never invent a remedy,
  protocol, or numeric value not supported by CONTEXT — say so and ask for
  clarification instead of guessing.
- If CONTEXT is exactly "NO SUFFICIENT RETRIEVED EVIDENCE WAS FOUND FOR THIS
  QUESTION.", do not answer the substantive question from general knowledge —
  state only that the available information doesn't support a specific
  recommendation. Never claim a remedy doesn't exist unless CONTEXT says so.
- PRIMARY EVIDENCE (the highest-priority source with meaningful evidence)
  controls the answer. SUPPLEMENTARY EVIDENCE may add compatible detail but
  never overrides a supported PRIMARY remedy, potency, or dosage.

POTENCY GUIDELINES (when not specified in evidence):
- Soil: lower potencies (6X, 6C, especially 12C) work best; 3X tissue salts are
  an option but 6C/12C often perform better.
- Insects/Pests: higher potencies for stronger effect; use 200C for fast-moving
  acute infestations.
- Diseases: 30C for persistent slow-progressing disease; 200C for rapid/severe
  spread.
- If the specified potency is unavailable, use the closest one you have — giving
  the plant the remedy matters more than exact potency.

PRECAUTIONS & FREQUENCY:
- Keep a minimum 2-week gap between Silicea and Sulphur (they antidote each
  other); don't apply Silicea too frequently.
- Never recommend Allium sativum or Allium cepa on beans or peas.
- Aggressive/fast-moving problems: treat 3 consecutive days, wait 1 week to
  assess, repeat another 3 days if improved but not resolved.
- Prophylactic use: apply before symptoms at 7-day intervals during high-risk
  periods.
- Soil deficiencies: one treatment per 2 weeks during the growing season.
- Fast-moving pests/diseases: expect results in 2-4 days or change remedy; for
  slow chronic issues, wait 1 week before assessing.

CONVERSATIONAL CONTEXT:
- Use history to resolve references ("it", "this remedy", "how often", etc.).
- Don't treat a previous assistant statement as fact unless also supported by
  the current CONTEXT.

CLARIFYING QUESTIONS — FIRST MESSAGE ONLY:
- Each turn includes a note on whether it's the first message — follow it
  exactly, overriding your own judgment.
- FIRST message: if key details are missing, ask up to 3 concise clarifying
  questions (checklist format) before any treatment — e.g. crop/variety/stage,
  symptoms and location/spread rate, pest signs, fungal/bacterial signs,
  weather/irrigation/soil, recent sprays or amendments.
- SECOND message onward: never ask further clarifying questions, even with
  missing info. Proceed directly to Analysis/Treatment using best available
  information, note assumptions explicitly, and reserve Escalate/Consult for
  genuine safety concerns only.

MEDICINE RULES:
- Suggest all relevant remedies from the evidence, in order of relevance, with
  repetition frequency per PRECAUTIONS & FREQUENCY above.
- If not confident enough to recommend a specific medicine, don't guess — give
  only supported organic steps and ask clarifying questions instead.

SAFETY:
- Add an "Escalate/Consult" note for severe cases (rapid spread, major wilting,
  suspected chemical burn, food safety concerns), advising the user to consult
  a Subject Matter Expert (SME) before acting.

MANDATORY USAGE TECHNIQUE:
- If you prescribe ANY agro-homeopathic medicine in Treatment, include the
  following text EXACTLY, translated naturally into the user's language but
  with all numeric dosage values unchanged:
{USAGE_INSTRUCTIONS}

RESPONSE FORMAT (do not translate the mode marker):
- The very first line of every response is exactly one of these two tokens,
  on its own line, followed by a blank line: [MODE:CLARIFY] or [MODE:ANSWER].
  This is stripped before the user sees it — always output it in this exact
  English form regardless of reply language.
- [MODE:CLARIFY] — used only on the first message, only if this entire
  response is the Clarifying questions section. Output nothing else (no
  Analysis, Treatment, Usage technique, Recommendations, or Escalate/Consult).
  Format:
  Clarifying questions:
  - ...
  - ...
- [MODE:ANSWER] — used for every other case (second turn onward, or first turn
  with enough info). Format:
  Analysis:
  ...

  Treatment:
  ...

  Usage technique:
  ...

  How to apply (short):
  ...

  Recommendations:
  - ...
  - ...
  - ...

  Escalate/Consult:
  ...
- The two modes are mutually exclusive — never mix Clarifying questions with
  Treatment/Usage technique in the same response.
""".strip()


# =========================
# BGE Embedding Wrapper
# =========================

class BGEEmbeddings(Embeddings):
    """
    LangChain-compatible wrapper around SentenceTransformers BGE embeddings.

    BGE recommends using the retrieval instruction for queries while
    embedding passages without the query instruction.
    """

    QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

    def __init__(self, model_name: str):
        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=32,
        )
        return embeddings.tolist()

    def embed_query(self, text: str) -> List[float]:
        query = self.QUERY_INSTRUCTION + text
        embedding = self.model.encode(
            query,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embedding.tolist()


# =========================
# BM25 Implementation
# =========================

class SimpleBM25:
    """
    Lightweight BM25 implementation.

    This avoids requiring an additional rank_bm25 package,
    which is useful for a simple Hugging Face Space deployment.

    Instances are plain-data (lists/dicts/floats) and are therefore
    safely picklable, so the index can be persisted to disk instead
    of being rebuilt from scratch on every process start.
    """

    def __init__(
        self,
        documents: List[str],
        k1: float = 1.5,
        b: float = 0.75,
    ):
        self.documents = documents
        self.k1 = k1
        self.b = b

        self.tokenized_docs = [
            self.tokenize(doc)
            for doc in documents
        ]

        self.doc_lengths = [
            len(tokens)
            for tokens in self.tokenized_docs
        ]

        self.avgdl = (
            sum(self.doc_lengths) / len(self.doc_lengths)
            if self.doc_lengths
            else 0.0
        )

        self.doc_freqs = []
        self.idf = {}

        self._build_index()

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """
        Tokenization deliberately preserves numbers, decimals,
        potency values and common technical terms.
        """
        text = text.lower()

        tokens = re.findall(
            r"[a-zA-Z]+(?:[-'][a-zA-Z]+)*|\d+(?:\.\d+)?[a-zA-Z]*",
            text,
        )

        return tokens

    def _build_index(self):
        num_docs = len(self.tokenized_docs)

        df = {}

        for tokens in self.tokenized_docs:
            unique_tokens = set(tokens)

            for token in unique_tokens:
                df[token] = df.get(token, 0) + 1

        self.idf = {
            token: math.log(
                1.0 + (num_docs - freq + 0.5) / (freq + 0.5)
            )
            for token, freq in df.items()
        }

        for tokens in self.tokenized_docs:
            freq = {}

            for token in tokens:
                freq[token] = freq.get(token, 0) + 1

            self.doc_freqs.append(freq)

    def get_scores(self, query: str) -> List[float]:
        query_tokens = self.tokenize(query)

        scores = [0.0] * len(self.documents)

        if not query_tokens or not self.documents:
            return scores

        for doc_idx, freq_dict in enumerate(self.doc_freqs):
            doc_len = self.doc_lengths[doc_idx]

            if doc_len == 0:
                continue

            for token in query_tokens:
                if token not in freq_dict:
                    continue

                idf = self.idf.get(token, 0.0)

                tf = freq_dict[token]

                denominator = (
                    tf
                    + self.k1
                    * (
                        1
                        - self.b
                        + self.b
                        * doc_len
                        / max(self.avgdl, 1e-9)
                    )
                )

                score = (
                    idf
                    * tf
                    * (self.k1 + 1)
                    / denominator
                )

                scores[doc_idx] += score

        return scores

    def top_n(
        self,
        query: str,
        n: int,
    ) -> List[Tuple[int, float]]:
        scores = self.get_scores(query)

        ranked = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True,
        )

        return ranked[:n]


# =========================
# Helpers
# =========================

def base_dir_pdfs() -> List[str]:
    return [
        f
        for f in os.listdir(".")
        if f.lower().endswith(".pdf")
    ]


def extract_text(msg: Any) -> str:
    if isinstance(msg, str):
        return msg

    elif isinstance(msg, list):
        parts = []

        for x in msg:
            if isinstance(x, dict) and "text" in x:
                parts.append(x["text"])

            elif isinstance(x, str):
                parts.append(x)

        return " ".join(parts) if parts else str(msg)

    elif isinstance(msg, tuple):
        return str(msg[0])

    return str(msg)


def strip_usage_block_for_history(text: str) -> str:
    """The mandatory Usage Technique block (~200 tokens) doesn't need to
    be replayed back to the model as conversation history — it's static
    boilerplate the model already knows how to regenerate. Stripping it
    from history (not from what the user sees) is one of the biggest
    single wins against token bloat, since it re-appears on every turn
    that prescribed a remedy."""
    for block in _usage_block_cache.values():
        if block and block in text:
            text = text.replace(block, "[usage instructions — omitted from history]")
    return text

    
def to_lc_messages(history, max_turns=2):
    msgs = []
    turns = 0
    for m in history:
        role = m.get("role")
        content = extract_text(m.get("content", ""))

        if role == "user":
            msgs.append(HumanMessage(content=content))
            turns += 1
        elif role == "assistant":
            content = strip_usage_block_for_history(content)   # <-- add this
            msgs.append(AIMessage(content=content))

        if turns >= max_turns:
            break
    return msgs


def format_docs_for_context(docs) -> str:
    formatted = []
    for i, d in enumerate(docs):
        source = Path(d.metadata.get("source", "")).name
        page = d.metadata.get("page")
        page_label = f", page {int(page) + 1}" if page is not None else ""
        formatted.append(f"[{i + 1}] ({source}{page_label}) {d.page_content.strip()}")
    return "\n\n".join(formatted)


POTENCY_MENTION_PATTERN = re.compile(
    r"\b\d+\s?(?:c|ch|x)\b",
    re.IGNORECASE,
)


def response_prescribes_treatment(text: str) -> bool:
    """
    Language-agnostic check for whether the response prescribes an
    agro-homeopathic remedy. Relies on potency notation (e.g. "30C",
    "6X") since the system prompt requires potency values to stay in
    their original notation regardless of reply language — unlike
    English keywords such as "pill" or "remedy", which won't appear
    in a non-English response.
    """
    if POTENCY_MENTION_PATTERN.search(text):
        return True

    # Belt-and-suspenders fallback for English replies specifically.
    treatment_words = [
        " 6C",
        " 30C",
        "pill",
        "pills",
        "ml",
        "remedy",
        "medicine",
    ]

    return any(w.lower() in text.lower() for w in treatment_words)


def usage_technique_already_present(text: str) -> bool:
    """
    Language-agnostic check for whether the mandatory usage-technique
    block is already present. The literal header "Usage technique"
    only reliably appears in English replies, so this also checks for
    the mandated dosage figures (200ml, 500 pills, etc.), which the
    system prompt requires to stay numerically unchanged in every
    language.
    """
    if "usage technique" in text.lower():
        return True

    present_numbers = extract_numeric_claims(text) & _USAGE_INSTRUCTION_NUMBERS

    return len(present_numbers) >= 2


# Cache of the "Usage technique:\n<instructions>" block translated into
# each detected language, so each language is only translated once per
# process lifetime rather than on every single response.
_usage_block_cache: Dict[str, str] = {
    "en": "Usage technique:\n" + USAGE_INSTRUCTIONS
}

USAGE_TRANSLATE_SYSTEM = """
You are a precise technical translator.

Translate the given "Text to translate" into the SAME language as the
"Reference text" below (do not translate into any other language, and
do not explain your choice).

Rules:
- Preserve ALL numbers, units (ml, l, pills, hectares, days, months),
  and dosage figures EXACTLY as written — do not change, round,
  reformat, or convert them.
- Preserve the line breaks and structure of the original text.
- Keep the heading "Usage technique" translated naturally as a heading.
- Do not add, remove, or explain anything. Output ONLY the translated
  text, nothing else.
- If the reference text is already in English, output the text to
  translate unchanged.
""".strip()


def build_usage_translator(llm):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", USAGE_TRANSLATE_SYSTEM),
            (
                "human",
                "Reference text (for language only):\n{reference}\n\n"
                "Text to translate:\n{source_text}\n\n"
                "Translated text:",
            ),
        ]
    )

    return prompt | llm | StrOutputParser()


def detect_language_code(text: str) -> str:
    try:
        return detect(text)
    except LangDetectException:
        return "en"


def get_translated_usage_block(
    user_message: str,
    translator,
) -> str:
    """
    Returns the mandatory "Usage technique" block translated into the
    same language as `user_message`, using a cached translation so the
    LLM is only called once per distinct language per process run.
    Falls back to the original English block if detection or
    translation fails for any reason.
    """
    lang_code = detect_language_code(user_message)

    if lang_code in _usage_block_cache:
        return _usage_block_cache[lang_code]

    try:
        translated = translator.invoke(
            {
                "reference": user_message,
                "source_text": _usage_block_cache["en"],
            }
        ).strip()

        if translated:
            _usage_block_cache[lang_code] = translated
            return translated

    except Exception:
        pass  # Fall back to English below rather than fail the whole reply.

    return _usage_block_cache["en"]


def ensure_usage_technique(
    text: str,
    user_message: str,
    translator,
) -> str:
    """
    Safety net: if the model prescribed a remedy but forgot to include
    the mandatory usage-technique section, append it — translated into
    the same language as the user's question.
    """
    if (
        response_prescribes_treatment(text)
        and not usage_technique_already_present(text)
    ):
        usage_block = get_translated_usage_block(
            user_message,
            translator,
        )

        text += "\n\n" + usage_block

    return text


# =========================
# Numeric / Potency Grounding Check
# =========================
#
# The system prompt instructs the LLM never to invent a specific
# dosage, potency, or numeric treatment value that isn't backed by
# the retrieved CONTEXT. LLMs don't reliably self-police this, so
# this is a cheap, deterministic, regex-based safety net that runs
# AFTER generation and flags any numeric/potency claim in the answer
# that doesn't actually appear anywhere in the retrieved context.

# Matches things like: 30C, 6X, 200ml, 500 ml, 1M, 125ml, 10 liters,
# 500 pills, 2500 pills, 10%, 3 months.
NUMERIC_CLAIM_PATTERN = re.compile(
    r"""
    \b\d+(?:\.\d+)?\s*
    (?:
        c\b | ch\b | x\b | m\b |            # homeopathic potencies (C, CH, X, M)
        ml\b | l\b | liters?\b | litres?\b | # liquid measures
        pills?\b | drops?\b |                # dosage units
        %\b |                                # percentage
        hectares?\b | ha\b |                 # area
        months?\b | days?\b | weeks?\b       # duration
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_numeric_claims(text: str) -> Set[str]:
    """
    Extract normalized numeric/potency tokens (e.g. '30c', '200ml')
    from a piece of text so they can be compared for grounding.
    """
    if not text:
        return set()

    matches = NUMERIC_CLAIM_PATTERN.findall(text)
    # findall with groups returns the whole match differently, so
    # use finditer to reliably get full matched spans.
    matches = [
        m.group(0)
        for m in NUMERIC_CLAIM_PATTERN.finditer(text)
    ]

    normalized = {
        re.sub(r"\s+", "", m.lower())
        for m in matches
    }

    return normalized


# Numbers that legitimately appear in the mandatory usage technique
# block are not "claims" the model invented — they're pasted verbatim
# from USAGE_INSTRUCTIONS — so they should never trigger a warning.
_USAGE_INSTRUCTION_NUMBERS = extract_numeric_claims(USAGE_INSTRUCTIONS)


def check_numeric_grounding(
    answer: str,
    context: str,
) -> List[str]:
    """
    Returns the list of numeric/potency tokens present in the answer
    that are NOT supported by the retrieved context (and are not part
    of the fixed, always-appended usage-technique boilerplate).
    """
    answer_claims = extract_numeric_claims(answer)
    context_claims = extract_numeric_claims(context)

    ungrounded = sorted(
        answer_claims - context_claims - _USAGE_INSTRUCTION_NUMBERS
    )

    return ungrounded


def apply_numeric_grounding_check(
    answer: str,
    context: str,
) -> str:
    """
    Appends a visible caution note if the answer contains numeric or
    potency claims that could not be verified against retrieved
    evidence. This never blocks the response (the system prompt
    already tries to prevent invented numbers) — it's a transparent
    safety net for the rare cases where the LLM doesn't comply.
    """
    if context.strip() == "NO SUFFICIENT RETRIEVED EVIDENCE WAS FOUND FOR THIS QUESTION.":
        # Evidence gate already fired; nothing further to add here.
        return answer

    ungrounded = check_numeric_grounding(answer, context)

    if ungrounded:
        print(
            f"[grounding-check] Ungrounded numeric/potency claims detected: {ungrounded}"
        )

        answer += (
            "\n\n⚠️ Note: This response includes specific figures "
            "(dosage, potency, or timing) that could not be fully "
            "verified against the source material. Please treat "
            "these as indicative only and confirm with a Subject "
            "Matter Expert before applying them."
        )

    return answer


# =========================
# Query Rewriting
# =========================

QUERY_REWRITE_SYSTEM = """
You rewrite a user's latest question into a standalone retrieval query.

Rules:
- Use the conversation history only to resolve references such as:
  "it", "this", "that remedy", "the same disease", "how often", etc.
- Preserve the user's actual intent.
- Do NOT answer the question.
- Do NOT add facts that are not present in the conversation.
- Do NOT add recommendations.
- Do NOT expand the question unnecessarily.
- Return ONLY the rewritten standalone search query.
""".strip()


def build_query_rewriter(llm):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", QUERY_REWRITE_SYSTEM),
            (
                "human",
                "Conversation:\n{history}\n\n"
                "Latest user question:\n{question}\n\n"
                "Standalone retrieval query:",
            ),
        ]
    )

    return prompt | llm | StrOutputParser()


def history_to_text(
    history: List[BaseMessage],
    max_messages: int = 12,
) -> str:

    recent = history[-max_messages:]

    lines = []

    for msg in recent:
        if isinstance(msg, HumanMessage):
            role = "User"

        elif isinstance(msg, AIMessage):
            role = "Assistant"

        else:
            role = "Message"

        content = extract_text(
            getattr(msg, "content", "")
        )

        lines.append(
            f"{role}: {content}"
        )

    return "\n".join(lines)


# =========================
# Incremental Ingestion Bookkeeping
# =========================

def compute_file_hash(path: str) -> str:
    """Fast file fingerprint used for incremental ingestion.

    Reading every PDF byte on the first request can itself create a
    noticeable cold-start delay. Size + modification timestamp is enough
    for this deployment's change detection and avoids scanning entire PDFs.
    """
    stat = os.stat(path)
    return f"{stat.st_size}:{stat.st_mtime_ns}"

def load_manifest() -> Dict[str, str]:
    if not MANIFEST_PATH.exists():
        return {}

    try:
        with open(MANIFEST_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_manifest(manifest: Dict[str, str]) -> None:
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def load_bm25_state() -> Optional[Dict[str, Any]]:
    if not BM25_STATE_PATH.exists():
        return None

    try:
        with open(BM25_STATE_PATH, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def save_bm25_state(documents: List[Document], bm25: SimpleBM25) -> None:
    with open(BM25_STATE_PATH, "wb") as f:
        pickle.dump(
            {"documents": documents, "bm25": bm25},
            f,
        )


def chunk_pdf(pdf_path: str, splitter) -> List[Document]:
    pages = PyPDFLoader(pdf_path).load()

    for p in pages:
        p.metadata["source"] = pdf_path

    chunks = splitter.split_documents(pages)

    for chunk in chunks:
        source = chunk.metadata.get("source", "")
        page = chunk.metadata.get("page", None)

        chunk.metadata["source"] = source

        if page is not None:
            chunk.metadata["page"] = page

    return chunks


# =========================
# Vectorstore
# =========================

# Lazy model/vector-store state. Keeping the transformer out of process
# startup is important on CPU-based Hugging Face Spaces.
_embeddings = None
_vectorstore = None
_bm25 = None
_bm25_documents = None
_dense_index_stale = False
_reranker = None


def get_embeddings():
    global _embeddings

    if _embeddings is None:
        print(f"[startup] Loading embedding model lazily: {EMBED_MODEL}")
        _embeddings = BGEEmbeddings(model_name=EMBED_MODEL)

    return _embeddings


# =========================
# Vectorstore / BM25 state
# =========================

def load_vectorstore(require_dense: bool = False):
    """
    Load the persistent retrieval state.

    BM25 is loaded first because it is extremely cheap and powers the
    fast exact-match path. The BGE embedding model and Chroma vector
    store are created only when dense retrieval is actually requested.

    This avoids the previous cold-start penalty where the transformer
    was constructed before the first user message.
    """
    global _vectorstore, _bm25, _bm25_documents, _dense_index_stale

    if _bm25_documents is not None and (not require_dense or _vectorstore is not None):
        return _vectorstore

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    pdfs = base_dir_pdfs()
    if not pdfs:
        raise RuntimeError("No PDF files were found in the application directory.")

    current_hashes = {pdf: compute_file_hash(pdf) for pdf in pdfs}
    manifest = load_manifest()

    bm25_state = load_bm25_state()
    if bm25_state is not None:
        _bm25_documents = bm25_state.get("documents", [])
        _bm25 = bm25_state.get("bm25")
    else:
        _bm25_documents = []
        _bm25 = None

    new_or_changed = [
        pdf for pdf in pdfs
        if manifest.get(pdf) != current_hashes.get(pdf)
    ]
    removed = [pdf for pdf in manifest if pdf not in current_hashes]

    needs_bm25_rebuild = False

    # Remove stale BM25 chunks. Dense deletion/update is deferred until
    # dense retrieval is actually needed.
    for pdf in set(new_or_changed) | set(removed):
        _bm25_documents = [
            d for d in _bm25_documents
            if d.metadata.get("source", "") != pdf
        ]
        needs_bm25_rebuild = True

    # Ingest changed PDFs into the lightweight BM25 index immediately.
    for pdf in new_or_changed:
        chunks = chunk_pdf(pdf, splitter)
        if chunks:
            _bm25_documents.extend(chunks)
        needs_bm25_rebuild = True

    if _bm25 is None or needs_bm25_rebuild:
        texts = [d.page_content for d in _bm25_documents]
        _bm25 = SimpleBM25(texts)
        save_bm25_state(_bm25_documents, _bm25)

    save_manifest(current_hashes)

    if require_dense and _vectorstore is None:
        _vectorstore = Chroma(
            persist_directory=str(PERSIST_DIR),
            embedding_function=get_embeddings(),
            collection_name="agro_homeopathy_bge",
        )

        # If PDFs changed since the dense index was built, do not silently
        # embed them during the user's request. The fast BM25 path remains
        # authoritative for the current request.
        if new_or_changed or removed:
            _dense_index_stale = True

    return _vectorstore


# =========================
# Lazy cross-encoder reranker
# =========================

def get_reranker():
    global _reranker

    if _reranker is None:
        print(f"[retrieval] Loading reranker lazily: {RERANKER_MODEL}")
        _reranker = CrossEncoder(RERANKER_MODEL, max_length=512)

    return _reranker


def rerank_candidates(
    query: str,
    documents: List[Document],
    limit: int = TOP_K,
    allow_cold_load: bool = False,
) -> List[Document]:
    """Rank candidates within an already-selected authority tier.

    The cross-encoder is deliberately NOT used as an evidence gate.
    """
    if not documents:
        return []

    if len(documents) <= 1:
        return documents[:limit]

    # Do not cold-load the cross-encoder during the first user request.
    # BM25/exact ranking remains deterministic and fast. The reranker can be
    # used later once explicitly allowed.
    if _reranker is None and not allow_cold_load:
        return documents[:limit]

    reranker = get_reranker()
    candidates = documents[:RERANKER_CANDIDATES]
    pairs = [[query, doc.page_content] for doc in candidates]
    scores = reranker.predict(
        pairs,
        batch_size=8,
        show_progress_bar=False,
    )

    ranked = sorted(
        zip(candidates, scores),
        key=lambda x: float(x[1]),
        reverse=True,
    )
    return [doc for doc, _ in ranked[:limit]]


# =========================
# Domain-aware retrieval
# =========================

QUERY_STOPWORDS = {
    "how", "what", "why", "when", "where", "which", "who",
    "can", "could", "should", "would", "do", "does", "did",
    "is", "are", "was", "were", "be", "to", "of", "for",
    "from", "in", "on", "at", "with", "my", "me", "the",
    "a", "an", "and", "or", "but", "please", "tell", "give",
    "remove", "treat", "treatment", "manage", "management",
    "control", "controls", "prevent", "prevention", "farm",
    "farmer", "farming", "field", "fields", "area", "plot",
    "garden", "north", "south", "east", "west", "india",
    "indian", "near", "nearby", "currently", "currently",
    "best", "way", "ways", "use", "using", "help", "deal",
    "dealing", "problem", "problems", "issue", "issues",
}


def normalize_for_match(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_core_query_terms(query: str) -> List[str]:
    """
    Extract content-bearing words for deterministic domain retrieval.
    This deliberately removes geography and generic farming verbs so a
    query such as 'remove potato scab from my farm in north India'
    becomes 'potato scab'.
    """
    tokens = re.findall(r"[a-zA-Z]+(?:[-'][a-zA-Z]+)*", query.lower())
    terms = [t for t in tokens if t not in QUERY_STOPWORDS and len(t) >= 3]
    return terms


def extract_core_phrases(query: str) -> List[str]:
    terms = extract_core_query_terms(query)
    phrases: List[str] = []

    # Prefer 3- and 2-word phrases; for the example query this produces
    # 'potato scab', which is exactly the repertory lookup key.
    for n in (4, 3, 2):
        for i in range(len(terms) - n + 1):
            phrase = " ".join(terms[i:i+n])
            if phrase not in phrases:
                phrases.append(phrase)

    if terms:
        phrases.extend([t for t in terms if t not in phrases])

    return phrases


def source_name(doc: Document) -> str:
    return Path(doc.metadata.get("source", "")).name


def exact_domain_retrieve(
    query: str,
    allowed_sources: Optional[Set[str]] = None,
) -> List[Tuple[Document, float, str]]:
    """Deterministic lexical retrieval for crop/disease/pest entities.

    A multi-word exact phrase is treated as very strong evidence. A single
    core term can also qualify, but only when it is sufficiently distinctive
    in the query. This is intentionally much more permissive than the old
    cross-encoder confidence gate, while still avoiding a lock caused by
    generic words such as "potato" alone.
    """
    load_vectorstore(require_dense=False)

    phrases = extract_core_phrases(query)
    terms = extract_core_query_terms(query)
    if not phrases or not _bm25_documents:
        return []

    normalized_phrases = [(p, normalize_for_match(p)) for p in phrases]
    results: List[Tuple[Document, float, str]] = []

    for doc in _bm25_documents:
        src = source_name(doc)
        if allowed_sources and src not in allowed_sources:
            continue

        text = normalize_for_match(doc.page_content)
        if not text:
            continue

        score = 0.0
        matched = ""

        # Multi-word phrase match: strongest possible lexical evidence.
        for phrase, norm_phrase in normalized_phrases:
            if len(phrase.split()) >= 2 and norm_phrase and norm_phrase in text:
                phrase_score = 1000.0 + len(norm_phrase) * 10.0
                if phrase_score > score:
                    score = phrase_score
                    matched = phrase
                break

        if score == 0.0 and terms:
            present_terms = [
                t for t in terms
                if re.search(rf"\b{re.escape(t)}\b", text)
            ]
            coverage = len(present_terms) / len(terms)

            # Two or more core terms together are meaningful evidence.
            if len(present_terms) >= 2 and coverage >= 0.5:
                score = 500.0 + len(present_terms) * 10.0
                matched = " ".join(present_terms)

            # A single distinctive term is allowed to establish a primary
            # tier, but generic crop words alone are not enough.
            elif len(present_terms) == 1:
                term = present_terms[0]
                distinctive = (
                    len(term) >= 7
                    and term not in {"potato", "tomato", "onion", "pepper", "plant", "plants"}
                )
                if distinctive:
                    score = 250.0 + len(term) * 5.0
                    matched = term

        if score > 0:
            # Authority is applied after evidence detection, not mixed into
            # the semantic relevance score used to choose the primary tier.
            if src == "Agro_Homeopathy_Repertory.pdf":
                score += 100.0
            results.append((doc, score, matched))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


def bm25_retrieve(
    query: str,
    allowed_sources: Optional[Set[str]] = None,
    limit: int = BM25_TOP_K,
) -> List[Document]:
    load_vectorstore(require_dense=False)

    if not _bm25_documents:
        return []

    raw = _bm25.top_n(
        query,
        min(len(_bm25_documents), limit * 5 if allowed_sources else limit),
    )
    docs: List[Document] = []

    for idx, score in raw:
        if score <= 0 or idx >= len(_bm25_documents):
            continue
        doc = _bm25_documents[idx]
        if allowed_sources and source_name(doc) not in allowed_sources:
            continue
        docs.append(doc)
        if len(docs) >= limit:
            break

    return docs

def _doc_key(doc: Document) -> Tuple[str, Any, str]:
    return (
        doc.metadata.get("source", ""),
        doc.metadata.get("page", ""),
        doc.page_content.strip(),
    )

def dense_retrieve(
    query: str,
    allowed_sources: Optional[Set[str]] = None,
) -> List[Document]:
    if not DENSE_FALLBACK_ENABLED:
        return []

    vectorstore = load_vectorstore(require_dense=True)
    if vectorstore is None or _dense_index_stale:
        return []

    if allowed_sources:
        return vectorstore.similarity_search(
            query,
            k=DENSE_FETCH_K,
            filter={"source": {"$in": list(allowed_sources)}},
        )

    return vectorstore.similarity_search(query, k=DENSE_FETCH_K)


def _stable_merge(
    primary: List[Document],
    secondary: List[Document],
    limit: int,
) -> List[Document]:
    seen: Set[Tuple[str, Any, str]] = set()
    merged: List[Document] = []

    for doc in primary + secondary:
        key = _doc_key(doc)
        if key in seen:
            continue
        seen.add(key)
        merged.append(doc)
        if len(merged) >= limit:
            break

    return merged


def retrieve_stage(
    query: str,
    allowed_sources: Optional[Set[str]],
    primary_stage: bool = True,
    allow_cold_reranker: bool = False,
) -> Tuple[List[Document], bool, str, List[Tuple[Document, float, str]]]:
    """Retrieve one authority stage.

    The stage's authority is selected from lexical/domain evidence. The
    cross-encoder, when needed, only ranks documents AFTER that authority
    decision. It never determines whether a tier is authoritative.
    """
    exact = exact_domain_retrieve(query, allowed_sources)

    if exact:
        exact_docs = [doc for doc, _, _ in exact]
        bm_docs = bm25_retrieve(query, allowed_sources, BM25_TOP_K)
        dense_docs = dense_retrieve(query, allowed_sources)
        candidates = _stable_merge(
            exact_docs,
            bm_docs + dense_docs,
            max(TOP_K, RERANKER_CANDIDATES),
        )

        # If we have an exact multi-word domain phrase, preserve the exact
        # matches first and do not pay the cross-encoder startup cost.
        has_exact_phrase = any(len(match.split()) >= 2 for _, _, match in exact)
        if has_exact_phrase:
            docs = _stable_merge(exact_docs, bm_docs + dense_docs, TOP_K)
        else:
            docs = rerank_candidates(query, candidates, TOP_K)

        return docs, True, f"domain:{exact[0][2]}", exact

    bm_docs = bm25_retrieve(query, allowed_sources, BM25_TOP_K)
    dense_docs = dense_retrieve(query, allowed_sources)
    candidates = _stable_merge(
        bm_docs,
        dense_docs,
        max(TOP_K, RERANKER_CANDIDATES),
    )

    if not candidates:
        return [], False, "none", []

    # BM25 alone is enough to establish that this tier has lexical evidence.
    # If desired, the cross-encoder ranks those candidates, but its score is
    # never used as an evidence threshold.
    docs = (
        rerank_candidates(
            query,
            candidates,
            TOP_K,
            allow_cold_load=allow_cold_reranker,
        )
        if len(candidates) > 1
        else candidates
    )
    return docs, True, "bm25", []


def retrieval_is_sufficient(
    evidence_sufficient: bool,
    documents: List[Any],
) -> bool:
    return bool(evidence_sufficient and documents)


# =========================
# Chain
# =========================

def build_chain():
    """
    Returns (retrieve_fn, generation_chain) separately, rather than a
    single fused Runnable, so that callers (chat_fn) can inspect the
    retrieved `context` for the numeric grounding check after
    generation completes.
    """

    llm = ChatGroq(
        api_key=os.getenv("GROQ_API_KEY"),
        model=GROQ_MODEL,
        temperature=TEMPERATURE,
        streaming=True,
        max_tokens=2048,
    )

    # Separate non-streaming use of the same LLM
    # for query rewriting.
    query_rewriter = build_query_rewriter(
        llm
    )

    # Separate non-streaming use of the same LLM for translating the
    # mandatory usage-technique block into the user's language, used
    # only as a fallback if the model itself omits the section.
    usage_translator = build_usage_translator(
        llm
    )

    def retrieve(inputs):

        question = inputs.get("question", "")
        if not isinstance(question, str):
            question = str(question)

        chat_history = inputs.get("chat_history", [])

        # Query rewriting is used only for follow-up turns. First-turn
        # retrieval avoids an extra LLM call and is therefore faster.
        search_query = question.strip()

        if chat_history:
            history_text = history_to_text(
                chat_history,
                max_messages=QUERY_REWRITE_HISTORY_TURNS * 2,
            )
            try:
                rewritten = query_rewriter.invoke(
                    {
                        "history": history_text,
                        "question": question,
                    }
                )
                rewritten = str(rewritten).strip()
                if rewritten:
                    # Keep the original wording as a lexical anchor while
                    # also using the standalone rewritten query.
                    search_query = f"{rewritten} {question}"
            except Exception:
                search_query = question

        # ---------------------------------
        # Select the highest-priority tier containing meaningful evidence.
        # ---------------------------------
        # IMPORTANT: A lower-priority source can never become PRIMARY merely
        # because its raw relevance score is higher. Authority is determined
        # first; ranking happens only inside the selected tier.
        tier_sets = [set(tier) for tier in RETRIEVAL_TIERS]

        primary_docs: List[Document] = []
        primary_tier_index: Optional[int] = None
        primary_reason = "none"

        allow_cold_reranker = bool(chat_history)

        for tier_index, allowed_sources in enumerate(tier_sets):
            stage_docs, stage_sufficient, stage_reason, exact = retrieve_stage(
                search_query,
                allowed_sources,
                primary_stage=True,
                allow_cold_reranker=allow_cold_reranker,
            )

            if stage_sufficient and stage_docs:
                primary_docs = stage_docs
                primary_tier_index = tier_index
                primary_reason = stage_reason
                break

        # ---------------------------------
        # Retrieve supplementary evidence.
        # ---------------------------------
        # Once a primary tier is selected, lower-priority tiers may add
        # context, but they can never replace, outrank, or override the
        # primary evidence. This is the key authority rule.
        supplementary_docs: List[Document] = []

        if primary_tier_index is not None:
            for tier_index in range(primary_tier_index + 1, len(tier_sets)):
                allowed_sources = tier_sets[tier_index]
                stage_docs, stage_sufficient, stage_reason, _ = retrieve_stage(
                    search_query,
                    allowed_sources,
                    primary_stage=False,
                    allow_cold_reranker=allow_cold_reranker,
                )

                if stage_sufficient and stage_docs:
                    # Only take a small number of supplementary chunks.
                    chosen = stage_docs[:SUPPLEMENTARY_TOP_K_PER_TIER]
                    supplementary_docs.extend(chosen)

        # ---------------------------------
        # If no tier produced evidence, optionally perform unrestricted
        # dense fallback. This remains disabled by default for fast startup.
        # ---------------------------------
        if primary_tier_index is None and DENSE_FALLBACK_ENABLED:
            unrestricted = dense_retrieve(search_query, None)
            if unrestricted:
                primary_docs = rerank_candidates(
                    search_query,
                    unrestricted,
                    TOP_K,
                    allow_cold_load=allow_cold_reranker,
                )
                primary_tier_index = len(RETRIEVAL_TIERS)
                primary_reason = "dense-fallback"

        evidence_sufficient = bool(primary_docs)

        # Primary evidence is always first. Supplementary evidence is always
        # after it, regardless of raw relevance score.
        docs = _stable_merge(
            primary_docs,
            supplementary_docs,
            TOP_K + len(supplementary_docs),
        )

        print(
            f"[retrieval] query={search_query!r} "
            f"primary_tier={None if primary_tier_index is None else primary_tier_index + 1} "
            f"reason={primary_reason!r} "
            f"primary_docs={len(primary_docs)} "
            f"supplementary_docs={len(supplementary_docs)} "
            f"evidence_sufficient={evidence_sufficient}"
        )

        if retrieval_is_sufficient(evidence_sufficient, docs):
            primary_context = format_docs_for_context(primary_docs)
            if supplementary_docs:
                supplementary_context = format_docs_for_context(supplementary_docs)
                context = (
                    "NOTES (most directly relevant to this question):\n"
                    f"{primary_context}\n\n"
                    "NOTES (general background, use only to fill gaps — never let this "
                    "override or contradict the notes above):\n"
                    f"{supplementary_context}"
                )
            else:
                context = f"NOTES:\n{primary_context}"
        else:
            context = "NO SUFFICIENT RETRIEVED EVIDENCE WAS FOUND FOR THIS QUESTION."

        # Clarifying questions are allowed only on the first turn.
        is_first_turn = len(chat_history) == 0

        if is_first_turn:
            clarifying_policy_note = (
                "[Turn note: This is the FIRST message in this "
                "conversation. You may ask up to 3 clarifying questions "
                "if needed, per the ASK CLARIFYING QUESTIONS FIRST policy.]"
            )
        else:
            clarifying_policy_note = (
                "[Turn note: This is NOT the first message in this "
                "conversation. Do NOT ask clarifying questions in this "
                "reply, even if details are still missing or ambiguous. "
                "Use the best available information, note any assumptions "
                "explicitly, and proceed directly to Analysis/Treatment "
                "per the OUTPUT FORMAT.]"
            )

        return {
            "question": question,
            "search_query": search_query,
            "chat_history": chat_history,
            "context": context,
            "evidence_sufficient": evidence_sufficient,
            "clarifying_policy_note": clarifying_policy_note,
        }

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                SYSTEM_PROMPT,
            ),
            MessagesPlaceholder(
                "chat_history"
            ),
            (
                "human",
                "CONTEXT:\n{context}\n\n"
                "QUESTION:\n{question}\n\n"
                "{clarifying_policy_note}",
            ),
        ]
    )

    generation_chain = (
        prompt
        | llm
        | StrOutputParser()
    )

    return retrieve, generation_chain, usage_translator


_retrieve_fn, _generation_chain, _usage_translator = build_chain()


# =========================
# Chat function
# =========================

# Matches the mandatory internal mode marker on its own first line,
# e.g. "[MODE:ANSWER]" or "[MODE:CLARIFY]". Case-insensitive as a
# safety margin against minor formatting drift from the LLM.
MODE_MARKER_PATTERN = re.compile(
    r"^\s*\[MODE:(CLARIFY|ANSWER)\]\s*$",
    re.IGNORECASE,
)

# How many characters to buffer while waiting for the instructed
# "marker line + blank line" pattern before falling back to a looser
# match. Keeps a model that deviates from the exact format from
# stalling the stream indefinitely, while still comfortably covering
# the ~15-character marker itself under normal conditions.
MODE_HEADER_MAX_BUFFER = 200


def _resolve_mode_header(
    raw_buffer: str,
    force: bool = False,
) -> Optional[Tuple[str, str]]:
    """
    Attempts to split the mandatory "[MODE:...]" marker line off the
    start of a streamed response. Returns (mode, remaining_display_text)
    once there's enough of the stream to decide, or None to keep
    accumulating.

    `force=True` skips the "wait for more chunks" behavior and resolves
    immediately against whatever text is available — used once the
    stream has actually ended, so there is nothing left to wait for.
    """
    # Preferred case: marker line followed by a full blank line, as
    # instructed in the system prompt.
    parts = re.split(
        r"\n\s*\n",
        raw_buffer,
        maxsplit=1,
    )

    if len(parts) == 2:
        first_line, rest = parts
        match = MODE_MARKER_PATTERN.match(first_line.strip())

        if match:
            return match.group(1).upper(), rest

        return "ANSWER", raw_buffer

    # No blank line seen yet. If the model deviated from the instructed
    # format (e.g. single newline only) or we've buffered enough that
    # waiting further would visibly hurt streaming responsiveness,
    # resolve anyway rather than stalling.
    if not force and len(raw_buffer) < MODE_HEADER_MAX_BUFFER:
        return None  # keep accumulating

    if "\n" in raw_buffer:
        first_line, rest = raw_buffer.split(
            "\n",
            1,
        )

        match = MODE_MARKER_PATTERN.match(first_line.strip())

        if match:
            return match.group(1).upper(), rest.lstrip("\n")

    # No recognizable marker at all within the buffer budget — fail
    # safe by showing everything collected so far as ANSWER mode.
    return "ANSWER", raw_buffer


def chat_fn(
    message,
    history,
):

    message = extract_text(
        message
    )

    lc_history = to_lc_messages(
        history, max_turns=2
    )

    retrieval_result = _retrieve_fn(
        {
            "question": message,
            "chat_history": lc_history,
        }
    )

    context = retrieval_result["context"]

    raw_buffer = ""
    display_buffer = ""
    mode = None
    header_resolved = False

    # --- START OF UPDATED TRY...EXCEPT BLOCK ---
    try:
        for chunk in _generation_chain.stream(
            retrieval_result
        ):

            raw_buffer += chunk

            if not header_resolved:

                resolved = _resolve_mode_header(
                    raw_buffer
                )

                if resolved is None:
                    continue  # not enough of the stream yet to decide

                mode, display_buffer = resolved
                header_resolved = True

                if display_buffer:
                    yield display_buffer

                continue

            display_buffer += chunk

            yield display_buffer

    except Exception as e:
        error_msg = str(e).lower()
        # Check if the error is related to the 413 Token Limit or Rate Limit
        if "413" in error_msg or "rate limit" in error_msg or "tokens" in error_msg:
            warning_text = (
                "\n\n⚠️ **Conversation Memory Full:** The chat history is too long for the current memory limit. "
                "Please click the **🗑️ Clear Chat** button below to start a new consultation!"
            )
            yield display_buffer + warning_text
            return # Exit the function gracefully
        else:
            # Handle any other unexpected API errors gracefully
            yield display_buffer + f"\n\n⚠️ **System Error:** Could not complete the request. ({str(e)})"
            return
    # --- END OF UPDATED TRY...EXCEPT BLOCK ---

    if not header_resolved:
        # Stream ended before the header could be resolved during
        # streaming (e.g. a very short response). Force a final
        # resolution against whatever we have — nothing more is coming.
        mode, display_buffer = _resolve_mode_header(
            raw_buffer,
            force=True,
        )

    if mode == "CLARIFY":
        # Clarifying-questions-only responses never get the usage
        # technique block or the numeric grounding check appended —
        # no treatment was actually prescribed in this response.
        final_answer = display_buffer

    else:
        final_answer = ensure_usage_technique(
            display_buffer,
            message,
            _usage_translator,
        )

        final_answer = apply_numeric_grounding_check(
            final_answer,
            context,
        )

    yield final_answer


# =========================
# Custom Chat Handlers
# =========================

def handle_user_message(
    user_message,
    history,
):

    if not user_message:
        return "", history

    history.append(
        {
            "role": "user",
            "content": user_message,
        }
    )

    return "", history


def handle_bot_response(
    history,
):

    if (
        not history
        or history[-1].get("role")
        != "user"
    ):
        yield history
        return

    user_msg = extract_text(
        history[-1].get(
            "content",
            "",
        )
    )

    prev_history = history[:-1]

    history.append(
        {
            "role": "assistant",
            "content": "",
        }
    )

    for partial_text in chat_fn(
        user_msg,
        prev_history,
    ):

        history[-1]["content"] = (
            partial_text
        )

        yield history


def clear_chat():
    return [], ""


# =========================
# UI & Mobile Optimization CSS
# =========================

mobile_css = """
/* 1. Hide the default Gradio logo footer everywhere */
footer {
    visibility: hidden !important;
    display: none !important;
}

/* 2. Only remove padding and margins on mobile screens */
@media screen and (max-width: 768px) {

    .gradio-container {
        padding: 0px !important;
        margin: 0px !important;
        max-width: 100% !important;
    }
}
"""


# =========================
# Gradio UI
# =========================

with gr.Blocks(
    title=APP_TITLE,
    css=mobile_css,
) as demo:

    gr.Markdown(
        f"# {APP_TITLE}"
    )

    gr.Markdown(
        "**Free Organic & Natural Farming Consultation**"
    )

    custom_chatbot = gr.Chatbot(
        height=450
    )

    # Placed outside the row so it spans the full width
    msg_box = gr.Textbox(
        label="👇 Ask your question here",
        placeholder=(
            "Please share crop, symptoms, "
            "and location/weather details..."
        ),
        lines=3,
        show_label=True,
    )

    # New row just for the buttons directly below the textbox
    with gr.Row():
        submit_btn = gr.Button(
            "Send",
            variant="primary",
        )

        clear_btn = gr.Button(
            "🗑️ Clear Chat",
            variant="stop",
        )

    user_event = msg_box.submit(
        handle_user_message,
        inputs=[
            msg_box,
            custom_chatbot,
        ],
        outputs=[
            msg_box,
            custom_chatbot,
        ],
        queue=False,
    )

    submit_event = submit_btn.click(
        handle_user_message,
        inputs=[
            msg_box,
            custom_chatbot,
        ],
        outputs=[
            msg_box,
            custom_chatbot,
        ],
        queue=False,
    )

    user_event.then(
        handle_bot_response,
        inputs=[
            custom_chatbot
        ],
        outputs=[
            custom_chatbot
        ],
    )

    submit_event.then(
        handle_bot_response,
        inputs=[
            custom_chatbot
        ],
        outputs=[
            custom_chatbot
        ],
    )

    clear_btn.click(
        clear_chat,
        inputs=[],
        outputs=[
            custom_chatbot,
            msg_box,
        ],
        queue=False,
    )

    gr.Markdown(
        """
<hr>
<div style="text-align:center; font-size:0.85rem; opacity:0.85;">
<b>Privacy:</b> We do not collect, log, or store any user data.<br>
<b>Developed by:</b> Dr.V.Gurucharan & V.Agam <br>
<b>Free for public & educational use</b>
</div>
"""
    )


# =========================
# Custom Professional Green Theme
# =========================

custom_theme = gr.themes.Soft(
    primary_hue="green"
).set(
    body_background_fill="#eef8f0",
    body_background_fill_dark="#1a2b1e",
    block_background_fill="#ffffff",
    block_background_fill_dark="#233626",
    block_border_width="1px",
    block_border_color="#d1e6d1",
)


# =========================--
# Launch
# =========================--

demo.launch(
    theme=custom_theme
)