"""
RAG Knowledge Base Demo
-----------------------
A Retrieval-Augmented Generation app for Hugging Face Spaces (free CPU tier).

Stack:
- UI:          Gradio
- Framework:   LangChain
- LLM:         Groq (ChatGroq, llama-3.1-8b-instant)
- Embeddings:  HuggingFaceEmbeddings (all-MiniLM-L6-v2, CPU-friendly)
- Vector DB:   Chroma (in-memory / ephemeral)
- PDF parsing: pypdf (PdfReader)

The Groq API key is read from the environment (GROQ_API_KEY). On Hugging Face
Spaces, set it under Settings -> Variables and secrets -> New secret.
Never hardcode it in this file.

Daily token budget:
- Shared across all users of this Space for the current UTC day.
- Configure with DAILY_TOKEN_LIMIT (default: 50000).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Load variables from a local .env file (if present) so os.getenv can find
# GROQ_API_KEY during local development. On Hugging Face Spaces this is a no-op
# because the key is injected as a real environment variable (repository secret).
load_dotenv()

import gradio as gr
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
LLM_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
LLM_FALLBACK_MODELS = [
    LLM_MODEL,
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
]
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
TOP_K = 3
DEFAULT_LANG = "en"

# Shared daily budget for ALL users of this Space (UTC day).
# Override on HF Spaces via Settings -> Variables: DAILY_TOKEN_LIMIT
DAILY_TOKEN_LIMIT = int(os.getenv("DAILY_TOKEN_LIMIT", "50000"))
TOKEN_USAGE_FILE = Path(os.getenv("TOKEN_USAGE_FILE", ".token_usage.json"))

# Load the embedding model once at startup (it is stateless and reusable).
# This runs on CPU and is small enough for the free tier.
EMBEDDINGS = HuggingFaceEmbeddings(
    model_name=EMBEDDING_MODEL,
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True},
)

TEXTS = {
    "en": {
        "page_title": "RAG Knowledge Base",
        "header_title": "# Chat With Your PDF (RAG Demo)",
        "header_body": (
            "Upload a PDF document, wait for it to be indexed, then ask questions "
            "about its contents. Answers are generated **only** from the uploaded "
            "document using retrieval-augmented generation.\n\n"
            "**How to use:**\n"
            "1. Upload a PDF in the panel on the left.\n"
            "2. Wait for the status to confirm indexing is complete.\n"
            "3. Ask your questions in the chat on the right.\n\n"
            "> You must upload and index a document before chatting."
        ),
        "language_label": "Language",
        "upload_pdf": "Upload PDF",
        "status": "Status",
        "status_default": "No document indexed yet.",
        "status_indexed": (
            "Indexed '{filename}' ({pages} page(s), {chunks} chunk(s)). "
            "You can start asking questions now."
        ),
        "usage_label": "Daily token budget (all users)",
        "usage_ok": "Used {used:,} / {limit:,} tokens today. Remaining: {remaining:,}.",
        "usage_hit": (
            "Today's global token limit has been reached "
            "({used:,} / {limit:,}). Please try again tomorrow."
        ),
        "chat_label": "Answers",
        "chat_placeholder": "Ask a question about your uploaded document...",
        "send": "Send",
        "clear": "Clear",
        "err_upload_first": "Please upload a PDF file first.",
        "err_read_pdf": "Failed to read the PDF: {error}",
        "err_no_text": "No text could be extracted from that PDF.",
        "err_no_chunks": "The document produced no chunks to index.",
        "err_missing_key": (
            "Server misconfiguration: GROQ_API_KEY is not set. "
            "Add it under the Space's Settings -> Variables and secrets."
        ),
        "err_no_document": "Please upload and index a PDF document before asking questions.",
        "err_empty_question": "Please enter a question.",
        "err_daily_limit": (
            "Today's global token limit has already been reached "
            "({used:,} / {limit:,}). Please come back tomorrow."
        ),
        "err_init_model": "Error while initializing Groq model: {error}",
        "err_generate": "Error while generating the answer: {error}",
        "rag_system": (
            "You are a helpful assistant answering questions about an uploaded "
            "document. Answer the user's question using ONLY the context "
            "provided below. If the answer is not contained in the context, "
            "say you don't know based on the document. Do not make up "
            "information. Respond in English.\n\n"
            "Context:\n{context}"
        ),
        "edu_section": """
