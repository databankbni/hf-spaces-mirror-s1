"""結構化查詢路由（query router）：彙總型問題不走 RAG，直接查 laws.json。

背景（Phase 6 作者實測發現）：「請列出長期照顧服務法的每一條」這類
**整部法規彙總問題**天生不適合 top-k 檢索——系統一次只看得到 5 條，
生成端只能把零碎檢索結果湊成順序混亂、甚至混入他法條文的清單。
但語料庫本身就有全部 205 條的結構化資料（含章節），這類問題應該
繞過 RAG 直接以確定性模板回答：零幻覺、零成本、各 provider 行為一致。

範圍刻意收窄：只攔「明確指名某部法 + 整部列舉意圖」的問題；
單一條文查詢（「長照法第10條是什麼」）與一般主題問題仍走 RAG 管線。

第二種路由：**meta 問題**（問系統本身，例如「可以問你哪些法規問題」），
同一份根因——作者實測發現這類問題連續 3 次讓 query 改寫模型把「問系統
範圍」誤判成「需要改寫成法規查詢用語」，改寫模型因此**憑空捏造**出一個
具體法律問題（如「1. 失能老人聘僱外籍看護的補助額度為何？」），檢索抓到
不相關條文，生成端再被帶偏、退化成列一串假設性問題清單而非回答。三次
重現皆一致，是系統性失效模式，不是隨機抽風。同樣繞過 RAG，直接回固定、
誠實的系統範圍說明。

第三種路由：**全局/跨章節問題**（問某部法整體規範什麼、兩部法的差異、
全法規最高罰則等），這類問題單一問題無法用 top-5 檢索回答，直覺解法是
把整部法全文塞進 context，但作者實測（PROGRESS 有完整記錄）發現這對
地端 12B **不安全**——生成端會編造內容（把不存在的段落講得煞有介事），
且 Phase 3 的逐句查核機制在核對 72 條參考資料時也失守（把捏造內容誤判
為支持）。根因是「一次核對的參考資料數量」超出地端 12B 的可靠規模。

解法（RAPTOR-lite，D13）：改用 `scripts/build_chapter_summaries.py` 預先
生成的**章節摘要**（`data/chapter_summaries.json`）當 context，规模回到
Phase 3 已驗證可靠的區間（一部法最多 7 段摘要，而非 72 條全文）。引用
格式改用章節層級 `[法規名 章節]`（非逐條 `§`，避免摘要衍生資料被誤認為
逐條精確查核）。**v1 刻意不重跑完整 CRAG 逐句查核**（摘要本身不是
`RetrievedChunk`，套用需要改造 grounding.py 核心函式，風險與本次工作量
不成比例）；改用較輕量的確定性防線：`verify_chapter_citations()` 逐段
檢查引用的章節是否真的在餵給模型的 context 範圍內，不在範圍內就整段
移除（寧可誤刪不可放行捏造，與拒答門檻同一原則）。完整 CRAG 整合記入
未來工作。
"""

from __future__ import annotations

import json
import re

from .config import DATA_DIR
from .knowledge_base import active_laws_path

# 法規名稱與常見簡稱 → pcode（僅本語料庫五法；他法簡稱不收，讓其落入拒答門檻）
LAW_ALIASES: dict[str, str] = {
    "長期照顧服務法施行細則": "L0070043",
    "長照服務法施行細則": "L0070043",
    "長照法施行細則": "L0070043",
    "長期照顧服務機構設立許可及管理辦法": "L0070044",
    "設立許可及管理辦法": "L0070044",
    "長期照顧服務申請及給付辦法": "L0070059",
    "申請及給付辦法": "L0070059",
    "長期照顧服務法": "L0070040",
    "長照服務法": "L0070040",
    "長照法": "L0070040",
    "老人福利法": "D0050037",
    "老福法": "D0050037",
}

# 整部列舉意圖：必須同時命中法規名（上表）與這組關鍵詞其一才觸發
# 注意：「整部」不放在這裡——「整部法規大概在講什麼」是全局摘要意圖
# （_GLOBAL_RE），不是逐條列舉意圖，兩者用詞需要區分不能共用
_ENUM_RE = re.compile(
    r"每一條|每條|所有條文|全部條文|全部的條文|條文列表|逐條列出|列出.{0,6}條文|"
    r"有(哪些|幾)條|共(有)?幾條|總共幾條|目錄|條文總覽"
)


