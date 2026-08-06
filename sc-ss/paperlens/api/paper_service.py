from pathlib import Path
from urllib.request import urlretrieve

from src.answer_writer import answer_from_evidence, evidence_strength
from src.hybrid_search import build_bm25_index, rrf_hybrid_search_chunks
from src.pdf_reader import read_many_pdfs
from src.reranker import load_reranker, rerank_chunks
from src.search_index import build_search_index, embed_texts, load_embedding_model, search_chunks
from src.text_chunks import make_text_chunks


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


class PaperLensService:
    def __init__(self):
        self.state = None

    def ensure_sample_papers(self):
        paper_dir = Path("data/papers")
        paper_dir.mkdir(parents=True, exist_ok=True)

        for paper in PAPERS:
            path = paper_dir / paper["file"]

            if not path.exists():
                urlretrieve(paper["url"], path)

    def build_sample_index(self):
        self.ensure_sample_papers()

        paper_inputs = [
            {
                "path": str(Path("data/papers") / paper["file"]),
                "title": paper["title"],
            }
            for paper in PAPERS
        ]

        pages = read_many_pdfs(paper_inputs)
        chunks = make_text_chunks(pages=pages, chunk_size=220, overlap=40)

        embedding_model = load_embedding_model()
        embeddings = embed_texts([chunk["text"] for chunk in chunks], model=embedding_model)
        index = build_search_index(embeddings)
        bm25_index = build_bm25_index(chunks)
        reranker = load_reranker()

        self.state = {
            "chunks": chunks,
            "embedding_model": embedding_model,
            "index": index,
            "bm25_index": bm25_index,
            "reranker": reranker,
            "paper_count": len(paper_inputs),
            "page_count": len(pages),
            "chunk_count": len(chunks),
        }

    def ready(self):
        return self.state is not None

    def papers(self):
        if not self.ready():
            return []

        titles = sorted({chunk["paper_title"] for chunk in self.state["chunks"]})
        return titles

    def stats(self):
        if not self.ready():
            return {
                "ready": False,
                "paper_count": 0,
                "page_count": 0,
                "chunk_count": 0,
            }

        return {
            "ready": True,
            "paper_count": self.state["paper_count"],
            "page_count": self.state["page_count"],
            "chunk_count": self.state["chunk_count"],
            "model": "BAAI/bge-small-en-v1.5",
            "reranker": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        }

    def search(self, question, paper_titles=None, search_mode="hybrid"):
        if not self.ready():
            self.build_sample_index()

        chunks = self.state["chunks"]

        if paper_titles:
            chunks = [
                chunk for chunk in chunks
                if chunk["paper_title"] in paper_titles
            ]

        if search_mode == "semantic":
            retrieved = search_chunks(
                query=question,
                chunks=chunks,
                model=self.state["embedding_model"],
                index=self.state["index"],
                top_k=10,
            )
        else:
            retrieved = rrf_hybrid_search_chunks(
                query=question,
                chunks=chunks,
                semantic_model=self.state["embedding_model"],
                semantic_index=self.state["index"],
                bm25_index=self.state["bm25_index"],
                top_k=10,
            )

        reranked = rerank_chunks(
            query=question,
            chunks=retrieved,
            reranker=self.state["reranker"],
            top_k=5,
        )

        answer = answer_from_evidence(
            query=question,
            chunks=reranked,
            min_score=1.0,
            max_chunks=3,
        )

        answer["evidence_strength"] = evidence_strength(reranked)
        answer["evidence_used"] = reranked

        return answer