---

## What is this technology?

This demo uses **RAG** — short for **Retrieval-Augmented Generation**.

Think of a normal chatbot (like ChatGPT) as a very well-read person who answers from memory. That is powerful, but memory can be outdated, incomplete, or wrong about *your* private documents. RAG solves that by giving the AI a temporary “open-book exam”:

1. **You upload a document** (here, a PDF).
2. The system **breaks the document into small readable pieces** (chunks), similar to cutting a long report into short paragraphs.
3. Each piece is converted into a **numerical fingerprint** called an *embedding*. Similar meanings get similar fingerprints.
4. Those fingerprints are stored in a **search index** (a vector database).
5. When you ask a question, the system **searches for the most relevant pieces** first.
6. Only then does it ask the language model to **write an answer using those pieces as evidence**.

So the AI is not “guessing from the internet.” It is answering from **your uploaded content**, with retrieval as the grounding step.

### Why this matters (even if you are new to AI)

| Without RAG | With RAG |
|---|---|
| The model answers from general training knowledge | The model answers from *your* documents |
| Hard to control what source it used | You can inspect the retrieved passages |
| Higher risk of confident but wrong answers | Lower risk, because answers are tied to retrieved text |
| Private company files are not available to the model | Private knowledge can be used safely inside your system |

In short: **RAG = search first, then generate.**

### What happens inside this demo

- **PDF parsing**: extract text from your file
- **Chunking**: split text into overlapping segments so meaning is not cut awkwardly
- **Embeddings**: turn text into searchable vectors
- **Vector search (Chroma)**: find the top 3 most relevant chunks
- **LLM answer (Groq)**: generate a grounded response from those chunks only

That pipeline is the same pattern used in many production knowledge assistants.

## How businesses can use this technology

RAG is especially valuable when a company has lots of documents and people keep asking the same questions.

### Common business use cases

1. **Internal knowledge assistant**  
   Employees ask questions about HR policies, SOPs, product manuals, or onboarding guides — and get answers grounded in the official files.

2. **Customer support copilots**  
   Support agents (or a self-service chatbot) answer from product docs, FAQs, warranty terms, and troubleshooting guides — with fewer invented answers.

3. **Sales enablement**  
   Sales teams quickly find pricing rules, feature comparisons, case studies, and proposal templates from a controlled document set.

4. **Compliance and risk review**  
   Legal/compliance teams query contracts, regulations, and internal policies to locate relevant clauses faster (with human review still required).

5. **Operations and manufacturing**  
   Technicians ask about machine manuals, maintenance checklists, and safety procedures on the floor.

6. **Education and training**  
   Companies turn training PDFs into an interactive tutor that answers staff questions using the course materials.

### Business value in plain language

- **Faster answers**: people spend less time hunting through folders and PDFs
- **More consistent answers**: everyone references the same source of truth
- **Better onboarding**: new hires ramp up by asking questions instead of reading everything
- **Lower support load**: common questions can be handled by a grounded assistant
- **Safer AI adoption**: answers are constrained to approved documents, not open-ended invention

### A practical way to start

Most companies do not need a huge AI project on day one. A strong first step is:

1. Pick **one high-value document set** (for example: customer FAQ + product manual)
2. Build a small RAG assistant like this demo
3. Measure whether answer quality and response time improve
4. Expand to more departments only after the first use case works

