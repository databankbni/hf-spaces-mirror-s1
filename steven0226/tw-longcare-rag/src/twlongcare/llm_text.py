"""LangChain AIMessage.content 正規化：不同 provider/版本可能回傳純字串，
也可能回傳 list of content parts（實測 langchain-google-genai 曾整批如此）。
任何直接對 reply.content 呼叫 .strip() 的地方都必須先過這支，否則遇到
list 格式會直接 AttributeError 崩潰。"""

from __future__ import annotations


def extract_text(content: str | list) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(item["text"])
        return "".join(parts)
    return str(content)
