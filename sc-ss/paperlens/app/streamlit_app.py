import tempfile
from pathlib import Path
from urllib.request import urlretrieve

import streamlit as st

from src.answer_writer import answer_from_evidence
from src.pdf_reader import read_many_pdfs
from src.reranker import load_reranker, rerank_chunks
from src.search_index import build_search_index, embed_texts, load_embedding_model, search_chunks
from src.text_chunks import make_text_chunks
from src.hybrid_search import build_bm25_index, hybrid_search_chunks, rrf_hybrid_search_chunks


PAPERS = [
    {
        "title": "Attention Is All You Need",
        "file": "attention_is_all_you_need.pdf",
        "url": "https://arxiv.org/pdf/1706.03762",
    },
    {
        "title": "BERT",
        "file": "bert.pdf",
        "url": "https://arxiv.org/pdf/1810.04805",
    },
    {
        "title": "Retrieval-Augmented Generation",
        "file": "retrieval_augmented_generation.pdf",
        "url": "https://arxiv.org/pdf/2005.11401",
    },
    {
        "title": "LoRA",
        "file": "lora.pdf",
        "url": "https://arxiv.org/pdf/2106.09685",
    },
    {
        "title": "Chain-of-Thought Prompting",
        "file": "chain_of_thought_prompting.pdf",
        "url": "https://arxiv.org/pdf/2201.11903",
    },
]


SAMPLE_QUESTIONS = [
    "What is self-attention and why is it useful?",
    "What is masked language modeling in BERT?",
    "How does retrieval augmented generation use external knowledge?",
    "How does LoRA reduce the number of trainable parameters?",
    "Why does chain-of-thought prompting improve reasoning?",
]


def ensure_sample_papers() -> None:
    """Download sample papers if they are not already available."""
    paper_dir = Path("data/papers")
    paper_dir.mkdir(parents=True, exist_ok=True)

    for paper in PAPERS:
        path = paper_dir / paper["file"]

        if path.exists():
            continue

        urlretrieve(paper["url"], path)

def save_uploaded_papers(uploaded_files) -> list[dict]:
    """Save uploaded PDFs temporarily and return paper inputs."""
    paper_inputs = []

    temp_dir = Path(tempfile.mkdtemp())

    for uploaded_file in uploaded_files:
        safe_name = uploaded_file.name.replace(" ", "_")
        path = temp_dir / safe_name

        path.write_bytes(uploaded_file.getbuffer())

        title = Path(uploaded_file.name).stem.replace("_", " ").replace("-", " ").title()

        paper_inputs.append(
            {
                "path": str(path),
                "title": title,
            }
        )

    return paper_inputs

@st.cache_resource(show_spinner="Preparing the research index...")
@st.cache_resource(show_spinner="Preparing the research index...")
def build_sample_index():
    ensure_sample_papers()

    paper_inputs = []

    for paper in PAPERS:
        path = Path("data/papers") / paper["file"]

        if path.exists():
            paper_inputs.append(
                {
                    "path": str(path),
                    "title": paper["title"],
                }
            )

    return build_index_from_papers(paper_inputs)


def build_index_from_papers(paper_inputs: list[dict]):
    """Build a searchable paper index from PDF inputs."""
    if not paper_inputs:
        return None

    pages = read_many_pdfs(paper_inputs)
    low_text_pages = [
        page for page in pages
        if len(page["text"].strip()) < 100
    ]

    quality_warning = len(low_text_pages) > max(3, len(pages) * 0.25)
    
    chunks = make_text_chunks(pages=pages, chunk_size=220, overlap=40)

    embedding_model = load_embedding_model()
    embeddings = embed_texts([chunk["text"] for chunk in chunks], model=embedding_model)
    index = build_search_index(embeddings)

    bm25_index = build_bm25_index(chunks)
    reranker = load_reranker()

    return {
        "chunks": chunks,
        "embedding_model": embedding_model,
        "index": index,
        "bm25_index": bm25_index,
        "reranker": reranker,
        "paper_count": len(paper_inputs),
        "chunk_count": len(chunks),
        "page_count": len(pages),
        "quality_warning": quality_warning,
    }


st.set_page_config(
    page_title="PaperLens",
    page_icon="📄",
    layout="wide",
)

st.title("PaperLens")
st.caption("Ask research papers. Get cited answers.")

with st.sidebar:
    st.header("Paper Collection")
    for paper in PAPERS:
        st.write(f"- {paper['title']}")

    st.divider()
    st.write("Retrieval: FAISS + Sentence Transformers")
    st.write("Reranking: Cross-Encoder")
    st.write("Benchmark: 15 questions across 5 papers")

with st.sidebar:
    st.divider()
    paper_mode = st.radio(
        "Paper source",
        ["Sample papers", "Upload PDFs"],
    )

uploaded_files = []