If you want to explore how this could fit your organization — internal knowledge, customer support, or document Q&A — this demo is a concrete starting point you can show stakeholders.
""",
    },
    "zh": {
        "page_title": "RAG 知識庫",
        "header_title": "# 與您的 PDF 對話（RAG 示範）",
        "header_body": (
            "上傳 PDF 文件並等待建立索引後，即可針對文件內容提問。"
            "回答**僅**會根據您上傳的文件，透過檢索增強生成（RAG）產生。\n\n"
            "**使用方式：**\n"
            "1. 在左側面板上傳 PDF。\n"
            "2. 等待狀態顯示索引完成。\n"
            "3. 在右側聊天視窗開始提問。\n\n"
            "> 請先上傳並建立文件索引，才能開始對話。"
        ),
        "language_label": "語言",
        "upload_pdf": "上傳 PDF",
        "status": "狀態",
        "status_default": "尚未建立任何文件索引。",
        "status_indexed": (
            "已建立索引「{filename}」（{pages} 頁，{chunks} 個區塊）。"
            "現在可以開始提問了。"
        ),
        "usage_label": "每日 Token 配額（全體使用者共用）",
        "usage_ok": "今日已使用 {used:,} / {limit:,} tokens。剩餘：{remaining:,}。",
        "usage_hit": (
            "今日全域 Token 上限已達標（{used:,} / {limit:,}）。"
            "請明天再試。"
        ),
        "chat_label": "回答",
        "chat_placeholder": "請輸入關於您上傳文件的問題...",
        "send": "送出",
        "clear": "清除",
        "err_upload_first": "請先上傳 PDF 文件。",
        "err_read_pdf": "無法讀取 PDF：{error}",
        "err_no_text": "無法從該 PDF 擷取任何文字。",
        "err_no_chunks": "文件未產生可用於索引的區塊。",
        "err_missing_key": (
            "伺服器設定錯誤：未設定 GROQ_API_KEY。"
            "請在 Space 的「Settings -> Variables and secrets」中新增。"
        ),
        "err_no_document": "請先上傳並建立 PDF 文件索引，再開始提問。",
        "err_empty_question": "請輸入問題。",
        "err_daily_limit": (
            "今日全域 Token 上限已達標（{used:,} / {limit:,}）。"
            "請明天再回來使用。"
        ),
        "err_init_model": "初始化 Groq 模型時發生錯誤：{error}",
        "err_generate": "產生回答時發生錯誤：{error}",
        "rag_system": (
            "你是一位有幫助的文件問答助手。請僅根據以下提供的內容回答使用者的問題。"
            "如果內容中沒有答案，請說明根據文件無法得知。請勿捏造資訊。"
            "請使用繁體中文回答。\n\n"
            "內容：\n{context}"
        ),
        "edu_section": """
---

## 這是什麼技術？

這個示範使用的是 **RAG**，全名是 **Retrieval-Augmented Generation（檢索增強生成）**。

你可以這樣理解：一般聊天機器人（例如 ChatGPT）像是一位「靠記憶回答」的博學人士，能力很強，但記憶可能過時、不完整，或根本不知道你們公司的內部文件。RAG 的做法比較像給 AI 一場「開書考試」：

1. **你上傳文件**（這裡是 PDF）。
2. 系統把文件**切成較小的可讀片段**（chunks），類似把長報告拆成一段段短段落。
3. 每個片段會被轉成一組**數字指紋**，稱為 *embedding（嵌入向量）*。意思相近的文字，指紋也會比較接近。
4. 這些指紋會存進**搜尋索引**（向量資料庫）。
5. 當你提問時，系統會先**找出最相關的片段**。
6. 最後才請大型語言模型**根據這些片段撰寫答案**。

所以 AI 不是在「憑空猜網路上的知識」，而是先檢索、再根據**你上傳的內容**回答。

### 為什麼這很重要（即使你沒有 AI 背景）

| 沒有 RAG | 有 RAG |
|---|---|
| 模型主要靠通用訓練知識回答 | 模型根據「你的文件」回答 |
| 很難確認它參考了什麼來源 | 可以檢查被檢索到的段落 |
| 較容易出現「很有自信但答錯」的情況 | 風險較低，因為答案綁定檢索內容 |
| 公司私有文件通常無法直接被模型使用 | 可在自家系統中安全使用私有知識 |

簡單說：**RAG = 先搜尋，再生成。**

### 這個示範內部實際做了什麼

- **PDF 解析**：從檔案擷取文字
- **切塊（Chunking）**：把文字切成有重疊的片段，避免語意被硬切斷
- **嵌入向量（Embeddings）**：把文字轉成可搜尋的向量
- **向量搜尋（Chroma）**：找出最相關的前 3 個片段
- **LLM 回答（Groq）**：只根據這些片段產生有根據的回答

