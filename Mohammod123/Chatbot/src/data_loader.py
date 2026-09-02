"""Document loading utilities for PDF, CSV, and text files."""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_community.document_loaders import (
    CSVLoader,
    DirectoryLoader,
    PyMuPDFLoader,
    TextLoader,
)
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class DataLoader:
    """Load supported files from a data directory into LangChain Documents."""

    _LOADERS = {
        "**/*.pdf": (PyMuPDFLoader, {}),
        "**/*.csv": (CSVLoader, {"encoding": "utf-8"}),
        "**/*.txt": (TextLoader, {"encoding": "utf-8", "autodetect_encoding": True}),
    }

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = Path(data_dir)

    def load(self) -> list[Document]:
        """Load every supported file under the data directory."""
        if not self.data_dir.exists():
            logger.info("Data directory %s does not exist; creating it.", self.data_dir)
            self.data_dir.mkdir(parents=True, exist_ok=True)
            return []

        documents: list[Document] = []

        for glob_pattern, (loader_cls, loader_kwargs) in self._LOADERS.items():
            loader = DirectoryLoader(
                str(self.data_dir),
                glob=glob_pattern,
                loader_cls=loader_cls,
                loader_kwargs=loader_kwargs,
                recursive=True,
                show_progress=False,
                silent_errors=True,
                use_multithreading=True,
            )

            loaded = loader.load()
            normalized = [self._normalize_document(document) for document in loaded]
            documents.extend(normalized)

            logger.info(
                "Loaded %d document(s) for pattern %s from %s.",
                len(normalized),
                glob_pattern,
                self.data_dir,
            )

        logger.info("Loaded %d total document(s).", len(documents))
        return documents

    @staticmethod
    def _normalize_document(document: Document) -> Document:
        """Ensure every document has consistent source metadata."""
        metadata = dict(document.metadata or {})
        source = metadata.get("source") or metadata.get("file_path") or "unknown"
        source_path = Path(str(source))

        metadata["source"] = str(source)
        metadata["source_file"] = source_path.name

        return Document(page_content=document.page_content, metadata=metadata)


def load_documents(data_dir: str | Path = "data") -> list[Document]:
    """Convenience function for loading all supported documents."""
    return DataLoader(data_dir).load()