def detect_enumeration_query(question: str) -> str | None:
    """偵測「整部法規列舉」問題。回傳命中的 pcode，未命中回 None。

    法規名取最長匹配（「長期照顧服務法施行細則」不可誤配到字首的
    「長期照顧服務法」——比對序已按名稱長度排列）。
    """
    if not _ENUM_RE.search(question):
        return None
    for name in sorted(LAW_ALIASES, key=len, reverse=True):
        if name in question:
            return LAW_ALIASES[name]
    return None


# meta 問題：問系統本身的範圍/身分/能力，不是實質法規問題。
# 必須指向「你/這系統」本身，避免誤觸「我可以申請什麼補助」這類真實問題
# （那句沒有「問你」「你能」「這系統」等自指詞，不會誤觸）。
_META_RE = re.compile(
    r"問你|你能(回答|做|處理)|你可以(回答|做|處理)|你是誰|你叫什麼|"
    r"你是什麼|這(個|套)(系統|工具|服務|機器人|助手|網站|平台)|"
    r"(你的|系統的|工具的)(功能|用途|能力|範圍)"
)

META_RESPONSE = (
    "我是台灣長照法規諮詢助手，目前可以回答《長期照顧服務法》《老人福利法》"
    "及其三部子法（長期照顧服務法施行細則、長期照顧服務機構設立許可及管理"
    "辦法、長期照顧服務申請及給付辦法）相關的問題，例如長照服務申請資格、"
    "機構設立許可、補助項目與計算方式等。\n\n"
    "我只依這五部法規的條文回答，查不到明確法源時會誠實告知「查無明確法源」，"
    "不會編造內容，也無法回答稅務、繼承、勞保、健保等其他法規領域的問題。"
)


def detect_meta_query(question: str) -> bool:
    """偵測「問系統本身」的 meta 問題（見模組 docstring 的根因說明）。"""
    return bool(_META_RE.search(question))


# 全局/跨章節意圖：問「整體規範什麼」「差異/比較」「最高/最重」等，
# 需要指名至少一部法規（見下方 detect_global_question 的別名比對）才觸發。
# 刻意與 _ENUM_RE／_META_RE 用詞不重疊。
_GLOBAL_RE = re.compile(
    r"整體|整部.{0,4}(規範|規定|在(講|說|管))|大致(規範|規定)|主要規範|主要規定|"
    r"規範(什麼|哪些|的重點)|規定(什麼|哪些)(內容|事項)?|重點是什麼|"
    r"差別|差異|不同之處|比較|哪個.{0,4}(嚴重|重)|"
    r"最高|最重|最少|最輕"
)

CHAPTER_SUMMARY_PATH = DATA_DIR / "chapter_summaries.json"

_CHAPTER_CITATION_RE = re.compile(
    r"\[([^\[\]]+?)\s+(第[一二三四五六七八九十百]+章[^\[\]]*?|全文)\]"
)

GLOBAL_SYSTEM_PROMPT = (
    "你是台灣長期照顧法規諮詢助手。以下是法規的「章節摘要」（不是逐條全文），"
    "每段摘要標示所屬法規、章節與涵蓋條號範圍。回答規則：\n"
    "1. 僅依下方章節摘要回答問題，不得使用其他知識、不得編造內容。\n"
    "2. 每個論述句的句尾必須標注來源，格式為 [法規名 章節]（章節請完整照抄"
    "下方摘要標示的章節名稱，例如 [長期照顧服務法 第六章罰則]；未分章的法規"
    "寫 [法規名 全文]），不要自己編造章節名稱或條號。\n"
    "3. 若摘要不足以回答問題，直接說明「查無明確法源」。\n"
    "4. 用繁體中文、平易近人的語氣回答，內容必須嚴格對應摘要。"
)


def detect_global_question(question: str) -> list[str] | None:
    """偵測「全局/跨章節」問題，回傳問題中命中的法規 pcode 清單
    （可能 1 或 2 部，用於單一法規總覽或跨法規比較）；未命中回 None。

    法規名比對後從剩餘文字中移除已匹配片段，避免長別名內含的短別名
    重複計數（不影響去重後的 pcode 清單本身）。
    """
    if not _GLOBAL_RE.search(question):
        return None
    pcodes: list[str] = []
    remaining = question
    for name in sorted(LAW_ALIASES, key=len, reverse=True):
        if name in remaining:
            pcode = LAW_ALIASES[name]
            if pcode not in pcodes:
                pcodes.append(pcode)
            remaining = remaining.replace(name, "")
    return pcodes or None


