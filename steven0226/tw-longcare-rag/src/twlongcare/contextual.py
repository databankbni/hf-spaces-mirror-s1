"""Contextual Retrieval：為每個 chunk 生成一句「此條文在該法中的定位摘要」。

摘要前置到 chunk 後再嵌入（BM25 亦索引同一份合成文字）。呼叫 GEMINI_LITE_MODEL
（一次性前處理，與 runtime provider 無關）；結果快取 `data/contextual_cache.json`，
重跑不重複計費。**任何實際 API 呼叫前必須先印成本估算、經作者確認**（CLAUDE.md）。

Prompt 設計：法規全文放在最前面作為各 chunk 共享的相同前綴，讓 Gemini 隱式
context cache 命中（快取命中部分計費約為 25%），指令與目標條文放在後面。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .chunking import Chunk, TokenCounter
from .llm_text import extract_text

# 官方牌價（USD / 1M tokens，2026-07 查證：gemini-3.1-flash-lite；D8 全案模型統一）
PRICE_IN_PER_M = 0.25
PRICE_OUT_PER_M = 1.50
EST_INSTRUCTION_TOKENS = 160
EST_OUTPUT_TOKENS_PER_CHUNK = 60

SUMMARY_MAX_TOKENS = 120  # 守門：單句摘要不應超過此數（pytest 驗證）


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_messages(law_full_text: str, law_name: str, chunk_text: str) -> list:
    """組出單一 chunk 的訊息串；law_full_text 為共享前綴（隱式快取友善）。"""
    from langchain_core.messages import HumanMessage

    prompt = (
        f"以下是《{law_name}》全文：\n\n{law_full_text}\n\n---\n"
        f"以下是上述法規中的一個條文片段：\n\n{chunk_text}\n\n"
        "請用一句繁體中文（60 字內）說明此條文在該法中的定位與主題，"
        "以利檢索系統理解片段脈絡。直接輸出那一句話，不要任何其他文字或標點以外的符號。"
    )
    return [HumanMessage(content=prompt)]


@dataclass
class CostEstimate:
    n_chunks: int
    input_tokens: int
    output_tokens: int

    @property
    def cost_no_cache(self) -> float:
        return (
            self.input_tokens * PRICE_IN_PER_M
            + self.output_tokens * PRICE_OUT_PER_M
        ) / 1_000_000

    @property
    def cost_with_implicit_cache(self) -> float:
        # 假設共享前綴（法規全文）約佔 95% 輸入且全部命中隱式快取（25% 計費）
        cached = self.input_tokens * 0.95
        fresh = self.input_tokens - cached
        return (
            cached * PRICE_IN_PER_M * 0.25
            + fresh * PRICE_IN_PER_M
            + self.output_tokens * PRICE_OUT_PER_M
        ) / 1_000_000


def estimate_cost(
    pending: list[Chunk],
    law_texts: dict[str, str],
    count_tokens: TokenCounter,
) -> CostEstimate:
    """估算尚未快取的 chunk 的生成成本。"""
    law_token_cache = {name: count_tokens(text) for name, text in law_texts.items()}
    input_tokens = sum(
        law_token_cache[c.law_name] + count_tokens(c.text) + EST_INSTRUCTION_TOKENS
        for c in pending
    )
    return CostEstimate(
        n_chunks=len(pending),
        input_tokens=input_tokens,
        output_tokens=len(pending) * EST_OUTPUT_TOKENS_PER_CHUNK,
    )


class ContextualCache:
    """chunk_id → {hash, summary, model}；hash 綁 chunk 內容，改文即失效。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict[str, dict] = {}
        if path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, chunk: Chunk) -> str | None:
        entry = self._data.get(chunk.chunk_id)
        if entry and entry["hash"] == _hash(chunk.text):
            return entry["summary"]
        return None

    def put(self, chunk: Chunk, summary: str, model: str) -> None:
        self._data[chunk.chunk_id] = {
            "hash": _hash(chunk.text),
            "summary": summary,
            "model": model,
        }

    def pending(self, chunks: list[Chunk]) -> list[Chunk]:
        return [c for c in chunks if self.get(c) is None]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
            newline="\n",
        )


def generate_summaries(
    pending: list[Chunk],
    law_texts: dict[str, str],
    cache: ContextualCache,
    model_name: str,
    api_key: str | None = None,
    max_concurrency: int = 4,
) -> None:
    """呼叫 GEMINI_LITE 補齊缺漏摘要並寫入快取（呼叫端負責成本確認）。

    穩健性：`model.batch()` 一次送出全部請求即已產生實際費用，任何後製
    處理錯誤都不該讓已付費的結果整批遺失——曾實際發生過 content 格式
    非預期導致單一例外中止迴圈、cache.save() 從未被呼叫、全部結果作廢。
    對策：逐筆立即存檔（單筆失敗不牽連其他）＋ return_exceptions 隔離
    單筆 API 錯誤，最後才彙整回報失敗清單。
    """
    from langchain.chat_models import init_chat_model

    model = init_chat_model(
        f"google_genai:{model_name}", temperature=0, api_key=api_key or None
    ).with_retry(stop_after_attempt=3)

    # 依法規分組送批次：同法規的請求相鄰，提高隱式快取命中率
    ordered = sorted(pending, key=lambda c: (c.law_name, c.part, c.article_no))
    batch = [build_messages(law_texts[c.law_name], c.law_name, c.text) for c in ordered]
    replies = model.batch(
        batch, config={"max_concurrency": max_concurrency}, return_exceptions=True
    )

    failures: list[tuple[str, str]] = []
    for chunk, reply in zip(ordered, replies):
        if isinstance(reply, BaseException):
            failures.append((chunk.chunk_id, repr(reply)))
            continue
        summary = extract_text(reply.content).strip().replace("\n", " ")
        if not summary:
            failures.append((chunk.chunk_id, "空回覆"))
            continue
        cache.put(chunk, summary, model_name)
        cache.save()  # 逐筆落地：已花費的 API 成本不因後續任何錯誤而作廢

    if failures:
        detail = "; ".join(f"{cid}: {err}" for cid, err in failures[:5])
        more = f"（其餘 {len(failures) - 5} 筆略）" if len(failures) > 5 else ""
        raise RuntimeError(
            f"{len(failures)}/{len(ordered)} 筆摘要生成失敗（已成功者已存入快取，"
            f"重跑只會補這些失敗筆）：{detail}{more}"
        )


def composite_text(chunk: Chunk, summary: str | None) -> str:
    """嵌入 / BM25 用的合成文字：摘要前置（無摘要即原文）。"""
    if summary:
        return f"{summary}\r\n{chunk.text}"
    return chunk.text