這條流程，正是許多企業知識助理在正式環境中使用的核心模式。

## 企業可以怎麼應用這項技術？

當公司有大量文件、而員工或客戶反覆問同樣問題時，RAG 特別有價值。

### 常見商業應用場景

1. **內部知識助理**  
   員工可詢問人資政策、SOP、產品手冊、新人訓練資料，並得到以正式文件為依據的回答。

2. **客服輔助 / 自助客服**  
   客服人員或聊天機器人可依產品說明、FAQ、保固條款、故障排除文件回答，減少「亂編答案」。

3. **業務賦能（Sales Enablement）**  
   業務團隊可快速查找價格規則、功能比較、成功案例與提案範本。

4. **法遵與風險檢視**  
   法務／法遵團隊可快速定位合約條款、法規與內部政策相關段落（仍需人工覆核）。

5. **營運與製造現場**  
   技術人員可查詢機台手冊、保養清單與安全程序。

6. **教育訓練**  
   企業可把訓練 PDF 變成互動式助教，讓同仁用提問方式學習教材內容。

### 用白話看商業價值

- **回答更快**：少花時間在資料夾與 PDF 裡翻找
- **答案更一致**：大家參考同一套正式來源
- **新人上手更快**：用提問取代「一次讀完整本手冊」
- **降低客服負擔**：常見問題可由有根據的助理處理
- **更安全地導入 AI**：答案被限制在核准文件內，而不是自由發揮

### 企業怎麼開始最務實

多數公司不需要第一天就做超大專案。很好的第一步是：

1. 先選**一套高價值文件**（例如：客戶 FAQ + 產品手冊）
2. 做出像這個示範一樣的小型 RAG 助理
3. 衡量回答品質與回應時間是否改善
4. 第一個場景跑通後，再擴展到其他部門

如果您想評估這項技術是否適合貴公司——無論是內部知識庫、客服，或文件問答——這個示範就是一個可以直接展示給利害關係人的起點。
""",
    },
}


# ---------------------------------------------------------------------------
# Daily global token budget (shared by all users)
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Rough token estimate that works for English and Chinese without extra deps.

    English is closer to ~4 chars/token; CJK is closer to ~1-2 chars/token.
    We use a conservative blend so we do not under-count spend.
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = max(len(text) - cjk, 0)
    return max(1, cjk + (other + 3) // 4)


class DailyTokenBudget:
    """Process-wide daily token counter persisted to a local JSON file."""

    def __init__(self, limit: int, path: Path):
        self.limit = max(1, limit)
        self.path = path
        self._lock = threading.Lock()
        self._date = self._today()
        self._used = 0
        self._load()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load(self) -> None:
        if not self.path.exists():
            self._date = self._today()
            self._used = 0
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._date = data.get("date", self._today())
            self._used = int(data.get("used", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self._date = self._today()
            self._used = 0
        self._rollover_if_needed()

    def _save(self) -> None:
        payload = {"date": self._date, "used": self._used, "limit": self.limit}
        self.path.write_text(json.dumps(payload), encoding="utf-8")

    def _rollover_if_needed(self) -> None:
        today = self._today()
        if self._date != today:
            self._date = today
            self._used = 0
            self._save()

    def snapshot(self) -> dict:
        with self._lock:
            self._rollover_if_needed()
            remaining = max(self.limit - self._used, 0)
            return {
                "date": self._date,
                "used": self._used,
                "limit": self.limit,
                "remaining": remaining,
                "hit": self._used >= self.limit,
            }

    def can_spend(self, estimated: int = 1) -> bool:
        with self._lock:
            self._rollover_if_needed()
            return (self._used + max(estimated, 0)) <= self.limit

    def record(self, tokens: int) -> dict:
        with self._lock:
            self._rollover_if_needed()
            self._used += max(0, int(tokens))
            self._save()
            remaining = max(self.limit - self._used, 0)
            return {
                "date": self._date,
                "used": self._used,
                "limit": self.limit,
                "remaining": remaining,
                "hit": self._used >= self.limit,
            }


TOKEN_BUDGET = DailyTokenBudget(DAILY_TOKEN_LIMIT, TOKEN_USAGE_FILE)


def t(lang: str, key: str, **kwargs) -> str:
    """Return localized UI text."""
    language = lang if lang in TEXTS else DEFAULT_LANG
    text = TEXTS[language][key]
    return text.format(**kwargs) if kwargs else text


def detect_lang(accept_language: str | None) -> str:
    """Map the browser Accept-Language header to an app language.

    Any Chinese locale (zh, zh-CN, zh-TW, zh-HK, zh-Hans, zh-Hant, ...) → zh.
    Everything else → en.
    """
    if not accept_language:
        return DEFAULT_LANG
    primary = accept_language.split(",")[0].split(";")[0].strip().lower().replace("_", "-")
    if primary.startswith("zh"):
        return "zh"
    return "en"


def header_markdown(lang: str) -> str:
    """Build the header block for the selected language."""
    return f"{t(lang, 'header_title')}\n\n{t(lang, 'header_body')}"


def edu_markdown(lang: str) -> str:
    """Build the educational explainer section for the selected language."""
    return t(lang, "edu_section")


def usage_text(lang: str, snap: dict | None = None) -> str:
    """Build the daily budget status line."""
    snap = snap or TOKEN_BUDGET.snapshot()
    key = "usage_hit" if snap["hit"] else "usage_ok"
    return t(
        lang,
        key,
        used=snap["used"],
        limit=snap["limit"],
        remaining=snap["remaining"],
    )


def get_rag_prompt(lang: str) -> ChatPromptTemplate:
    """Build the retrieval prompt for the selected language."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", t(lang, "rag_system")),
            ("human", "{question}"),
        ]
    )


