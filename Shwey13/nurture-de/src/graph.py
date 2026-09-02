"""Phase 11 — the orchestration WORKFLOW (LangGraph). Not an agent: predefined code paths,
two routing branches, one bounded evaluator-optimizer loop (retry <= 2). See
knowledge/phase11-graph-decision.md for the workflow-vs-agent rationale (written before this code).

Reuses, does not reimplement: Retriever.search (+ Reranker, RERANK_POOL=100), tools.timeline,
the existing answer_system_prompt.md, and the Phase-5 RetrievalTrace (embedded in GraphTrace).

    from graph import run
    state = run("When does Mutterschutz start if I'm due 2027-03-15 and employed?")
    print(state["path"])          # the nodes visited, in order
    print(state["plan"])          # the FinalPlan (when the informational path completed)
"""

from __future__ import annotations

import json
import operator
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Optional, TypedDict

from pydantic import BaseModel
from langgraph.graph import StateGraph, START, END

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

# let `python src/graph.py` pick up the key from .env (same convention as ask.py / run_eval.py)
import os  # noqa: E402
if not os.environ.get("ANTHROPIC_API_KEY"):
    _envf = _ROOT / ".env"
    if _envf.exists():
        for _line in _envf.read_text(encoding="utf-8").splitlines():
            if _line.startswith("ANTHROPIC_API_KEY="):
                os.environ["ANTHROPIC_API_KEY"] = _line.split("=", 1)[1].strip()

import generate  # noqa: E402  (reuse: client, cost, system prompt, context assembly)
from retrieval import RetrievedChunk, RetrievalTrace, Reranker, RERANK_POOL  # noqa: E402
from tools.timeline import calculate_timeline  # noqa: E402  (Phase-9 deterministic tool)

JUDGE_MODEL = "claude-haiku-4-5"     # classify / grade / verify / rewrite / profile — cheap
GEN_MODEL = generate.MODEL           # claude-opus-5 — the plan
K_CONTEXT = 4
MAX_RETRIES = 2                      # hard cap on the evaluator-optimizer loop


# --- final schema (Pydantic) ----------------------------------------------------------------
class TimelineItem(BaseModel):
    event: str
    date: str
    rule: str
    source_chunk: str


class Citation(BaseModel):
    chunk_id: str
    authority: str
    authority_tier: str
    last_verified: str


class FinalPlan(BaseModel):
    summary: str
    timeline: list[TimelineItem]
    citations: list[Citation]
    information_date: str
    needs_professional_confirmation: list[str]


# --- graph state ----------------------------------------------------------------------------
class GraphState(TypedDict, total=False):
    question: str
    profile: dict                    # caller-supplied: employment_status, insurance_type, due_date
    intent: str
    complete: bool
    missing: list[str]
    query: str                       # current (possibly rewritten) retrieval query
    retry_count: int
    chunks: list                     # list[RetrievedChunk]
    evidence_sufficient: bool
    timeline: Optional[dict]
    plan: dict
    response: dict                   # terminal output for the referral / attributes branches
    path: Annotated[list[str], operator.add]
    cost: Annotated[float, operator.add]
    trace: "GraphTrace"


# --- trace (EXTENDS the Phase-5 RetrievalTrace by embedding it, not paralleling it) ----------
@dataclass
class GraphTrace:
    nodes: list[dict] = field(default_factory=list)      # [{node, branch?, detail?, ms?}]
    branch_intent: Optional[str] = None
    branch_profile: Optional[str] = None
    retries: int = 0
    retrievals: list[RetrievalTrace] = field(default_factory=list)   # one per retrieve attempt
    final_node: Optional[str] = None
    filter_starved: bool = False                         # a filtered search returned zero chunks
    node_timings: list[dict] = field(default_factory=list)   # [{node, ms}] in call order (Phase-11 instr.)

    def visit(self, node: str, **detail) -> None:
        self.nodes.append({"node": node, **detail})


