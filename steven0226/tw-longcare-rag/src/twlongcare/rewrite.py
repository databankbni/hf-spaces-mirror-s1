"""Query 改寫：把口語問題改寫為法規檢索用語（例：「阿嬤請看護政府有補助嗎」→
長照給付、補助資格、外籍看護、家庭照顧者支持服務）。"""

from __future__ import annotations

import sys

from langchain_core.messages import HumanMessage, SystemMessage

from .llm_text import extract_text

# 初版：純抽象指令（保留供評測對照；D10 評測後預設改用 few-shot 版）
REWRITE_SYSTEM_V1 = (
    "你是台灣長期照顧法規檢索系統的查詢改寫器。"
    "把使用者的口語問題改寫成適合檢索法規條文的正式用語，"
    "保留原意並補上可能對應的法規關鍵詞（如：長照服務給付、失能等級、"
    "家庭照顧者、喘息服務、機構設立許可、罰鍰）。"
    "只輸出改寫後的一行檢索查詢，不要解釋、不要標點以外的符號。"
)

# few-shot 版：小模型跟範例學比跟抽象規則學更穩（Phase 2/3 的 prompt 迭代
# 已兩度證實這點）；附微型口語→法規語對照，範例保持三個就好不要再加
REWRITE_SYSTEM = (
    "你是台灣長期照顧法規檢索系統的查詢改寫器。"
    "把口語問題改寫成適合檢索法規條文的正式用語，補上對應的法規關鍵詞。"
    "常見對應：阿嬤/阿公/長輩→失能老人、失能者；請看護→聘僱外籍看護、個人看護者；"
    "安養院/養老院→住宿式長照機構、老人福利機構；日照→日間照顧；"
    "補助→給付、額度、補助基準；評估→照顧管理中心、長照需要等級。\n"
    "範例：\n"
    "問：阿嬤請看護政府有補助嗎\n改：聘僱外籍看護 長照服務給付額度 失能者補助資格\n"
    "問：開日照中心要什麼證照\n改：日間照顧 長照機構設立許可 申請文件\n"
    "問：阿公失智了可以申請什麼\n改：失智症 長照服務申請資格 給付項目\n"
    "只輸出改寫後的一行檢索查詢，不要解釋。"
)


def rewrite_query(
    question: str,
    model,
    system: str = REWRITE_SYSTEM,
    on_response=None,
) -> str:
    """改寫失敗（空回覆/例外）時回退原問題，不讓改寫成為單點故障。"""
    try:
        reply = model.invoke([
            SystemMessage(content=system),
            HumanMessage(content=question),
        ])
        if on_response is not None:
            on_response("query_rewrite", reply)
        text = extract_text(reply.content)
        rewritten = text.strip().splitlines()[0].strip() if text.strip() else ""
        return rewritten or question
    except Exception as e:  # noqa: BLE001 - 改寫非關鍵路徑，仍印出真實原因供除錯
        print(f"[rewrite] 改寫失敗，退回原始問題：{e!r}", file=sys.stderr)
        return question


REFINE_SYSTEM = (
    "你是法規檢索查詢修正器。第一次檢索的證據不足或互相衝突。"
    "根據原始問題、第一次查詢與候選條文標題，產生一個更明確的檢索查詢。"
    "不得改變原意、不得假定使用者未提供的事實、不得回答問題。"
    "只輸出一行查詢。"
)


def refine_query(
    question: str,
    previous_query: str,
    retrieved,
    model,
    *,
    on_response=None,
) -> str:
    """One-shot corrective query refinement.

    The caller owns the iteration budget.  This function performs exactly one
    model call and falls back to the previous query on any failure.
    """
    candidates = "\n".join(
        f"- {chunk.law_name} 第{chunk.article_no}條：{chunk.text[:180]}"
        for chunk in retrieved[:5]
    )
    prompt = (
        f"原始問題：{question}\n"
        f"第一次查詢：{previous_query}\n"
        f"第一次候選：\n{candidates or '- 無候選'}"
    )
    try:
        reply = model.invoke([
            SystemMessage(content=REFINE_SYSTEM),
            HumanMessage(content=prompt),
        ])
        if on_response is not None:
            on_response("query_refinement", reply)
        text = extract_text(reply.content)
        lines = [
            line.strip().lstrip("-•").strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("```")
        ]
        # Small local models occasionally prepend “以下是更明確的查詢：”
        # despite the output contract.  Prefer the final non-explanatory line.
        explanatory = ("以下", "根據", "說明", "修正理由", "原始問題")
        candidates = [
            line for line in lines
            if not line.startswith(explanatory)
        ]
        refined = (candidates[-1] if candidates else (lines[-1] if lines else ""))
        refined = refined.strip("「」\"' ")
        refined = refined.removeprefix("修正後查詢：").removeprefix("查詢：").strip()
        if (
            len(refined) < 4
            or len(refined) > 64
            or any(mark in refined for mark in ("。", "；", "這個查詢", "查詢策略"))
        ):
            # Reject answer-like or malformed model output.  Combining the
            # original intent with the first query is a deterministic, bounded
            # corrective fallback and cannot invent a new user fact.
            refined = f"{question} {previous_query}".strip()[:160]
        return refined or previous_query
    except Exception as e:  # noqa: BLE001 - bounded corrective path must degrade safely
        print(f"[refine] 修正失敗，保留第一次查詢：{e!r}", file=sys.stderr)
        return previous_query