def get_indexed_status(lang: str, indexed_info: dict | None) -> str:
    """Return the status line for the current indexing state."""
    if not indexed_info:
        return t(lang, "status_default")
    return t(
        lang,
        "status_indexed",
        filename=indexed_info["filename"],
        pages=indexed_info["pages"],
        chunks=indexed_info["chunks"],
    )


# ---------------------------------------------------------------------------
# Core RAG logic
# ---------------------------------------------------------------------------


def resolve_pdf_path(pdf_file) -> str | None:
    """Normalize Gradio File payloads across versions into a local path."""
    if pdf_file is None:
        return None
    if isinstance(pdf_file, str):
        return pdf_file
    if isinstance(pdf_file, dict):
        return pdf_file.get("path") or pdf_file.get("name")
    return getattr(pdf_file, "name", None)


def build_vectorstore(pdf_file, lang: str):
    """Parse the uploaded PDF, chunk it, embed it, and return a Chroma store.

    Returns a tuple of (vectorstore, status_message, indexed_info). On failure
    the vectorstore is None and indexed_info is None.
    """
    pdf_path = resolve_pdf_path(pdf_file)
    if not pdf_path:
        return None, t(lang, "err_upload_first"), None

    try:
        reader = PdfReader(pdf_path)
        documents = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                documents.append(
                    Document(
                        page_content=text,
                        metadata={"source": pdf_path, "page": page_number},
                    )
                )
    except Exception as exc:  # noqa: BLE001 - surface any parsing error to the UI
        return None, t(lang, "err_read_pdf", error=exc), None

    if not documents:
        return None, t(lang, "err_no_text"), None

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_documents(documents)

    if not chunks:
        return None, t(lang, "err_no_chunks"), None

    # Ephemeral, in-memory Chroma collection (no persistence directory).
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=EMBEDDINGS,
        collection_name="rag_session",
    )

    indexed_info = {
        "filename": os.path.basename(pdf_path),
        "pages": len(documents),
        "chunks": len(chunks),
    }
    status = get_indexed_status(lang, indexed_info)
    return vectorstore, status, indexed_info


def format_context(docs):
    """Join retrieved chunks into a single context string."""
    return "\n\n---\n\n".join(doc.page_content for doc in docs)