# --- structured-output helper (reuses generate._client / _cost) -----------------------------
def _structured(model: str, system: str, user: str, schema: dict,
                max_tokens: int = 1500) -> tuple[dict, float]:
    resp = generate._client().messages.create(
        model=model, max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError(f"structured output truncated at max_tokens={max_tokens} "
                           f"(model={model}); raise the budget")
    return json.loads(text), generate._cost(resp.usage)


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": required}


# --- reranked retrieval (reuses Retriever.search + Reranker, fills the RetrievalTrace) -------
_reranker: Optional[Reranker] = None


def _retrieve_reranked(query: str, filters: dict | None) -> tuple[list[RetrievedChunk], RetrievalTrace]:
    global _reranker
    R = generate._get_retriever()
    pool_hits, tr = R.search(query, k=RERANK_POOL, filters=filters or None,
                             mode="hybrid", pool=RERANK_POOL, trace=True)
    if _reranker is None:
        _reranker = Reranker()
    reranked = _reranker.rerank(query, pool_hits)[:K_CONTEXT]
    chunks = [RetrievedChunk(h.chunk_id, h.text, float(h.score), h.metadata) for h in reranked]
    tr.rerank = [{"chunk_id": c.chunk_id, "score": round(c.score, 4)} for c in chunks]
    tr.final_context = [c.chunk_id for c in chunks]
    return chunks, tr


def _excerpts(chunks: list[RetrievedChunk], n: int = 500) -> str:
    out = []
    for c in chunks:
        m = c.metadata
        body = " ".join(c.text.split())
        out.append(f"[{c.chunk_id}] ({m.get('authority','?')}, {m.get('last_verified_date','?')})\n"
                   f"{body[:n]}")
    return "\n\n".join(out)


# --- nodes ----------------------------------------------------------------------------------
def classify_intent(state: GraphState) -> dict:
    tr: GraphTrace = state["trace"]
    schema = _obj({"intent": {"type": "string", "enum": ["medical", "informational"]},
                   "reason": {"type": "string"}}, ["intent", "reason"])
    system = ("Classify a question for a German pregnancy/benefits assistant. 'medical' = about "
              "symptoms, pain, bleeding, whether something is normal or an emergency, medication, "
              "or interpreting a test — anything a doctor or midwife must answer. 'informational' "
              "= about rules, benefits, deadlines, forms, processes, or administrative terms. When "
              "in doubt between the two, choose 'medical'.")
    data, cost = _structured(JUDGE_MODEL, system, state["question"], schema)
    tr.branch_intent = data["intent"]
    tr.visit("classify_intent", branch=data["intent"], detail=data.get("reason", "")[:120])
    return {"intent": data["intent"], "path": ["classify_intent"], "cost": cost}


def safe_referral(state: GraphState) -> dict:
    tr: GraphTrace = state["trace"]
    tr.final_node = "safe_referral"
    tr.visit("safe_referral")
    msg = ("That sounds like a medical question, and I'm not able to assess symptoms or how "
           "serious something is. Please contact your doctor or midwife (Hebamme) — and if it "
           "feels urgent, call 112. They can help you properly.")
    return {"response": {"kind": "safe_referral", "message": msg}, "path": ["safe_referral"]}


def check_profile_completeness(state: GraphState) -> dict:
    tr: GraphTrace = state["trace"]
    profile = state.get("profile") or {}
    schema = _obj({
        "complete": {"type": "boolean"},
        "missing": {"type": "array", "items": {"type": "string",
                    "enum": ["employment_status", "insurance_type"]}},
        "due_date": {"type": ["string", "null"]},
        "employment_status": {"type": ["string", "null"]},
        "insurance_type": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    }, ["complete", "missing", "due_date", "employment_status", "insurance_type", "reason"])
    system = (
        "For a German maternity-benefits assistant, decide whether a question can be answered "
        "accurately yet, and extract any attributes the user STATED. Ask for an attribute ONLY if "
        "the answer to THIS specific question genuinely changes with it — do not ask for anything "
        "the question does not actually depend on:\n"
        "- A question purely about the DATES / TIMING of Mutterschutz (when it starts or ends, "
        "deadlines, the Mutterschutzfrist) depends on the due date and employment status, but NOT "
        "on insurance type — the protection dates are the same for everyone.\n"
        "- A question about payment AMOUNTS or what a person will RECEIVE (Mutterschaftsgeld, the "
        "employer top-up) depends on employment status AND insurance type.\n"
        "employment values: employed / self-employed / student / civil-servant / marginally-"
        "employed. insurance values: statutory / private / family-insured. If answering needs an "
        "attribute the user has NOT given, set complete=false and list exactly that attribute in "
        "'missing'. Only extract due_date if the user explicitly stated one (ISO YYYY-MM-DD); "
        "never guess a date. Attributes already known: " + json.dumps(profile))
    data, cost = _structured(JUDGE_MODEL, system, state["question"], schema)
    # merge caller-supplied profile with what the model extracted from the question
    merged = dict(profile)
    for k in ("due_date", "employment_status", "insurance_type"):
        if data.get(k) and not merged.get(k):
            merged[k] = data[k]
    complete = bool(data["complete"]) and not data["missing"]
    tr.branch_profile = "complete" if complete else "missing"
    tr.visit("check_profile_completeness", branch=tr.branch_profile,
             detail=("missing " + ",".join(data["missing"])) if data["missing"] else "ok")
    return {"complete": complete, "missing": data["missing"], "profile": merged,
            "query": state["question"], "path": ["check_profile_completeness"], "cost": cost}


def request_attributes(state: GraphState) -> dict:
    tr: GraphTrace = state["trace"]
    tr.final_node = "request_attributes"
    tr.visit("request_attributes", detail=",".join(state.get("missing") or []))
    pretty = {"employment_status": "whether you're employed, self-employed, a student, a civil "
              "servant, or not currently employed",
              "insurance_type": "whether you have statutory or private health insurance"}
    asks = [pretty.get(m, m) for m in (state.get("missing") or [])]
    msg = ("To give you an answer that's actually right for your situation, I need to know "
           + " and ".join(asks) + ". Could you tell me?")
    return {"response": {"kind": "request_attributes", "message": msg,
            "missing": state.get("missing")}, "path": ["request_attributes"]}


# employment_status vocabulary (the timeline/profile vocab) -> corpus `user_type` facet vocabulary.
# These are DIFFERENT vocabularies: the corpus tags chunks 'employee', not 'employed'. A naive
# pass-through silently excluded every maternity-protection chunk (none are tagged 'any' on this
# facet), which starved retrieval of the exact rule chunk. Map explicitly; unmapped -> no filter.
_USER_TYPE = {"employed": "employee", "marginally-employed": "employee",
              "self-employed": "self-employed", "student": "student",
              "civil-servant": "civil-servant"}   # not-employed -> no user_type filter

# insurance_type: same lesson. check_profile_completeness can emit 'family-insured', but the corpus
# has no such facet value (its insurance_type vocab is any/statutory/non-statutory/private/none).
# Familienversicherung IS statutory cover (GKV, insured via a family member) — so it maps to
# 'statutory', not through. A naive pass-through of 'family-insured' would match nothing specific
# and silently drop every statutory/private chunk behind the `any` passthrough — the SAME bug the
# guard below now catches at startup. Map explicitly; unmapped -> no insurance filter.
_INSURANCE = {"statutory": "statutory", "private": "private", "family-insured": "statutory"}


def _filters_from(profile: dict) -> dict:
    f = {}
    ut = profile.get("user_type") or _USER_TYPE.get(profile.get("employment_status"))
    if ut:
        f["user_type"] = ut
    ins = _INSURANCE.get(profile.get("insurance_type"), profile.get("insurance_type"))
    if profile.get("insurance_type") and ins:
        f["insurance_type"] = ins
    return f


# --- filter-vocabulary guard ----------------------------------------------------------------
# Twice now (Phase 8 rank-6 discard, Phase 11 employed/employee) a filter value that matched
# NOTHING in the corpus starved retrieval silently, and the graph's honest degradation hid it —
# only the per-node trace revealed the bug. The lesson made durable: a filter value the code can
# emit that matches no chunk is a defect, and it should fail LOUDLY, not silently. Two guards:
#   1. assert_filter_vocab() — at build time, check every value the mapping tables can produce
#      against the actual corpus vocabulary. A code-level orphan (like 'employed', or the latent
#      'family-insured') raises here, caught by a developer / unit test, never a user.
#   2. the retrieve node warns loudly if a *filtered* search returns zero chunks at request time.
_CHUNKS_PATH = _ROOT / "data" / "chunks.jsonl"
_FACET_VOCAB: Optional[dict[str, set]] = None


def _corpus_facet_vocab(fields=("user_type", "insurance_type"),
                        path: Path | None = None) -> dict[str, set]:
    """The set of values each facet actually takes in the corpus (chunks.jsonl). Read once."""
    global _FACET_VOCAB
    if _FACET_VOCAB is not None and path is None:
        return _FACET_VOCAB
    vocab: dict[str, set] = {f: set() for f in fields}
    with open(path or _CHUNKS_PATH, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            d = json.loads(line)
            for f in fields:
                if d.get(f) is not None:
                    vocab[f].add(d[f])
    if path is None:
        _FACET_VOCAB = vocab
    return vocab


def assert_filter_vocab(path: Path | None = None) -> None:
    """Fail fast if any filter value the code can emit matches nothing in the corpus.

    `any` is the passthrough sentinel (ANY_PASSTHROUGH_FIELDS) — always eligible — so a mapped
    value is valid iff it appears in the corpus for that facet. Raises ValueError listing every
    orphan so the mismatch is fixed at startup, not discovered later as a silent recall hole."""
    vocab = _corpus_facet_vocab(path=path)
    emittable = {"user_type": set(_USER_TYPE.values()),
                 "insurance_type": set(_INSURANCE.values())}
    orphans = []
    for facet, values in emittable.items():
        corpus = vocab.get(facet, set())
        for v in sorted(values):
            if v not in corpus:
                orphans.append(f"{facet}={v!r} matches no chunk "
                               f"(corpus {facet} vocab: {sorted(corpus)})")
    if orphans:
        raise ValueError(
            "filter vocabulary out of sync with the corpus — these values would silently "
            "starve retrieval:\n  " + "\n  ".join(orphans))


def retrieve(state: GraphState) -> dict:
    tr: GraphTrace = state["trace"]
    filters = _filters_from(state.get("profile") or {})
    chunks, rtr = _retrieve_reranked(state["query"], filters)
    tr.retrievals.append(rtr)
    # A FILTERED search that returns zero chunks is — at this corpus size — almost always a
    # vocabulary mismatch, not a genuine absence. Warn loudly rather than let it look like a
    # graceful "no evidence" (the failure mode that hid the Phase-11 bug). The startup
    # assert_filter_vocab() catches code-level orphans; this catches request-time starvation.
    if filters and not chunks:
        tr.filter_starved = True
        print(f"[retrieve] WARNING: filtered search returned 0 chunks for filters={filters} "
              f"query={state['query']!r} — likely a vocabulary mismatch, not genuine absence.",
              file=sys.stderr)
    tr.visit("retrieve", detail=f"{len(chunks)} chunks (attempt {len(tr.retrievals)})")
    return {"chunks": chunks, "path": ["retrieve"]}


def grade_evidence(state: GraphState) -> dict:
    tr: GraphTrace = state["trace"]
    schema = _obj({"sufficient": {"type": "boolean"}, "reason": {"type": "string"}},
                  ["sufficient", "reason"])
    system = ("You judge whether retrieved excerpts are SUFFICIENT to answer a question from "
              "official German sources — not whether they are perfect. sufficient=true if the "
              "excerpts contain the facts needed to answer the substantive question. "
              "sufficient=false only if they are off-topic or miss the core of what was asked. "
              "One-sentence reason.")
    user = f"QUESTION:\n{state['question']}\n\nEXCERPTS:\n{_excerpts(state['chunks'])}"
    data, cost = _structured(JUDGE_MODEL, system, user, schema)
    tr.visit("grade_evidence", branch=("sufficient" if data["sufficient"] else "insufficient"),
             detail=data.get("reason", "")[:120])
    return {"evidence_sufficient": bool(data["sufficient"]), "path": ["grade_evidence"], "cost": cost}


def rewrite_query(state: GraphState) -> dict:
    tr: GraphTrace = state["trace"]
    n = state.get("retry_count", 0) + 1
    tr.retries = n
    schema = _obj({"rewritten_query": {"type": "string"}, "reason": {"type": "string"}},
                  ["rewritten_query", "reason"])
    system = ("Rewrite a search query to retrieve better from a corpus of German government and "
              "health-insurer pages about pregnancy, Mutterschutz, and family benefits. Add "
              "likely German terms and synonyms; keep it a search query, not a sentence.")
    user = f"Original question:\n{state['question']}\n\nPrevious query:\n{state['query']}"
    data, cost = _structured(JUDGE_MODEL, system, user, schema)
    tr.visit("rewrite_query", detail=f"retry {n}: {data['rewritten_query'][:80]}")
    return {"query": data["rewritten_query"], "retry_count": n,
            "path": ["rewrite_query"], "cost": cost}


def calculate_timeline_node(state: GraphState) -> dict:
    """Phase-9 tool — runs ONLY when a due date was actually supplied. Never invents one."""
    tr: GraphTrace = state["trace"]
    profile = state.get("profile") or {}
    due, emp = profile.get("due_date"), profile.get("employment_status")
    if not due or not emp:
        tr.visit("calculate_timeline", detail="skipped (no due date supplied)")
        return {"timeline": None, "path": ["calculate_timeline"]}
    try:
        tl = calculate_timeline(due, emp,
                                multiple_birth=bool(profile.get("multiple_birth")),
                                actual_birth_date=profile.get("actual_birth_date"))
        tr.visit("calculate_timeline", detail=f"{tl['protection_starts']} → {tl['protection_ends']}")
        return {"timeline": tl, "path": ["calculate_timeline"]}
    except ValueError as e:
        tr.visit("calculate_timeline", detail=f"invalid: {e}")
        return {"timeline": {"error": str(e)}, "path": ["calculate_timeline"]}


def generate_structured_plan(state: GraphState) -> dict:
    tr: GraphTrace = state["trace"]
    chunks: list[RetrievedChunk] = state["chunks"]
    context_block, _ = generate.assemble_context(chunks)
    timeline = state.get("timeline")
    schema = _obj({
        "summary": {"type": "string"},
        "cited_chunk_ids": {"type": "array", "items": {"type": "string"}},
        "needs_professional_confirmation": {"type": "array", "items": {"type": "string"}},
    }, ["summary", "cited_chunk_ids", "needs_professional_confirmation"])
    system = generate.load_system_prompt() + (
        "\n\n---\nYou are producing a STRUCTURED plan. Write `summary` as the grounded, cited "
        "answer in the user's language. In `cited_chunk_ids` list ONLY the exact document ids you "
        "relied on (from the provided documents). In `needs_professional_confirmation` name the "
        "authorities that decide what actually applies (employer, Krankenkasse, Elterngeldstelle, "
        "Personalstelle) — never state an amount or an eligibility verdict. Do not put dates in the "
        "summary that were not in the documents; the deterministic timeline is supplied separately.")
    # Inject the timeline WITHOUT chunk_ids: the model narrates the dates + rule wording but must
    # not present the timeline's source chunks as retrieved documents it can cite (their
    # provenance is carried deterministically in the structured `timeline[]`, added below).
    tl_note = ""
    if timeline and "error" not in timeline:
        tl_public = {k: timeline.get(k) for k in
                     ("expected_birth", "actual_birth", "protection_starts",
                      "protection_ends", "elterngeld_apply_by")}
        tl_public["rules"] = [r["rule"] for r in timeline.get("rules_applied", [])]
        tl_note = f"\n\n<computed_timeline>\n{json.dumps(tl_public)}\n</computed_timeline>"
    user = generate._build_user_message(state["question"], context_block) + tl_note
    data, cost = _structured(GEN_MODEL, system, user, schema, max_tokens=4096)

    # assemble the FinalPlan: prose + citations from the model, DATES from the deterministic tool
    ctx_by_id = {c.chunk_id: c for c in chunks}
    citations = []
    for cid in dict.fromkeys(data.get("cited_chunk_ids", [])):
        c = ctx_by_id.get(cid)
        if c:                                    # can only cite what was actually retrieved
            m = c.metadata
            citations.append(Citation(chunk_id=cid, authority=m.get("authority", "?"),
                                      authority_tier=m.get("authority_tier", "?"),
                                      last_verified=m.get("last_verified_date", "?")))
    timeline_items: list[TimelineItem] = []
    if timeline and "error" not in timeline:
        rule_by = {r["rule"].split(".")[0]: r for r in timeline.get("rules_applied", [])}
        starts_rule = next((r for r in timeline["rules_applied"] if "begins" in r["rule"]), None)
        ends_rule = next((r for r in timeline["rules_applied"] if "after birth" in r["rule"]), None)
        elt_rule = next((r for r in timeline["rules_applied"] if "Elterngeld" in r["rule"]), None)
        for event, date, rl in (("protection_starts", timeline["protection_starts"], starts_rule),
                                ("protection_ends", timeline["protection_ends"], ends_rule),
                                ("elterngeld_apply_by", timeline["elterngeld_apply_by"], elt_rule)):
            timeline_items.append(TimelineItem(event=event, date=date,
                rule=(rl["rule"] if rl else ""), source_chunk=(rl["source_chunk"] if rl else "")))
    info_date = max([c.last_verified for c in citations] or ["unknown"])
    plan = FinalPlan(summary=data["summary"], timeline=timeline_items, citations=citations,
                     information_date=info_date,
                     needs_professional_confirmation=data.get("needs_professional_confirmation", []))
    tr.visit("generate_structured_plan", detail=f"{len(citations)} citations, {len(timeline_items)} dates")
    return {"plan": plan.model_dump(), "path": ["generate_structured_plan"], "cost": cost}


def verify_citations(state: GraphState) -> dict:
    tr: GraphTrace = state["trace"]
    tr.final_node = "verify_citations"
    plan = state["plan"]
    chunks: list[RetrievedChunk] = state["chunks"]
    ctx_by_id = {c.chunk_id: c for c in chunks}
    schema = _obj({"all_supported": {"type": "boolean"},
                   "issues": {"type": "array", "items": _obj(
                       {"claim": {"type": "string"}, "cited_id": {"type": "string"},
                        "reason": {"type": "string"}}, ["claim", "cited_id", "reason"])}},
                  ["all_supported", "issues"])
    docs = "\n\n".join(f"[{cid}]\n{ctx_by_id[cid].text}" for cid in
                       [c["chunk_id"] for c in plan["citations"]] if cid in ctx_by_id)
    system = ("Verify citation faithfulness. For each substantive claim in the SUMMARY that is "
              "attributed to a cited document, decide whether that document actually supports it "
              "(not merely same-topic). Return all_supported and a list of any unsupported claims "
              "with the cited_id and a one-line reason.")
    user = f"SUMMARY:\n{plan['summary']}\n\nCITED DOCUMENTS:\n{docs}"
    data, cost = _structured(JUDGE_MODEL, system, user, schema)
    tr.visit("verify_citations", branch=("all_supported" if data["all_supported"] else "issues"),
             detail=f"{len(data.get('issues', []))} issue(s)")
    return {"response": {"kind": "plan", "plan": plan,
            "citations_verified": bool(data["all_supported"]), "issues": data.get("issues", [])},
            "path": ["verify_citations"], "cost": cost}


# --- routing functions ----------------------------------------------------------------------
def _route_intent(state: GraphState) -> str:
    return "medical" if state["intent"] == "medical" else "informational"


def _route_profile(state: GraphState) -> str:
    return "complete" if state.get("complete") else "missing"


def _route_evidence(state: GraphState) -> str:
    if not state.get("evidence_sufficient") and state.get("retry_count", 0) < MAX_RETRIES:
        return "insufficient"
    return "sufficient"


# --- per-node wall-clock instrumentation (Phase-11 spec) ------------------------------------
# Wraps each node to record its wall-clock ms on the trace. Measures the WHOLE node (model call
# included), which is what user-perceived latency is made of. Zero coupling to node bodies: nodes
# stay pure state->dict functions; the wrapper only reads state["trace"] and appends a timing.
def _timed(name: str, fn):
    def wrapped(state: GraphState) -> dict:
        t0 = time.perf_counter()
        out = fn(state)
        ms = (time.perf_counter() - t0) * 1000.0
        tr = state.get("trace")
        if tr is not None:
            tr.node_timings.append({"node": name, "ms": round(ms, 1)})
            if tr.nodes and tr.nodes[-1].get("node") == name:   # each node visits exactly once
                tr.nodes[-1]["ms"] = round(ms, 1)
        return out
    return wrapped


# --- build ----------------------------------------------------------------------------------
def build_graph():
    assert_filter_vocab()   # fail fast: no filter value the code emits may match zero chunks
    g = StateGraph(GraphState)
    g.add_node("classify_intent", _timed("classify_intent", classify_intent))
    g.add_node("safe_referral", _timed("safe_referral", safe_referral))
    g.add_node("check_profile_completeness", _timed("check_profile_completeness", check_profile_completeness))
    g.add_node("request_attributes", _timed("request_attributes", request_attributes))
    g.add_node("retrieve", _timed("retrieve", retrieve))
    g.add_node("grade_evidence", _timed("grade_evidence", grade_evidence))
    g.add_node("rewrite_query", _timed("rewrite_query", rewrite_query))
    g.add_node("calculate_timeline", _timed("calculate_timeline", calculate_timeline_node))
    g.add_node("generate_structured_plan", _timed("generate_structured_plan", generate_structured_plan))
    g.add_node("verify_citations", _timed("verify_citations", verify_citations))

    g.add_edge(START, "classify_intent")
    g.add_conditional_edges("classify_intent", _route_intent,
                            {"medical": "safe_referral", "informational": "check_profile_completeness"})
    g.add_edge("safe_referral", END)
    g.add_conditional_edges("check_profile_completeness", _route_profile,
                            {"missing": "request_attributes", "complete": "retrieve"})
    g.add_edge("request_attributes", END)
    g.add_edge("retrieve", "grade_evidence")
    g.add_conditional_edges("grade_evidence", _route_evidence,
                            {"insufficient": "rewrite_query", "sufficient": "calculate_timeline"})
    g.add_edge("rewrite_query", "retrieve")
    g.add_edge("calculate_timeline", "generate_structured_plan")
    g.add_edge("generate_structured_plan", "verify_citations")
    g.add_edge("verify_citations", END)
    return g.compile()


_GRAPH = None


def run(question: str, profile: dict | None = None) -> dict:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    init: GraphState = {"question": question, "profile": profile or {}, "query": question,
                        "retry_count": 0, "path": [], "cost": 0.0, "trace": GraphTrace()}
    return _GRAPH.invoke(init)


def print_trace(s: dict) -> None:
    tr: GraphTrace = s["trace"]
    print("PATH:", " → ".join(s["path"]))
    print("\nDECISIONS:")
    for n in tr.nodes:
        bits = []
        if n.get("branch"):
            bits.append(f"[{n['branch']}]")
        if n.get("detail"):
            bits.append(str(n["detail"]))
        ms = f"{n['ms']:>8.1f} ms" if n.get("ms") is not None else " " * 11
        print(f"  {ms}  {n['node']:28} {' '.join(bits)}")
    if tr.retrievals:
        print(f"\nRETRIEVAL ATTEMPTS: {len(tr.retrievals)} (retries={tr.retries})")
        for i, rt in enumerate(tr.retrievals, 1):
            print(f"  attempt {i} query={rt.query!r}")
            print(f"    top-{len(rt.final_context)}: {rt.final_context}")
    total_ms = sum(t["ms"] for t in tr.node_timings)
    if total_ms:
        gen = sum(t["ms"] for t in tr.node_timings if t["node"] == "generate_structured_plan")
        print(f"\nWALL-CLOCK: {total_ms:,.0f} ms total across {len(tr.node_timings)} node calls"
              + (f"  |  generation {gen:,.0f} ms = {gen / total_ms:.0%} of it" if gen else ""))
    if tr.filter_starved:
        print("  ⚠ filter_starved: a filtered retrieval returned zero chunks (see stderr)")
    print(f"\nfinal_node={tr.final_node}  cost=${s.get('cost', 0):.4f}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    q = " ".join(sys.argv[1:]) or "When does Mutterschutz start if I'm due 2027-03-15 and employed?"
    s = run(q)
    print_trace(s)
    print("\nRESPONSE:")
    print(json.dumps(s.get("response", {}), ensure_ascii=False, indent=2, default=str)[:1800])
