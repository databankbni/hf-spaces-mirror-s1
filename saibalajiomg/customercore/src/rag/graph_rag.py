"""
src/rag/graph_rag.py

Phase 8b: Unified B2B Graph-RAG Engine

== Why Graph-RAG Beats Pure Vector RAG for B2B ==

Pure vector RAG answers "find me tickets similar to this one."
That works for simple FAQ-style queries but breaks for B2B intelligence:

  Q: "Why has acme-corp been escalating so often this quarter?"
  Pure vector: Returns similar escalation tickets — no context.
  Graph-RAG:   Returns similar tickets + tenant health score + category
               breakdown from DuckDB Gold + escalation trend from time series.
               The LLM gets BOTH the examples AND the structured analytics.

B2B support platforms are fundamentally relational: tenants have accounts,
accounts have tiers, tiers have SLAs, SLAs have breach patterns. Vector
search alone misses all of this. Graph-RAG bridges the gap by combining:

  Layer 1 (Graph)    — B2BKnowledgeGraph: NetworkX DiGraph connecting
                        Tickets → Tenants → Categories → Metrics
  Layer 2 (Vector)   — HybridRetriever: BM25 + ChromaDB dense search
  Layer 3 (SQL)      — DuckDB queries against Gold mart Parquet files

== Architecture ==

    Query: "Why is acme-corp escalating this month?"
      │
      ├── [Vector]  HybridRetriever.search(tenant_id="acme-corp", query=...)
      │    └── Returns: 5 most similar past escalation tickets
      │
      ├── [Graph]   B2BKnowledgeGraph.get_tenant_context("acme-corp")
      │    └── Returns: total tickets, top categories, priority breakdown
      │
      └── [SQL]     DuckDB → Gold mart → support_agent_performance + ticket_funnel
           └── Returns: volume trend, resolution rate, avg priority

      ↓
    GraphRAGEngine._format_combined_context(...)
      └── Produces: structured prompt context for the LLM

Run demo:
  python -m src.rag.graph_rag
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Node Dataclasses ───────────────────────────────────────────────────────────

@dataclass
class TicketNode:
    ticket_id: str
    tenant_id: str
    text: str
    category: str
    priority: str
    language: str = "en"
    created_at: str = ""


@dataclass
class TenantNode:
    tenant_id: str
    tier: str = "professional"
    metrics: dict = field(default_factory=dict)


@dataclass
class CategoryNode:
    category: str
    ticket_count: int = 0


@dataclass
class GraphRAGResult:
    """Full result from a Graph-RAG query."""
    query: str
    tenant_id: str
    similar_tickets: list        # list[RetrievedDoc]
    tenant_context: dict
    sql_insights: list[dict]
    combined_context: str
    query_plan: list[str]        # steps taken — for explainability/debugging


# ── B2B Knowledge Graph ────────────────────────────────────────────────────────

class B2BKnowledgeGraph:
    """
    In-memory knowledge graph for B2B customer intelligence.

    Nodes:
      - tenant:{tenant_id}    — B2B customer tenant
      - ticket:{ticket_id}    — support ticket
      - category:{name}       — support category (billing, technical, etc.)

    Edges:
      - (tenant) --[HAS_TICKET]--> (ticket)
      - (ticket) --[BELONGS_TO]--> (category)
      - (ticket) --[SIMILAR_TO]--> (ticket)   ← added by RAG engine after retrieval

    Usage:
        graph = B2BKnowledgeGraph()
        graph.add_ticket("acme-corp", "TKT-001", "API error on checkout",
                         category="technical", priority="high", language="en")
        context = graph.get_tenant_context("acme-corp")
    """

    def __init__(self):
        try:
            import networkx as nx
            self._graph = nx.DiGraph()
        except ImportError:
            logger.warning("networkx not installed — using dict-based fallback graph")
            self._graph = None

        # Fallback storage (always populated, networkx is additive)
        self._tenants: dict[str, TenantNode] = {}
        self._tickets: dict[str, TicketNode] = {}
        self._categories: dict[str, CategoryNode] = {}
        self._tenant_tickets: dict[str, list[str]] = defaultdict(list)
        self._ticket_category: dict[str, str] = {}

    def add_ticket(
        self,
        tenant_id: str,
        ticket_id: str,
        text: str,
        category: str = "general",
        priority: str = "medium",
        language: str = "en",
        created_at: str = "",
    ):
        """Add a ticket node and connect it to tenant and category nodes."""
        # Create nodes
        ticket = TicketNode(
            ticket_id=ticket_id, tenant_id=tenant_id, text=text,
            category=category, priority=priority, language=language,
            created_at=created_at,
        )
        self._tickets[ticket_id] = ticket
        self._ticket_category[ticket_id] = category

        if tenant_id not in self._tenants:
            self._tenants[tenant_id] = TenantNode(tenant_id=tenant_id)

        if category not in self._categories:
            self._categories[category] = CategoryNode(category=category)
        self._categories[category].ticket_count += 1
        self._tenant_tickets[tenant_id].append(ticket_id)

        # NetworkX graph
        if self._graph is not None:
            self._graph.add_node(f"ticket:{ticket_id}", **ticket.__dict__)
            self._graph.add_node(f"tenant:{tenant_id}")
            self._graph.add_node(f"category:{category}")
            self._graph.add_edge(f"tenant:{tenant_id}", f"ticket:{ticket_id}",
                                 rel="HAS_TICKET")
            self._graph.add_edge(f"ticket:{ticket_id}", f"category:{category}",
                                 rel="BELONGS_TO", priority=priority)

    def add_tenant_metrics(self, tenant_id: str, metrics: dict):
        """Update a tenant node with structured metrics from the Gold layer."""
        if tenant_id not in self._tenants:
            self._tenants[tenant_id] = TenantNode(tenant_id=tenant_id)
        self._tenants[tenant_id].metrics = metrics

        if self._graph is not None:
            self._graph.add_node(f"tenant:{tenant_id}", **metrics)

    def get_tenant_context(self, tenant_id: str) -> dict:
        """
        Build a structured context dict for a tenant from the graph.
        Includes ticket volume, category breakdown, priority distribution,
        language breakdown, and any stored metrics.
        """
        ticket_ids = self._tenant_tickets.get(tenant_id, [])
        tickets = [self._tickets[tid] for tid in ticket_ids if tid in self._tickets]

        if not tickets:
            return {
                "tenant_id": tenant_id,
                "total_tickets": 0,
                "message": "No tickets found in graph for this tenant.",
            }

        # Category breakdown
        category_counts: dict[str, int] = defaultdict(int)
        priority_counts: dict[str, int] = defaultdict(int)
        language_counts: dict[str, int] = defaultdict(int)

        for t in tickets:
            category_counts[t.category] += 1
            priority_counts[t.priority] += 1
            language_counts[t.language] += 1

        top_categories = sorted(
            category_counts.items(), key=lambda x: x[1], reverse=True
        )[:5]

        # Escalation proxy: high + critical tickets as % of total
        escalation_count = (
            priority_counts.get("high", 0) + priority_counts.get("critical", 0)
        )
        escalation_rate = round(escalation_count / len(tickets) * 100, 1)

        tenant_node = self._tenants.get(tenant_id, TenantNode(tenant_id))

        return {
            "tenant_id": tenant_id,
            "tier": tenant_node.tier,
            "total_tickets": len(tickets),
            "top_categories": [
                {"category": cat, "count": cnt} for cat, cnt in top_categories
            ],
            "priority_breakdown": dict(priority_counts),
            "language_breakdown": dict(language_counts),
            "escalation_rate_pct": escalation_rate,
            "escalation_count": escalation_count,
            "gold_metrics": tenant_node.metrics,
        }

    def find_similar_tenants(
        self, tenant_id: str, by: str = "category", top_k: int = 3
    ) -> list[dict]:
        """
        Find tenants with similar issue profiles based on category distribution.
        Useful for benchmarking: "how does acme-corp compare to similar tenants?"
        """
        target_cats = set(
            self._tickets[tid].category
            for tid in self._tenant_tickets.get(tenant_id, [])
            if tid in self._tickets
        )

        scores = []
        for other_id, ticket_ids in self._tenant_tickets.items():
            if other_id == tenant_id:
                continue
            other_cats = set(
                self._tickets[tid].category
                for tid in ticket_ids if tid in self._tickets
            )
            # Jaccard similarity
            if target_cats or other_cats:
                overlap = len(target_cats & other_cats)
                union = len(target_cats | other_cats)
                similarity = overlap / union if union > 0 else 0.0
                scores.append({"tenant_id": other_id, "similarity": round(similarity, 3)})

        return sorted(scores, key=lambda x: x["similarity"], reverse=True)[:top_k]

    def get_category_trends(self) -> dict[str, int]:
        """Return ticket count per category across all tenants."""
        return {cat: node.ticket_count for cat, node in self._categories.items()}

    def node_count(self) -> int:
        if self._graph is not None:
            return self._graph.number_of_nodes()
        return len(self._tickets) + len(self._tenants) + len(self._categories)

    def edge_count(self) -> int:
        if self._graph is not None:
            return self._graph.number_of_edges()
        return len(self._tickets) * 2  # each ticket has 2 edges


# ── SQL Insights (DuckDB Gold Layer) ──────────────────────────────────────────

def _load_duckdb_insights(tenant_id: str, gold_db_path: str = "data/gold/customercore_gold.duckdb") -> list[dict]:
    """
    Query the DuckDB Gold layer for structured analytics about a tenant.
    Returns empty list gracefully if the DB doesn't exist (local dev mode).
    """
    insights = []
    try:
        import duckdb
        conn = duckdb.connect(gold_db_path, read_only=True)

        # Ticket funnel for this tenant
        try:
            rows = conn.execute("""
                SELECT event_type, COUNT(*) as count, AVG(priority_score) as avg_priority
                FROM gold_gold.ticket_funnel_daily
                WHERE tenant_id = ?
                GROUP BY event_type
                ORDER BY count DESC
                LIMIT 5
            """, [tenant_id]).fetchall()
            for r in rows:
                insights.append({
                    "source": "ticket_funnel",
                    "event_type": r[0],
                    "count": r[1],
                    "avg_priority": round(r[2] or 0, 2),
                })
        except Exception:
            pass

        # Customer health
        try:
            rows = conn.execute("""
                SELECT snapshot_date, avg_priority, ticket_count
                FROM gold_gold.customer_health_daily
                WHERE tenant_id = ?
                ORDER BY snapshot_date DESC
                LIMIT 3
            """, [tenant_id]).fetchall()
            for r in rows:
                insights.append({
                    "source": "customer_health",
                    "date": str(r[0]),
                    "avg_priority": round(float(r[1] or 0), 2),
                    "ticket_count": r[2],
                })
        except Exception:
            pass

        conn.close()

    except Exception as e:
        logger.debug("DuckDB Gold layer not available: %s", e)

    return insights


# ── Graph-RAG Engine ───────────────────────────────────────────────────────────

class GraphRAGEngine:
    """
    Unified B2B Graph-RAG Query Engine.

    Combines three retrieval strategies in a single query:
      1. Vector + BM25 hybrid search (tenant-isolated, Phase 6)
      2. Graph traversal for tenant context and category trends
      3. SQL analytics from DuckDB Gold marts

    The resulting combined_context is ready for injection into any LLM prompt.

    Usage:
        engine = GraphRAGEngine(retriever=hybrid_retriever, graph=knowledge_graph)
        result = engine.query(
            tenant_id="acme-corp",
            question="Why has this tenant been escalating so often this quarter?",
            k=5
        )
        # Inject result.combined_context into your LLM prompt
    """

    def __init__(
        self,
        retriever=None,       # HybridRetriever instance (or None for graph-only)
        graph: Optional[B2BKnowledgeGraph] = None,
        gold_db_path: str = "data/gold/customercore_gold.duckdb",
    ):
        self.retriever = retriever
        self.graph = graph or B2BKnowledgeGraph()
        self.gold_db_path = gold_db_path

    def index_ticket(
        self,
        tenant_id: str,
        ticket_id: str,
        text: str,
        metadata: dict | None = None,
    ):
        """
        Index a ticket into both the vector retriever and the knowledge graph.
        Single entry point — no need to call retriever and graph separately.
        """
        metadata = metadata or {}
        category = metadata.get("category", "general")
        priority = metadata.get("priority", "medium")
        language = metadata.get("language", "en")

        # Add to graph
        self.graph.add_ticket(
            tenant_id=tenant_id,
            ticket_id=ticket_id,
            text=text,
            category=category,
            priority=priority,
            language=language,
        )

        # Add to vector retriever if available
        if self.retriever is not None:
            self.retriever.index_ticket(tenant_id, ticket_id, text, metadata)

    def query(
        self,
        tenant_id: str,
        question: str,
        k: int = 5,
        include_sql: bool = True,
    ) -> GraphRAGResult:
        """
        Full Graph-RAG query.

        Steps (all recorded in query_plan for explainability):
          1. Vector+BM25 hybrid retrieval (tenant-isolated)
          2. Graph traversal for tenant context
          3. SQL analytics from DuckDB Gold (optional)
          4. Format combined context for LLM injection
        """
        query_plan = []

        # Step 1: Hybrid vector retrieval
        similar_tickets = []
        if self.retriever is not None:
            similar_tickets = self.retriever.search(tenant_id, question, k=k)
            query_plan.append(
                f"[Vector+BM25] Retrieved {len(similar_tickets)} similar tickets "
                f"for tenant={tenant_id}"
            )
        else:
            query_plan.append("[Vector+BM25] Retriever not configured — skipped")

        # Step 2: Graph context
        tenant_context = self.graph.get_tenant_context(tenant_id)
        query_plan.append(
            f"[Graph] Tenant context: {tenant_context['total_tickets']} tickets, "
            f"escalation_rate={tenant_context.get('escalation_rate_pct', 0)}%"
        )

        # Step 3: SQL analytics
        sql_insights = []
        if include_sql:
            sql_insights = _load_duckdb_insights(tenant_id, self.gold_db_path)
            query_plan.append(
                f"[SQL] Gold layer: {len(sql_insights)} insight rows from DuckDB"
            )
        else:
            query_plan.append("[SQL] Skipped (include_sql=False)")

        # Step 4: Format combined context
        combined_context = self._format_combined_context(
            question, similar_tickets, tenant_context, sql_insights
        )
        query_plan.append("[Format] Combined context built — ready for LLM injection")

        return GraphRAGResult(
            query=question,
            tenant_id=tenant_id,
            similar_tickets=similar_tickets,
            tenant_context=tenant_context,
            sql_insights=sql_insights,
            combined_context=combined_context,
            query_plan=query_plan,
        )

    def _format_combined_context(
        self,
        question: str,
        similar_tickets: list,
        tenant_context: dict,
        sql_insights: list[dict],
    ) -> str:
        """
        Format all retrieved information into a structured context string
        ready for injection into an LLM system prompt.
        """
        lines = []

        # Tenant profile
        lines.append("=== TENANT PROFILE ===")
        lines.append(f"Tenant ID : {tenant_context.get('tenant_id', 'unknown')}")
        lines.append(f"Tier      : {tenant_context.get('tier', 'unknown')}")
        lines.append(f"Total Tickets : {tenant_context.get('total_tickets', 0)}")
        lines.append(f"Escalation Rate : {tenant_context.get('escalation_rate_pct', 0)}%")

        top_cats = tenant_context.get("top_categories", [])
        if top_cats:
            cats_str = ", ".join(
                f"{c['category']}({c['count']})" for c in top_cats[:3]
            )
            lines.append(f"Top Categories : {cats_str}")

        lang_breakdown = tenant_context.get("language_breakdown", {})
        if lang_breakdown:
            lang_str = ", ".join(f"{k}:{v}" for k, v in lang_breakdown.items())
            lines.append(f"Languages Used : {lang_str}")

        # Similar past tickets
        if similar_tickets:
            lines.append("\n=== SIMILAR PAST TICKETS ===")
            for i, doc in enumerate(similar_tickets[:5], 1):
                lines.append(
                    f"{i}. [{doc.category.upper()}|{doc.priority}] "
                    f"{doc.text[:100]}..."
                )

        # SQL insights
        if sql_insights:
            lines.append("\n=== ANALYTICS (Gold Layer) ===")
            for ins in sql_insights[:5]:
                src = ins.get("source", "")
                if src == "ticket_funnel":
                    lines.append(
                        f"- Funnel: {ins.get('event_type')} "
                        f"count={ins.get('count')} "
                        f"avg_priority={ins.get('avg_priority')}"
                    )
                elif src == "customer_health":
                    lines.append(
                        f"- Health [{ins.get('date')}]: "
                        f"tickets={ins.get('ticket_count')} "
                        f"avg_priority={ins.get('avg_priority')}"
                    )

        lines.append(f"\n=== ORIGINAL QUESTION ===\n{question}")
        return "\n".join(lines)


# ── Module-level singleton ─────────────────────────────────────────────────────
_default_engine: Optional[GraphRAGEngine] = None


def get_engine() -> GraphRAGEngine:
    global _default_engine
    if _default_engine is None:
        _default_engine = GraphRAGEngine()
    return _default_engine


# ── Standalone Demo ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    os.environ["PYTHONIOENCODING"] = "utf-8"

    print("=" * 65)
    print("CustomerCore Phase 8b - Unified B2B Graph-RAG Demo")
    print("=" * 65)

    # Build knowledge graph
    graph = B2BKnowledgeGraph()

    # Index tickets for two tenants
    acme_tickets = [
        ("TKT-A001", "API returning 500 errors on checkout endpoint", "technical", "critical", "en"),
        ("TKT-A002", "March invoice shows double charge for $420", "billing", "high", "en"),
        ("TKT-A003", "Login broken after your latest deployment", "technical", "high", "en"),
        ("TKT-A004", "Need to cancel our subscription next month", "subscription", "medium", "en"),
        ("TKT-A005", "Export of customer data timing out after 30s", "technical", "high", "en"),
        ("TKT-A006", "Zahlung fehlgeschlagen - bitte helfen", "billing", "high", "de"),
        ("TKT-A007", "Notre tableau de bord ne fonctionne plus", "technical", "critical", "fr"),
    ]
    globex_tickets = [
        ("TKT-B001", "Latency spike on EU cluster affecting production", "technical", "critical", "en"),
        ("TKT-B002", "Overcharged by 2400 USD last billing cycle", "billing", "high", "en"),
        ("TKT-B003", "Data export failing with timeout error", "technical", "high", "en"),
    ]

    print("\nIndexing tickets into knowledge graph...")
    for tid, text, cat, prio, lang in acme_tickets:
        graph.add_ticket("acme-corp", tid, text, cat, prio, lang)
    for tid, text, cat, prio, lang in globex_tickets:
        graph.add_ticket("globex-inc", tid, text, cat, prio, lang)

    # Add mock tenant metrics
    graph.add_tenant_metrics("acme-corp", {
        "avg_resolution_hours": 4.2,
        "open_tickets": 7,
        "csat_score": 3.8,
    })

    print(f"Graph nodes: {graph.node_count()}")
    print(f"Graph edges: {graph.edge_count()}")

    # Tenant context
    print("\n" + "=" * 40)
    print("TENANT CONTEXT: acme-corp")
    ctx = graph.get_tenant_context("acme-corp")
    print(f"  Total Tickets    : {ctx['total_tickets']}")
    print(f"  Escalation Rate  : {ctx['escalation_rate_pct']}%")
    print(f"  Priority Breakdown: {ctx['priority_breakdown']}")
    print(f"  Language Breakdown: {ctx['language_breakdown']}")
    print(f"  Top Categories   : {[c['category'] for c in ctx['top_categories']]}")

    # Similar tenants
    print("\n" + "=" * 40)
    print("SIMILAR TENANTS TO acme-corp:")
    similar = graph.find_similar_tenants("acme-corp")
    for s in similar:
        print(f"  {s['tenant_id']} (similarity={s['similarity']})")

    # Category trends
    print("\n" + "=" * 40)
    print("GLOBAL CATEGORY TRENDS:")
    trends = graph.get_category_trends()
    for cat, count in sorted(trends.items(), key=lambda x: x[1], reverse=True):
        print(f"  {cat:<15}: {count} tickets")

    # Full Graph-RAG query (no retriever, no DuckDB in demo)
    engine = GraphRAGEngine(retriever=None, graph=graph)
    result = engine.query(
        tenant_id="acme-corp",
        question="Why has acme-corp been escalating so many technical issues this month?",
        include_sql=False,  # no DuckDB in demo
    )

    print("\n" + "=" * 40)
    print("GRAPH-RAG QUERY RESULT:")
    print("\nQuery Plan:")
    for step in result.query_plan:
        print(f"  - {step}")

    print("\nCombined Context (injected into LLM prompt):")
    print("-" * 50)
    print(result.combined_context)
    print("=" * 65)