def get_groq_llm():
    """Create a ChatGroq client, with graceful fallback for retired models."""
    tried = []
    for model in dict.fromkeys(LLM_FALLBACK_MODELS):
        tried.append(model)
        try:
            return ChatGroq(
                api_key=GROQ_API_KEY,
                model=model,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001 - inspect provider/runtime failures
            message = str(exc).lower()
            if "decommissioned" in message or "model" in message and "not" in message:
                continue
            raise

    raise RuntimeError(
        "No available Groq model could be initialized. "
        f"Tried: {', '.join(tried)}"
    )


def append_turn(history, user_text: str, assistant_text: str):
    """Append one user/assistant turn in Gradio 6 messages format."""
    return history + [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": assistant_text},
    ]


def answer_question(message, history, vectorstore, lang):
    """Retrieve relevant chunks and stream the LLM answer token by token."""
    history = list(history or [])

    if not GROQ_API_KEY:
        yield "", append_turn(history, message, t(lang, "err_missing_key")), usage_text(lang)
        return

    snap = TOKEN_BUDGET.snapshot()
    if snap["hit"]:
        yield (
            "",
            append_turn(
                history,
                message,
                t(
                    lang,
                    "err_daily_limit",
                    used=snap["used"],
                    limit=snap["limit"],
                ),
            ),
            usage_text(lang, snap),
        )
        return

    if vectorstore is None:
        yield "", append_turn(history, message, t(lang, "err_no_document")), usage_text(lang)
        return

    if not message or not message.strip():
        yield "", append_turn(history, message, t(lang, "err_empty_question")), usage_text(lang)
        return

    retriever = vectorstore.as_retriever(search_kwargs={"k": TOP_K})
    relevant_docs = retriever.invoke(message)
    context = format_context(relevant_docs)

    prompt_estimate = estimate_tokens(
        t(lang, "rag_system", context=context) + "\n" + message
    )
    # Reserve a small completion budget so we stop before overshooting.
    if not TOKEN_BUDGET.can_spend(prompt_estimate + 64):
        snap = TOKEN_BUDGET.snapshot()
        yield (
            "",
            append_turn(
                history,
                message,
                t(
                    lang,
                    "err_daily_limit",
                    used=snap["used"],
                    limit=snap["limit"],
                ),
            ),
            usage_text(lang, snap),
        )
        return

    try:
        llm = get_groq_llm()
    except Exception as exc:  # noqa: BLE001 - display model init errors in UI
        yield (
            "",
            append_turn(history, message, t(lang, "err_init_model", error=exc)),
            usage_text(lang),
        )
        return

    chain = get_rag_prompt(lang) | llm | StrOutputParser()

    history = append_turn(history, message, "")
    yield "", history, usage_text(lang)

    partial = ""
    try:
        for token in chain.stream({"context": context, "question": message}):
            partial += token
            history[-1]["content"] = partial
            yield "", history, usage_text(lang)
    except Exception as exc:  # noqa: BLE001 - surface API/network errors to the UI
        history[-1]["content"] = t(lang, "err_generate", error=exc)
        yield "", history, usage_text(lang)
        return

    completion_estimate = estimate_tokens(partial)
    snap = TOKEN_BUDGET.record(prompt_estimate + completion_estimate)
    yield "", history, usage_text(lang, snap)


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------


def on_upload(pdf_file, lang):
    """Handle a new upload: build the store and reset the chat."""
    vectorstore, status, indexed_info = build_vectorstore(pdf_file, lang)
    return vectorstore, indexed_info, status, [], usage_text(lang)


def switch_language(lang, indexed_info):
    """Update all visible UI labels when the language changes."""
    return (
        header_markdown(lang),
        gr.update(label=t(lang, "upload_pdf")),
        gr.update(label=t(lang, "status"), value=get_indexed_status(lang, indexed_info)),
        gr.update(label=t(lang, "usage_label"), value=usage_text(lang)),
        gr.update(label=t(lang, "chat_label")),
        gr.update(
            label=t(lang, "chat_label"),
            placeholder=t(lang, "chat_placeholder"),
        ),
        gr.update(value=t(lang, "send")),
        gr.update(value=t(lang, "clear")),
        gr.update(label=t(lang, "language_label")),
        edu_markdown(lang),
    )


def apply_browser_language(request: gr.Request):
    """On page load, switch the UI to match the visitor's browser language."""
    headers = getattr(request, "headers", None) or {}
    accept = headers.get("Accept-Language") or headers.get("accept-language") or ""
    lang = detect_lang(accept)
    (
        header,
        pdf,
        status,
        usage,
        chat,
        msg_box,
        submit,
        clear,
        _lang_switch,
        edu,
    ) = switch_language(lang, None)
    lang_switch = gr.update(label=t(lang, "language_label"), value=lang)
    return (
        lang,
        header,
        pdf,
        status,
        usage,
        chat,
        msg_box,
        submit,
        clear,
        lang_switch,
        edu,
    )


with gr.Blocks(title=TEXTS[DEFAULT_LANG]["page_title"]) as demo:
    language_state = gr.State(value=DEFAULT_LANG)
    vectorstore_state = gr.State(value=None)
    indexed_info_state = gr.State(value=None)

    with gr.Row(equal_height=True):
        with gr.Column(scale=5):
            header_md = gr.Markdown(header_markdown(DEFAULT_LANG))
        with gr.Column(scale=1, min_width=180):
            language_switch = gr.Radio(
                choices=[("English", "en"), ("繁體中文", "zh")],
                value=DEFAULT_LANG,
                label=TEXTS[DEFAULT_LANG]["language_label"],
                interactive=True,
            )

    with gr.Row():
        with gr.Column(scale=1):
            pdf_input = gr.File(
                label=TEXTS[DEFAULT_LANG]["upload_pdf"],
                file_types=[".pdf"],
                file_count="single",
            )
            status_box = gr.Textbox(
                label=TEXTS[DEFAULT_LANG]["status"],
                value=TEXTS[DEFAULT_LANG]["status_default"],
                interactive=False,
            )
            usage_box = gr.Textbox(
                label=TEXTS[DEFAULT_LANG]["usage_label"],
                value=usage_text(DEFAULT_LANG),
                interactive=False,
            )

        with gr.Column(scale=2):
            chatbot = gr.Chatbot(
                height=480,
                label=TEXTS[DEFAULT_LANG]["chat_label"],
            )
            msg = gr.Textbox(
                label=TEXTS[DEFAULT_LANG]["chat_label"],
                placeholder=TEXTS[DEFAULT_LANG]["chat_placeholder"],
                lines=2,
            )
            with gr.Row():
                submit_btn = gr.Button(TEXTS[DEFAULT_LANG]["send"], variant="primary")
                clear_btn = gr.ClearButton(
                    [msg, chatbot],
                    value=TEXTS[DEFAULT_LANG]["clear"],
                )

    edu_md = gr.Markdown(edu_markdown(DEFAULT_LANG))

    language_outputs = [
        language_state,
        header_md,
        pdf_input,
        status_box,
        usage_box,
        chatbot,
        msg,
        submit_btn,
        clear_btn,
        language_switch,
        edu_md,
    ]

    # Auto-detect language from the browser's Accept-Language header on first load.
    # Manual radio changes still override for the rest of the session.
    demo.load(
        fn=apply_browser_language,
        inputs=None,
        outputs=language_outputs,
    )

    language_switch.change(
        fn=lambda lang, info: (lang, *switch_language(lang, info)),
        inputs=[language_switch, indexed_info_state],
        outputs=language_outputs,
    )

    pdf_input.change(
        fn=on_upload,
        inputs=[pdf_input, language_state],
        outputs=[
            vectorstore_state,
            indexed_info_state,
            status_box,
            chatbot,
            usage_box,
        ],
    )

    submit_btn.click(
        fn=answer_question,
        inputs=[msg, chatbot, vectorstore_state, language_state],
        outputs=[msg, chatbot, usage_box],
    )
    msg.submit(
        fn=answer_question,
        inputs=[msg, chatbot, vectorstore_state, language_state],
        outputs=[msg, chatbot, usage_box],
    )


if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=7860)
