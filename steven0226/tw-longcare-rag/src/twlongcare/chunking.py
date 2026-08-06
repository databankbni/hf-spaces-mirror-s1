"""條文 chunking：以「條」為單位，超過 token 上限才以段落（項/款）切分。

規則（PLAN.md Phase 2、D7）：
- 每條一個 chunk；token 數（GTAIDE tokenizer 計）> MAX_TOKENS 才切分
- 切點只允許在段落邊界（law.moj 條文以 \r\n 分隔「項/款」行），
  禁止在 token 中線切壞項/款；單一段落本身超限時保留整段不硬切（記 warning）
- sub-chunk 前置「{法規名}第X條（續）」保留出處；metadata 記 parent_id，
  檢索命中 sub-chunk 後由生成端還原整條全文（parent-document 規則）
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_TOKENS = 512


@dataclass(frozen=True)
class Chunk:
    """單一嵌入單位；part=0 為整條，part>=1 為分段（parent_id 指向整條 id）。"""

    chunk_id: str
    parent_id: str
    part: int
    text: str
    law_name: str
    pcode: str
    article_no: str
    chapter: str | None
    url: str


TokenCounter = Callable[[str], int]


def _split_paragraphs(content: str) -> list[str]:
    """依 \r\n（或殘留的 \n）切出段落行，保留原文字。"""
    return [line for line in content.replace("\r\n", "\n").split("\n") if line.strip()]


def chunk_article(article: dict, count_tokens: TokenCounter) -> list[Chunk]:
    """單一條文 record（laws.json articles 元素）→ 1..n 個 Chunk。"""
    base_id = f"{article['pcode']}-{article['article_no']}"
    common = {
        "law_name": article["law_name"],
        "pcode": article["pcode"],
        "article_no": article["article_no"],
        "chapter": article.get("chapter"),
        "url": article["url"],
    }
    content = article["content"]
    if count_tokens(content) <= MAX_TOKENS:
        return [Chunk(chunk_id=base_id, parent_id=base_id, part=0, text=content, **common)]

    prefix = f"{article['law_name']}第{article['article_no']}條（續）"
    budget = MAX_TOKENS - count_tokens(prefix + "\r\n")
    paragraphs = _split_paragraphs(content)

    segments: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for para in paragraphs:
        para_tokens = count_tokens(para)
        if para_tokens > budget and not current:
            # 單段落超限：整段保留不硬切（法條項/款極少超過 512 token）
            logger.warning(
                "%s 單一段落 %d tokens 超過切分預算 %d，保留整段",
                base_id, para_tokens, budget,
            )
            segments.append([para])
            continue
        if current and current_tokens + para_tokens > budget:
            segments.append(current)
            current, current_tokens = [], 0
        current.append(para)
        current_tokens += para_tokens
    if current:
        segments.append(current)

    chunks = []
    for i, seg in enumerate(segments, start=1):
        chunks.append(Chunk(
            chunk_id=f"{base_id}-p{i}",
            parent_id=base_id,
            part=i,
            text=prefix + "\r\n" + "\r\n".join(seg),
            **common,
        ))
    return chunks


def chunk_articles(
    articles: list[dict], count_tokens: TokenCounter
) -> list[Chunk]:
    """全部條文 → chunk 清單（保持原順序）。"""
    chunks: list[Chunk] = []
    for article in articles:
        chunks.extend(chunk_article(article, count_tokens))
    return chunks


@dataclass
class ChunkStats:
    total_articles: int = 0
    total_chunks: int = 0
    split_articles: list[str] = field(default_factory=list)


def chunk_stats(articles: list[dict], chunks: list[Chunk]) -> ChunkStats:
    split = sorted({c.parent_id for c in chunks if c.part > 0})
    return ChunkStats(
        total_articles=len(articles),
        total_chunks=len(chunks),
        split_articles=split,
    )


def gtaide_token_counter(model_id: str, hf_token: str | None = None) -> TokenCounter:
    """以 GTAIDE（EmbeddingGemma）tokenizer 建 token 計數器（需下載 tokenizer）。"""
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_id, token=hf_token or None)

    def count(text: str) -> int:
        return len(tokenizer.encode(text, add_special_tokens=True))

    return count
