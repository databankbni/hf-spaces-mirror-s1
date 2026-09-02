"""Embedding and chunking pipeline for RAG indexing."""

from __future__ import annotations

import logging

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class EmbeddingPipeline:
    """Split documents and embed them with a local sentence-transformers model."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> None:
        self.model_name = model_name
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=True,
        )
        self.embeddings = HuggingFaceEmbeddings(
            model_name=model_name,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        """Split source documents into retrieval-sized chunks."""
        if not documents:
            logger.info("No documents provided for splitting.")
            return []

        chunks = self.text_splitter.split_documents(documents)
        logger.info("Split %d document(s) into %d chunk(s).", len(documents), len(chunks))
        return chunks
