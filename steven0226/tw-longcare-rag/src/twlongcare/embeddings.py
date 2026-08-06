"""sentence-transformers 模型的 LangChain Embeddings 包裝。

鐵律（CLAUDE.md）：query 與 document 必須分別走 encode_query() /
encode_document()——EmbeddingGemma 系（GTAIDE）兩路徑使用不同 prompt，
混用會讓檢索品質嚴重下降。對無 prompt 的模型（如 bge-m3），
sentence-transformers 會自動退回一般 encode，同一包裝兩模型通用。
"""

from __future__ import annotations

from langchain_core.embeddings import Embeddings


class STEmbeddings(Embeddings):
    """通用包裝：embed_documents → encode_document、embed_query → encode_query。"""

    def __init__(
        self,
        model_id: str,
        *,
        device: str | None = None,
        truncate_dim: int | None = None,
        hf_token: str | None = None,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_id = model_id
        self.truncate_dim = truncate_dim
        self._model = SentenceTransformer(
            model_id,
            device=device,
            truncate_dim=truncate_dim,
            token=hf_token or None,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode_document(
            texts, normalize_embeddings=True, show_progress_bar=False
        ).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self._model.encode_query(
            [text], normalize_embeddings=True, show_progress_bar=False
        )[0].tolist()
