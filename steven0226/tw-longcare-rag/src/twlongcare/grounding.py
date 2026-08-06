"""逐句 groundedness 查核（CRAG 式，Phase 3）：生成後對每句話核對「參考條文是否
真的支持這句話」，不受支持者刪除，log 可稽核。

分句規則（核心賣點，改動必須同步改 tests/test_grounding.py）：
1. 先按換行切段落，段落間互不影響分句
2. 段落內按「。！？」切句，但跳過「」『』（）巢狀引號/括號內的標點（不切）
3. 句尾的方括號引用 [...]（可能多個相連、可能夾雜多餘句號，如
   "……補助。[老人福利法 §15]。"）一律併回前一個真句子，不獨立成句
4. 過濾：<8 字的片段（citation 不計入字數）、無中文內容的片段、
   樣板句（拒答語、「請撥打1966」轉介語）不送查核——這些不含法律主張

Judge 設計：一次呼叫送出全部候選句 + top-5 條文全文，回 JSON verdict array，
每句附「真正支持它的 article_no」。Phase 2 驗收實測到兩種真實案例，judge
prompt 明確要求涵蓋：(a) 句尾引用格式對，但內文提及的法規名跟引用不符；
(b) 句子內容正確，但完全沒有句尾引用（漏標）。兩者皆判定為不支持並移除。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .generate import REFUSAL_TEXT, LawsLookup, dedup_articles
from .llm_text import extract_text
from .retriever import RetrievedChunk

# ---------- 分句 ----------

_OPEN_QUOTES = "「『（"
_CLOSE_QUOTES = "」』）"
_SENTENCE_END = "。！？"

_CITATION_ONLY_RE = re.compile(r"^(?:\[[^\[\]]+\][。！？]?)+$")
_CITATION_STRIP_RE = re.compile(r"\[[^\[\]]+\]")
_HAN_RE = re.compile(r"[一-鿿]")
_REFUSAL_PREFIXES = (REFUSAL_TEXT,)
_HOTLINE_RE = re.compile(r"1966")
_REFERRAL_HINT_RE = re.compile(r"建議|洽詢|撥打|專人")

MIN_SENTENCE_CHARS = 8


def _raw_split(paragraph: str) -> list[str]:
    """段落內依句尾標點切分，跳過引號/括號內的標點；標點併入前一片段。

    已知限制：若句尾引用與下一句完全無分隔（無空白/換行）直接相連
    （如「...結束[甲法§1]接著下一句」），下一句會被誤併入引用所在片段。
    實測所有真實生成輸出的引用後面都接空白或換行，未觀察到此情況，
    故不特別處理；若未來實測發現真實案例，回來加解析。
    """
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in paragraph:
        buf.append(ch)
        if ch in _OPEN_QUOTES:
            depth += 1
        elif ch in _CLOSE_QUOTES:
            depth = max(0, depth - 1)
        elif ch in _SENTENCE_END and depth == 0:
            parts.append("".join(buf))
            buf = []
    if buf:
        parts.append("".join(buf))
    return parts


def _merge_citation_tails(parts: list[str]) -> list[str]:
    """「純由方括號引用（可能夾句號）組成」的片段併回前一個真句子。"""
    merged: list[str] = []
    for part in parts:
        stripped = part.strip()
        if merged and stripped and _CITATION_ONLY_RE.match(stripped):
            merged[-1] = merged[-1].rstrip() + stripped
        else:
            merged.append(part)
    return merged


def _is_template_sentence(text: str) -> bool:
    stripped = text.strip()
    if any(stripped.startswith(p) for p in _REFUSAL_PREFIXES):
        return True
    if _HOTLINE_RE.search(stripped) and _REFERRAL_HINT_RE.search(stripped):
        return True
    return False


def _is_substantive(text: str) -> bool:
    content_only = _CITATION_STRIP_RE.sub("", text).strip()
    if len(content_only) < MIN_SENTENCE_CHARS:
        return False
    if not _HAN_RE.search(content_only):
        return False
    return not _is_template_sentence(text)


def _split_with_paragraphs(text: str) -> list[tuple[int, str]]:
    """回傳 (paragraph_index, sentence)；供需保留段落換行的呼叫端使用。"""
    result: list[tuple[int, str]] = []
    for p_idx, paragraph in enumerate(text.split("\n")):
        if not paragraph.strip():
            continue
        merged = _merge_citation_tails(_raw_split(paragraph))
        for s in merged:
            s = s.strip()
            if s and _is_substantive(s):
                result.append((p_idx, s))
    return result


def split_sentences(text: str) -> list[str]:
    """核心分句函式（公開 API）：見模組 docstring 規則。回傳已過濾候選句清單。"""
    return [s for _, s in _split_with_paragraphs(text)]


# ---------- judge ----------

GROUNDING_JUDGE_PROMPT = """你是法規回答的查核員。以下是「參考條文」（依序編號）與「候選句清單」。
針對每一句話，判斷它的內容是否被參考條文中「某一條」的原文實際支持——不能只因為
句尾寫了引用標記就算數，必須確認條文原文真的講了這件事。若句子本文提及了法規
名稱或條號，也要確認跟真正支持它的條文是否一致（若不一致，視為不支持）。