if paper_mode == "Upload PDFs":
    uploaded_files = st.file_uploader(
        "Upload one or more research papers",
        type=["pdf"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        with st.spinner("Reading uploaded papers and building search index..."):
            uploaded_inputs = save_uploaded_papers(uploaded_files)
            state = build_index_from_papers(uploaded_inputs)
    else:
        state = None
else:
    state = build_sample_index()

available_papers = sorted({chunk["paper_title"] for chunk in state["chunks"]})

selected_papers = st.multiselect(
    "Search within papers",
    available_papers,
    default=available_papers,
)

searchable_chunks = [
    chunk for chunk in state["chunks"]
    if chunk["paper_title"] in selected_papers
]

if state is None:
    if paper_mode == "Upload PDFs":
        st.warning("Upload at least one PDF to build a research index.")
    else:
        st.warning("PaperLens could not prepare the sample paper collection.")
    st.stop()
ask_tab, benchmark_tab, about_tab = st.tabs(["Ask", "Benchmark", "About"])

with ask_tab:
    st.info(
        f"Indexed {state['paper_count']} papers into {state['chunk_count']} searchable chunks."
    )
    st.caption(f"Read {state['page_count']} pages.")

    if state.get("quality_warning"):
        st.warning(
            "Some pages had very little extractable text. If this is a scanned PDF, "
            "PaperLens may need OCR support for better results."
        )
    selected_question = st.selectbox(
        "Try a sample question",
        SAMPLE_QUESTIONS,
    )

    custom_question = st.text_input(
        "Or ask your own question",
        placeholder="Ask about one of the papers...",
    )

    query = custom_question.strip() or selected_question

    search_mode = st.radio(
    "Search mode",
    ["Hybrid search", "Semantic search"],
    horizontal=True,
    )
    if "question_history" not in st.session_state:
        st.session_state.question_history = []
    
    if st.session_state.question_history:
        st.caption("Recent questions")
        for old_query in st.session_state.question_history:
            st.write(f"- {old_query}")
    
    if st.button("Search Papers", type="primary"):
        if search_mode == "Hybrid search":
            retrieved = rrf_hybrid_search_chunks(
                query=query,
                chunks=searchable_chunks,
                semantic_model=state["embedding_model"],
                semantic_index=state["index"],
                bm25_index=state["bm25_index"],
                top_k=10,
            )
        else:
            retrieved = search_chunks(
                query=query,
                chunks=searchable_chunks,
                model=state["embedding_model"],
                index=state["index"],
                top_k=10,
            )

        reranked = rerank_chunks(
            query=query,
            chunks=retrieved,
            reranker=state["reranker"],
            top_k=5,
        )

        answer = answer_from_evidence(
            query=query,
            chunks=reranked,
            min_score=1.0,
            max_chunks=3,
        )
        if query not in st.session_state.question_history:
            st.session_state.question_history.insert(0, query)
            st.session_state.question_history = st.session_state.question_history[:5]
        if "rrf_score" in chunk:
            st.write(f"RRF score: {chunk.get('rrf_score', 0):.4f}")
        from src.answer_writer import evidence_strength

        strength = evidence_strength(reranked)

        st.subheader("Answer")

        if strength == "strong":
            st.success("Evidence strength: Strong")
        elif strength == "moderate":
            st.warning("Evidence strength: Moderate")
        else:
            st.error("Evidence strength: Weak")
        
        st.write(answer["answer"])

        st.subheader("Citations")
        if answer["citations"]:
            for citation in answer["citations"]:
                st.write(f"- {citation['citation']}")
        else:
            st.write("No strong citations found.")

        st.subheader("Evidence")
        for rank, chunk in enumerate(reranked, start=1):
            with st.expander(
                f"{rank}. {chunk['paper_title']} · page {chunk['page_number']}"
            ):
                st.write(f"Search score: {chunk.get('search_score', 0):.3f}")

                if "keyword_score" in chunk:
                    st.write(f"Keyword score: {chunk.get('keyword_score', 0):.3f}")

                if "hybrid_score" in chunk:
                    st.write(f"Hybrid score: {chunk.get('hybrid_score', 0):.3f}")

                st.write(f"Rerank score: {chunk.get('rerank_score', 0):.3f}")
                st.write(chunk["text"])

with benchmark_tab:
    st.subheader("Retrieval Benchmark")

    st.metric("Benchmark Questions", "15")
    st.metric("Top-1 Paper Routing", "100%")
    st.metric("Strict Page-Level Citation Hit Rate", "86.7%")

    st.write(
        "PaperLens was evaluated on 15 manually written questions across five AI research papers. "
        "The system routed every question to the correct paper, while exact expected-page matching "
        "was intentionally measured as a stricter citation-quality metric."
    )

with about_tab:
    st.subheader("About PaperLens")

    st.write(
        "PaperLens is a citation-grounded research assistant for technical papers. "
        "It reads PDFs, splits them into page-aware chunks, builds a FAISS search index, "
        "reranks evidence with a cross-encoder, and answers using cited source text."
    )

    st.write("Built with free tools:")
    st.write("- Streamlit")
    st.write("- Hugging Face Spaces free CPU")
    st.write("- Sentence Transformers")
    st.write("- FAISS")
    st.write("- pypdf")