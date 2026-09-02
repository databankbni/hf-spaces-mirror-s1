"""
Heaven on Earth CMS Backend - Knowledge Base Service

RAG pipeline over static church content (web-crawled) and dynamic
PostgreSQL-cached data (events, ministries).

The SentenceTransformer model is injected at construction time — it is
loaded exactly once at startup and shared across the application.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.chatbot import ChatbotKnowledgeChunk
from app.models.event import Event
from app.models.ministry import Ministry

logger = structlog.get_logger(__name__)


class KnowledgeBaseService:
    """
    Service for managing and querying the chatbot RAG knowledge base.

    The embedding model is **injected** — never loaded inside this class.
    The caller is responsible for loading `SentenceTransformer` once at
    application startup.

    Attributes
    ----------
    _model:
        The injected sentence-transformers model instance.
    _last_refresh:
        In-memory dict mapping source_id → last ``updated_at`` datetime
        observed during a previous ``refresh_dynamic_content`` run.  Used
        for incremental change detection without a dedicated DB table.
    """

    def __init__(self, model: SentenceTransformer) -> None:
        self._model: SentenceTransformer = model
        # { "<source_type>:<source_id>": datetime } — persisted across calls
        self._last_refresh: dict[str, datetime] = {}

    # ------------------------------------------------------------------
    # 3.2  Embedding helper
    # ------------------------------------------------------------------

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Encode *texts* using the injected SentenceTransformer model.

        Parameters
        ----------
        texts:
            A list of text strings to embed.

        Returns
        -------
        list[list[float]]
            A list of 384-dimensional float vectors (one per input text).
        """
        vectors = self._model.encode(texts, batch_size=32)
        return [v.tolist() for v in vectors]

    # ------------------------------------------------------------------
    # 3.3  Add documents
    # ------------------------------------------------------------------

    async def add_documents(
        self, docs: list[dict], db: AsyncSession
    ) -> None:
        """
        Insert ``ChatbotKnowledgeChunk`` rows for each document dict.

        Each dict must contain the keys: ``content``, ``source_type``,
        ``source_url``, ``source_id``, ``language``, and ``chunk_index``.
        The embedding for every doc is computed in a single batch call.

        Parameters
        ----------
        docs:
            List of document dicts.
        db:
            SQLAlchemy async session (caller-managed transaction).
        """
        if not docs:
            return

        texts = [d["content"] for d in docs]
        embeddings = self.embed(texts)

        for doc, embedding in zip(docs, embeddings):
            chunk = ChatbotKnowledgeChunk(
                content=doc["content"],
                embedding=embedding,
                source_type=doc["source_type"],
                source_url=doc.get("source_url"),
                source_id=doc.get("source_id"),
                language=doc.get("language", "en"),
                chunk_index=doc["chunk_index"],
            )
            db.add(chunk)

        await db.flush()

    # ------------------------------------------------------------------
    # 3.4  Similarity query
    # ------------------------------------------------------------------

    async def query(
        self,
        question: str,
        db: AsyncSession,
        k: int = 4,
    ) -> list[ChatbotKnowledgeChunk]:
        """
        Retrieve the top-*k* knowledge chunks most similar to *question*.

        Uses a **parameterised** cosine-distance query via pgvector's
        ``<=>`` operator.  User input is never interpolated into SQL.

        Parameters
        ----------
        question:
            The user's natural-language question.
        db:
            SQLAlchemy async session.
        k:
            Number of chunks to return (default: 4).

        Returns
        -------
        list[ChatbotKnowledgeChunk]
            Top-*k* chunks ordered by ascending cosine distance
            (most similar first).
        """
        # Embed the question (single-item batch)
        [query_vector] = self.embed([question])

        # Parameterised query — :query_vector and :k are bind parameters,
        # never raw user input in the SQL string.
        sql = text(
            """
            SELECT id
            FROM   chatbot_knowledge_chunks
            ORDER  BY embedding <=> CAST(:query_vector AS vector)
            LIMIT  :k
            """
        )

        result = await db.execute(
            sql,
            {"query_vector": str(query_vector), "k": k},
        )
        chunk_ids = [row[0] for row in result.fetchall()]

        if not chunk_ids:
            return []

        rows = await db.execute(
            select(ChatbotKnowledgeChunk).where(
                ChatbotKnowledgeChunk.id.in_(chunk_ids)
            )
        )
        chunks = rows.scalars().all()

        # Re-order by the original distance ranking
        id_to_chunk = {str(c.id): c for c in chunks}
        return [id_to_chunk[str(cid)] for cid in chunk_ids if str(cid) in id_to_chunk]

    # ------------------------------------------------------------------
    # 3.5  Web crawl and index
    # ------------------------------------------------------------------

    async def crawl_and_index(
        self,
        urls: list[str],
        db: AsyncSession,
    ) -> dict:
        """
        Crawl *urls*, extract text, split into chunks, and insert into
        the knowledge base.

        This operation is **idempotent**: existing ``web_crawl`` chunks for
        each URL are deleted before new ones are inserted.

        Parameters
        ----------
        urls:
            List of HTTP/HTTPS URLs to crawl.
        db:
            SQLAlchemy async session.

        Returns
        -------
        dict
            ``{"urls_crawled": int, "chunks_created": int, "errors": list[str]}``
        """
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
        )
        urls_crawled = 0
        chunks_created = 0
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=10.0) as client:
            for url in urls:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                except Exception as exc:
                    errors.append(f"{url}: {exc}")
                    logger.warning("crawl_url_failed", url=url, error=str(exc))
                    continue

                # Parse HTML and strip boilerplate tags
                soup = BeautifulSoup(response.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                page_text = soup.get_text(separator=" ", strip=True)

                # Chunk the text
                text_chunks = splitter.split_text(page_text)
                if not text_chunks:
                    urls_crawled += 1
                    continue

                # Idempotent: delete existing chunks for this URL
                await db.execute(
                    delete(ChatbotKnowledgeChunk).where(
                        ChatbotKnowledgeChunk.source_type == "web_crawl",
                        ChatbotKnowledgeChunk.source_url == url,
                    )
                )

                # Embed all chunks in a single batch call
                embeddings = self.embed(text_chunks)

                for idx, (chunk_text, embedding) in enumerate(
                    zip(text_chunks, embeddings)
                ):
                    chunk = ChatbotKnowledgeChunk(
                        content=chunk_text,
                        embedding=embedding,
                        source_type="web_crawl",
                        source_url=url,
                        source_id=None,
                        language="en",
                        chunk_index=idx,
                    )
                    db.add(chunk)

                chunks_created += len(text_chunks)
                urls_crawled += 1

        await db.flush()

        logger.info(
            "crawl_and_index_complete",
            urls_crawled=urls_crawled,
            chunks_created=chunks_created,
            errors=len(errors),
        )
        return {
            "urls_crawled": urls_crawled,
            "chunks_created": chunks_created,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # 3.6  Refresh dynamic content (events + ministries)
    # ------------------------------------------------------------------

    async def refresh_dynamic_content(self, db: AsyncSession) -> dict:
        """
        Incrementally refresh event and ministry chunks in the vector store.

        Only records whose ``updated_at`` timestamp is **newer** than the
        value recorded during the previous refresh (stored in
        ``self._last_refresh``) are re-embedded and re-inserted.

        Chunks whose source records have been removed from the DB are also
        deleted.

        Parameters
        ----------
        db:
            SQLAlchemy async session.

        Returns
        -------
        dict
            Summary with keys: ``events_fetched``, ``ministries_fetched``,
            ``chunks_upserted``, ``chunks_deleted``, ``duration_ms``.
        """
        start_time = time.monotonic()
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
        )
        chunks_upserted = 0
        chunks_deleted = 0

        # ------------------------------------------------------------------
        # Events — filter by is_published=True
        # ------------------------------------------------------------------
        events_result = await db.execute(
            select(Event).where(Event.is_published == True)  # noqa: E712
        )
        events: list[Event] = list(events_result.scalars().all())

        # Fetch current set of event IDs from DB
        current_event_ids = {str(e.id) for e in events}

        # Delete chunks for events that no longer exist (removed from DB)
        existing_event_chunks = await db.execute(
            select(ChatbotKnowledgeChunk.source_id).where(
                ChatbotKnowledgeChunk.source_type == "db_events"
            )
        )
        known_event_ids = {
            row[0] for row in existing_event_chunks.fetchall() if row[0]
        }
        stale_event_ids = known_event_ids - current_event_ids
        if stale_event_ids:
            for stale_id in stale_event_ids:
                del_result = await db.execute(
                    delete(ChatbotKnowledgeChunk)
                    .where(ChatbotKnowledgeChunk.source_type == "db_events")
                    .where(ChatbotKnowledgeChunk.source_id == stale_id)
                )
                chunks_deleted += del_result.rowcount

        # Upsert changed or new events
        for event in events:
            cache_key = f"db_events:{event.id}"
            last_seen: Optional[datetime] = self._last_refresh.get(cache_key)

            # Check whether this record was updated since last refresh
            record_updated_at: datetime = event.updated_at
            if record_updated_at.tzinfo is None:
                record_updated_at = record_updated_at.replace(
                    tzinfo=timezone.utc
                )

            if last_seen is not None and record_updated_at <= last_seen:
                # Not changed — skip
                continue

            # Delete old chunks for this event
            del_result = await db.execute(
                delete(ChatbotKnowledgeChunk)
                .where(ChatbotKnowledgeChunk.source_type == "db_events")
                .where(ChatbotKnowledgeChunk.source_id == str(event.id))
            )
            chunks_deleted += del_result.rowcount

            # Format event as text
            event_text = (
                f"Event: {event.title}\n"
                f"Date: {event.event_date}\n"
                f"Location: {event.location}\n"
                f"Description: {event.description}"
            )

            # Split and embed
            text_chunks = splitter.split_text(event_text)
            if not text_chunks:
                self._last_refresh[cache_key] = record_updated_at
                continue

            embeddings = self.embed(text_chunks)
            for idx, (chunk_text, embedding) in enumerate(
                zip(text_chunks, embeddings)
            ):
                db.add(
                    ChatbotKnowledgeChunk(
                        content=chunk_text,
                        embedding=embedding,
                        source_type="db_events",
                        source_url=None,
                        source_id=str(event.id),
                        language="en",
                        chunk_index=idx,
                    )
                )
            chunks_upserted += len(text_chunks)
            self._last_refresh[cache_key] = record_updated_at

        # ------------------------------------------------------------------
        # Ministries — filter by is_active=True
        # ------------------------------------------------------------------
        ministries_result = await db.execute(
            select(Ministry).where(Ministry.is_active == True)  # noqa: E712
        )
        ministries: list[Ministry] = list(ministries_result.scalars().all())

        current_ministry_ids = {str(m.id) for m in ministries}

        # Delete chunks for removed ministries
        existing_ministry_chunks = await db.execute(
            select(ChatbotKnowledgeChunk.source_id).where(
                ChatbotKnowledgeChunk.source_type == "db_ministries"
            )
        )
        known_ministry_ids = {
            row[0] for row in existing_ministry_chunks.fetchall() if row[0]
        }
        stale_ministry_ids = known_ministry_ids - current_ministry_ids
        if stale_ministry_ids:
            for stale_id in stale_ministry_ids:
                del_result = await db.execute(
                    delete(ChatbotKnowledgeChunk)
                    .where(
                        ChatbotKnowledgeChunk.source_type == "db_ministries"
                    )
                    .where(ChatbotKnowledgeChunk.source_id == stale_id)
                )
                chunks_deleted += del_result.rowcount

        # Upsert changed or new ministries
        for ministry in ministries:
            cache_key = f"db_ministries:{ministry.id}"
            last_seen = self._last_refresh.get(cache_key)

            record_updated_at = ministry.updated_at
            if record_updated_at.tzinfo is None:
                record_updated_at = record_updated_at.replace(
                    tzinfo=timezone.utc
                )

            if last_seen is not None and record_updated_at <= last_seen:
                continue

            # Delete old chunks for this ministry
            del_result = await db.execute(
                delete(ChatbotKnowledgeChunk)
                .where(ChatbotKnowledgeChunk.source_type == "db_ministries")
                .where(ChatbotKnowledgeChunk.source_id == str(ministry.id))
            )
            chunks_deleted += del_result.rowcount

            # Format ministry as text
            ministry_text = (
                f"Ministry: {ministry.title}\n"
                f"Description: {ministry.description}\n"
                f"Leader: {ministry.leader_name}"
            )

            text_chunks = splitter.split_text(ministry_text)
            if not text_chunks:
                self._last_refresh[cache_key] = record_updated_at
                continue

            embeddings = self.embed(text_chunks)
            for idx, (chunk_text, embedding) in enumerate(
                zip(text_chunks, embeddings)
            ):
                db.add(
                    ChatbotKnowledgeChunk(
                        content=chunk_text,
                        embedding=embedding,
                        source_type="db_ministries",
                        source_url=None,
                        source_id=str(ministry.id),
                        language="en",
                        chunk_index=idx,
                    )
                )
            chunks_upserted += len(text_chunks)
            self._last_refresh[cache_key] = record_updated_at

        await db.flush()

        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        summary = {
            "events_fetched": len(events),
            "ministries_fetched": len(ministries),
            "chunks_upserted": chunks_upserted,
            "chunks_deleted": chunks_deleted,
            "duration_ms": duration_ms,
        }

        logger.info(
            "knowledge_refresh_complete",
            **summary,
        )

        return summary