參考條文（依序編號）：
{context}

候選句清單（依序編號，共 {n_sentences} 句）：
{numbered_sentences}

**輸出的 JSON 陣列必須恰好有 {n_sentences} 個元素，每一句話都要有一個判定，
不可省略任何一句、也不可重複判定同一句。** 每個元素對應一句話，格式：
[{{"index": 1, "supported": true, "context_no": 3, "reason": "一句話理由"}}]
- supported：這句話是否被參考條文中某一條的原文實際支持
- context_no：supported 為 true 時，填入真正支持它的參考條文編號（上方
  參考條文的編號，一個整數）；否則為 null。**不要輸出法規名稱本身**，
  只填編號數字。
- reason：一句話說明理由（判定不支持時，說明句子跟條文哪裡兜不起來）
不要輸出 JSON 以外的文字，不要用 markdown code fence。"""

# Ollama 原生 format 參數用：直接約束輸出為此形狀的陣列（解碼層級強制，
# 比純 prompt 要求可靠得多）。article_no 原本要求模型重打完整「法規名
# §條號」字串，實測長法規名（如「長期照顧服務機構設立許可及管理辦法」）
# 會誘發地端 12B 陷入字元重複輸出、陣列永不收尾——JSON 語法約束只保證
# 結構合法，不保證字串「內容」不失控。改用 context_no 純整數索引後
# （呼叫端自行對應回法規名），此問題消失。
def _judge_json_schema(n_sentences: int) -> dict:
    """minItems/maxItems 釘死陣列長度＝句數：解碼層級保證涵蓋每一句判定，
    避免模型在較長回答時提早收尾陣列、遺漏後段句子的判定。"""
    return {
        "type": "array",
        "minItems": n_sentences,
        "maxItems": n_sentences,
        "items": {
            "type": "object",
            "properties": {
                "index": {"type": "integer"},
                "supported": {"type": "boolean"},
                "context_no": {"type": ["integer", "null"]},
                "reason": {"type": "string"},
            },
            "required": ["index", "supported"],
        },
    }


@dataclass
class SentenceVerdict:
    sentence: str
    supported: bool
    article_no: str | None
    reason: str


def _parse_json_array(text: str) -> list[dict]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"judge 回覆內找不到 JSON 陣列：{cleaned[:200]!r}")
    return json.loads(cleaned[start : end + 1])


class JudgeUnavailable(RuntimeError):
    """judge 呼叫失敗或回覆無法解析（實測過地端小模型在長 prompt 下偶發
    輸出陷入重複迴圈、JSON 陣列不收尾）；由呼叫端決定降級策略。"""


def judge_sentences(
    sentences: list[str],
    retrieved: list[RetrievedChunk],
    lookup: LawsLookup,
    model,
    retries: int = 1,
    related: list | None = None,
    on_response=None,
    on_retry=None,
) -> list[SentenceVerdict]:
    """一次呼叫批次判定全部候選句；judge 沒回覆到的句子保守視為不支持。

    重試一次後仍解析失敗則拋 JudgeUnavailable（不吞錯，讓呼叫端決定
    要拒答還是放行未查核內容——這是信任層級的決策，不該在此處預設）。

    related：Phase 4 圖譜擴展的關聯條文，併入 judge 可查核的條文範圍
    （否則句子若只被關聯條文支持，會被誤判不支持——回答本來就允許引用
    這些條文，查核範圍不該比生成範圍窄）。
    """
    if not sentences:
        return []

    is_ollama = False
    try:
        from langchain_ollama import ChatOllama

        is_ollama = isinstance(model, ChatOllama)
    except ImportError:
        pass

    articles = dedup_articles(retrieved, lookup)
    articles += [(r.law_name, r.article_no, r.content) for r in (related or [])]
    context = "\n\n".join(
        f"[{i}] 《{name}》第 {no} 條：\n{content}"
        for i, (name, no, content) in enumerate(articles, start=1)
    )

    # 實測：地端 12B 一次批次判定多句時，會把不同句子的判定理由互相混淆
    # （例如把 A 句的判定理由複製貼到 B 句，導致明明條文沒寫的內容被誤判
    # 為支持）——同一案例逐句單獨判定兩次都正確、四句一起判就出錯，
    # 可重現地證實是「同批句數」而非條文長度導致精度下降。雲端模型
    # （gemini/openai）批次判定已驗證準確，故僅對 Ollama 限縮批次為 1。
    batch_size = 1 if is_ollama else len(sentences)

    verdicts: list[SentenceVerdict] = []
    for start in range(0, len(sentences), batch_size):
        batch = sentences[start : start + batch_size]
        batch_items = _judge_batch(
            batch,
            context,
            articles,
            model,
            is_ollama,
            retries,
            on_response,
            on_retry,
        )
        verdicts.extend(batch_items)
    return verdicts


def _judge_batch(
    sentences: list[str],
    context: str,
    articles: list[tuple[str, str, str]],
    model,
    is_ollama: bool,
    retries: int,
    on_response=None,
    on_retry=None,
) -> list[SentenceVerdict]:
    """對一小批句子（可能只有 1 句）呼叫 judge 並回傳對應 verdict，保持原順序。"""
    from langchain_core.messages import HumanMessage

    if is_ollama:
        model = model.bind(format=_judge_json_schema(len(sentences)))

    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences, start=1))
    prompt = GROUNDING_JUDGE_PROMPT.format(
        context=context, numbered_sentences=numbered, n_sentences=len(sentences)
    )

    last_err: Exception | None = None
    items: list[dict] | None = None
    for attempt in range(retries + 1):
        try:
            reply = model.invoke([HumanMessage(content=prompt)])
            if on_response is not None:
                on_response("sentence_grounding", reply)
            raw = extract_text(reply.content)
            items = _parse_json_array(raw)
            break
        except Exception as e:  # noqa: BLE001 - 涵蓋解析錯誤與呼叫例外，統一重試
            last_err = e
            if attempt < retries and on_retry is not None:
                on_retry()
    if items is None:
        raise JudgeUnavailable(f"judge 呼叫/解析連續失敗（重試 {retries} 次）：{last_err}")

    by_index = {int(item["index"]): item for item in items if "index" in item}

    verdicts: list[SentenceVerdict] = []
    for i, s in enumerate(sentences, start=1):
        item = by_index.get(i)
        if item is None:
            verdicts.append(SentenceVerdict(s, False, None, "judge 未回覆此句判定"))
            continue
        supported = bool(item.get("supported", False))
        article_no = None
        if supported:
            try:
                name, no, _content = articles[int(item.get("context_no")) - 1]
                article_no = f"{name} §{no}"
            except (TypeError, ValueError, IndexError):
                supported = False  # context_no 指到不存在的條文，視同無支持
        verdicts.append(SentenceVerdict(
            sentence=s,
            supported=supported,
            article_no=article_no,
            reason=str(item.get("reason", "")),
        ))
    return verdicts


# ---------- 拒答門檻 ----------

# 校準依據（2026-07-20 實跑 scripts/calibrate_grounding.py，5 正常題 + 5
# 陷阱題，皆先過 query 改寫再檢索——與 cli.py 實際流程一致；D10 改寫
# prompt 換 few-shot 版後重校準）：正常題 rerank top-1 分數 0.718〜0.730；
# 陷阱題 0.507〜0.553。兩組完全分離（分離幅度較 V1 prompt 更大），取中點。
# dev set 僅 5+5 題，樣本小，Phase 5 正式評估應擴大樣本重新驗證此門檻。
REFUSAL_RERANK_THRESHOLD = 0.636


def should_refuse_before_generation(retrieved: list[RetrievedChunk]) -> bool:
    """檢索分數過低時，跳過生成直接拒答（省一次 LLM 呼叫，且更保守）。"""
    if not retrieved:
        return True
    top_score = retrieved[0].rerank_score
    if top_score is None:
        return False  # --no-rerank 模式不套用此規則
    return top_score < REFUSAL_RERANK_THRESHOLD


# ---------- 套用 ----------

@dataclass
class GroundingResult:
    original_text: str
    final_text: str
    verdicts: list[SentenceVerdict] = field(default_factory=list)
    removed_count: int = 0


REFUSAL_FINAL_TEXT = f"{REFUSAL_TEXT}。建議撥打 1966 長照服務專線洽詢。"


def apply_grounding(
    text: str, retrieved: list[RetrievedChunk], lookup: LawsLookup, model,
    related: list | None = None,
    on_response=None,
    on_retry=None,
) -> GroundingResult:
    """生成後查核：不受支持的句子從最終回答中移除，保留段落結構。

    related：Phase 4 圖譜擴展的關聯條文，一併納入 judge 可查核範圍。
    """
    pairs = _split_with_paragraphs(text)
    sentences = [s for _, s in pairs]
    verdicts = judge_sentences(
        sentences,
        retrieved,
        lookup,
        model,
        related=related,
        on_response=on_response,
        on_retry=on_retry,
    )

    kept_by_para: dict[int, list[str]] = {}
    for (p_idx, _s), v in zip(pairs, verdicts):
        if v.supported:
            kept_by_para.setdefault(p_idx, []).append(v.sentence)

    paragraphs = ["".join(kept_by_para[k]) for k in sorted(kept_by_para)]
    final_text = "\n".join(p for p in paragraphs if p) or REFUSAL_FINAL_TEXT
    removed = sum(1 for v in verdicts if not v.supported)
    return GroundingResult(text, final_text, verdicts, removed)


def log_grounding(
    log_path: Path, question: str, provider: str, result: GroundingResult
) -> None:
    """差異記錄，供事後稽核（logs/grounding/*.jsonl，不進 git）。"""
    import datetime

    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "provider": provider,
        "original_text": result.original_text,
        "final_text": result.final_text,
        "removed_count": result.removed_count,
        "verdicts": [
            {
                "sentence": v.sentence,
                "supported": v.supported,
                "article_no": v.article_no,
                "reason": v.reason,
            }
            for v in result.verdicts
        ],
    }
    with log_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
