"""生成端：僅依提供條文回答、句尾標 [法規名 §條號]、不足即誠實拒答。

parent-document 規則：檢索命中 sub-chunk 時，送給 LLM 的 context 還原整條全文
（語料僅 205 條，負擔小）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from .knowledge_base import active_laws_path
from .llm_text import extract_text
from .retriever import RetrievedChunk

REFUSAL_TEXT = "查無明確法源"

SYSTEM_PROMPT = (
    "你是台灣長期照顧法規諮詢助手。回答規則：\n"
    "1. 僅依下方「參考條文」回答問題，不得使用其他知識、不得編造條號。\n"
    "2. 每個論述句的句尾必須標注來源，格式為 [法規名 §條號]（§ 後面只放"
    "條號，不放「第」「條」等文字或項款數字），例如 [長期照顧服務法 §8-1]；"
    "同句多來源可並列 [甲法 §1][乙法 §2]。若句子本文也提到法規名或條號，"
    "務必與句尾方括號一致。\n"
    "3. 若參考條文不足以回答問題，直接說明「查無明確法源」，"
    "並建議撥打 1966 長照服務專線洽詢，不要勉強作答。\n"
    "4. 用繁體中文、平易近人的語氣回答，但內容必須嚴格對應條文。"
)

CITATION_RE = re.compile(r"\[([^\[\]§]+?)\s*§\s*([0-9]+(?:-[0-9]+)?)\]")


def extract_citations(text: str) -> list[tuple[str, str]]:
    """抽出文中所有 [法規名 §條號] 引用（P3 grounding 也用這支）。"""
    return [(m.group(1).strip(), m.group(2)) for m in CITATION_RE.finditer(text)]


class LawsLookup:
    """laws.json 條文索引：parent-document 還原與引用驗證用。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or active_laws_path()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.by_key: dict[tuple[str, str], dict] = {
            (r["pcode"], r["article_no"]): r for r in data["articles"]
        }
        self.by_name: dict[tuple[str, str], dict] = {
            (r["law_name"], r["article_no"]): r for r in data["articles"]
        }

    def full_article(self, pcode: str, article_no: str) -> dict | None:
        return self.by_key.get((pcode, article_no))


def dedup_articles(
    retrieved: list[RetrievedChunk], lookup: LawsLookup
) -> list[tuple[str, str, str]]:
    """檢索結果去重（sub-chunk 還原整條）並保序，回傳 (law_name, article_no, content)。"""
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for c in retrieved:
        if c.parent_id in seen:
            continue
        seen.add(c.parent_id)
        record = lookup.full_article(c.pcode, c.article_no)
        content = record["content"] if record else c.text
        out.append((c.law_name, c.article_no, content))
    return out


def build_context(retrieved: list[RetrievedChunk], lookup: LawsLookup) -> str:
    """檢索結果 → 參考條文區塊；sub-chunk 還原整條，去重後保序。"""
    return "\n\n".join(
        f"《{name}》第 {no} 條：\n{content}"
        for name, no, content in dedup_articles(retrieved, lookup)
    )


def build_related_context(related: list) -> str:
    """Phase 4 圖譜擴展的關聯條文 → context 區塊（與參考條文分開標示，
    避免跟直接檢索結果混淆——Phase 5 評估 precision 分母不計這些）。"""
    if not related:
        return ""
    return "\n\n".join(
        f"《{r.law_name}》第 {r.article_no} 條：\n{r.content}" for r in related
    )


def build_messages(
    question: str, retrieved: list[RetrievedChunk], lookup: LawsLookup,
    related: list | None = None,
):
    context = build_context(retrieved, lookup)
    parts = [f"參考條文：\n\n{context}"]
    related_ctx = build_related_context(related or [])
    if related_ctx:
        parts.append(
            "關聯條文（由上方條文的引用關係一階擴展帶入，可視情況輔助回答）：\n\n"
            + related_ctx
        )
    parts.append(f"---\n問題：{question}")
    user = "\n\n".join(parts)
    return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]


def answer(
    question: str, retrieved: list[RetrievedChunk], lookup: LawsLookup, model,
    related: list | None = None,
    on_response=None,
) -> str:
    if not retrieved:
        return f"{REFUSAL_TEXT}。建議撥打 1966 長照服務專線洽詢。"
    reply = model.invoke(build_messages(question, retrieved, lookup, related))
    if on_response is not None:
        on_response("answer_generation", reply)
    return extract_text(reply.content).strip()