def load_chapter_summaries(pcodes: list[str]) -> list[dict]:
    data = json.loads(CHAPTER_SUMMARY_PATH.read_text(encoding="utf-8"))
    laws = json.loads(active_laws_path().read_text(encoding="utf-8"))
    law_names = {m["pcode"]: m["law_name"] for m in laws["meta"]["laws"]}
    out = []
    for pcode in pcodes:
        for ch in data.get(pcode, []):
            out.append({"pcode": pcode, "law_name": law_names[pcode], **ch})
    return out


def build_global_context(chapters: list[dict]) -> str:
    return "\n\n".join(
        f"《{c['law_name']}》{c['chapter']}（第{c['article_lo']}〜{c['article_hi']}條）：\n"
        f"{c['summary']}"
        for c in chapters
    )


def verify_chapter_citations(text: str, chapters: list[dict]) -> tuple[str, int]:
    """逐段檢查章節引用是否在提供的章節範圍內，不在範圍內的整段移除
    （寧可誤刪不可放行捏造，與拒答門檻同一原則；v1 用段落而非逐句，
    完整 CRAG 整合記入未來工作，見模組 docstring）。回傳 (清理後文字, 移除段數)。
    """
    valid = {(c["law_name"], c["chapter"]) for c in chapters}
    valid |= {(c["law_name"], "全文") for c in chapters}  # 未分章時的寫法
    paragraphs = [p for p in text.replace("\r\n", "\n").split("\n") if p.strip()]

    kept: list[str] = []
    removed = 0
    for para in paragraphs:
        citations = _CHAPTER_CITATION_RE.findall(para)
        bad = [c for c in citations if c not in valid]
        if bad:
            removed += 1
            continue
        kept.append(para)
    return "\n".join(kept), removed


def answer_global_question(
    question: str, pcodes: list[str], model, on_response=None
) -> tuple[str, int]:
    """回傳 (回答文字, 移除段數)。章節摘要規模小（一部法最多 7 段），
    落在 Phase 3 已驗證地端模型可靠的規模。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from .llm_text import extract_text

    chapters = load_chapter_summaries(pcodes)
    if not chapters:
        return "查無明確法源。建議撥打 1966 長照服務專線洽詢。", 0

    context = build_global_context(chapters)
    messages = [
        SystemMessage(content=GLOBAL_SYSTEM_PROMPT),
        HumanMessage(content=f"章節摘要：\n\n{context}\n\n---\n問題：{question}"),
    ]
    reply = model.invoke(messages)
    if on_response is not None:
        on_response("global_generation", reply)
    text = extract_text(reply.content).strip()
    cleaned, removed = verify_chapter_citations(text, chapters)
    if not cleaned.strip():
        return "查無明確法源。建議撥打 1966 長照服務專線洽詢。", removed
    return cleaned, removed


def _roc_date(yyyymmdd: str) -> str:
    if len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return yyyymmdd
    return f"民國 {int(yyyymmdd[:4]) - 1911} 年 {int(yyyymmdd[4:6])} 月 {int(yyyymmdd[6:8])} 日"


def build_law_overview(pcode: str) -> str:
    """整部法規的確定性目錄：章節結構＋每章條號＋官方全文連結。"""
    data = json.loads(active_laws_path().read_text(encoding="utf-8"))
    meta = next(m for m in data["meta"]["laws"] if m["pcode"] == pcode)
    articles = [a for a in data["articles"] if a["pcode"] == pcode]

    lines = [
        f"《{meta['law_name']}》全文共 {len(articles)} 條"
        f"（最近修正：{_roc_date(meta['law_modified_date'])}）。",
        "",
    ]

    chapters: dict[str, list[str]] = {}
    for a in articles:
        ch = a.get("chapter") or ""
        chapters.setdefault(ch, []).append(a["article_no"])

    if len(chapters) > 1 or (len(chapters) == 1 and "" not in chapters):
        lines.append("章節結構：")
        for ch, nos in chapters.items():
            label = re.sub(r"\s+", "", ch) if ch else "（未分章）"
            lines.append(f"・{label}：第 {nos[0]}〜{nos[-1]} 條（共 {len(nos)} 條）")
    else:
        nos = chapters.get("", [])
        lines.append(f"本法未分章，條號為第 {nos[0]}〜{nos[-1]} 條。")

    lines += [
        "",
        "逐條全文請見全國法規資料庫（官方版本）：",
        f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}",
        "",
        "本工具的問答功能適合針對特定主題提問（例如「開一家日照中心要什麼許可」），"
        "會檢索最相關的條文並附出處；整部法規的逐條內容以上方官方連結為準。",
    ]
    return "\n".join(lines)
