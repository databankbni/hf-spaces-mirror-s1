"""
LangGraph Agentic SQL Agent — F1InsightAI

A stateful agent that uses tools to:
1. Retrieve relevant schema via RAG
2. Generate SQL with the LLM
3. Execute SQL safely
4. Self-reflect on results (retry if bad)
5. Decompose complex questions into sub-queries
6. Generate natural language answers
"""

from typing import TypedDict, Annotated, Any
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from config import Config
from agent.tools import AgentTools
from llm.prompt_templates import ANSWER_SYSTEM_PROMPT, ANSWER_USER_TEMPLATE


# ── Agent State ──────────────────────────────────────────────
class AgentState(TypedDict):
    """State that flows through the agent graph."""
    question: str
    chat_history: list              # Previous messages for multi-turn
    schema_context: str             # Retrieved from RAG
    retrieved_tables: list          # Tables retrieved by RAG with scores
    sql: str                        # Generated SQL
    sql_attempts: int               # Retry counter
    execution_result: dict          # From MySQL
    validation: dict                # From validate_results
    answer: str                     # Final natural language answer
    follow_ups: list                # Follow-up suggestions
    agent_steps: list               # Trace of agent reasoning
    error: str                      # Error if any
    is_database_query: bool         # Whether question needs SQL
    rag_metrics: dict               # RAG evaluation metrics


# ── Agent Builder ────────────────────────────────────────────
class SQLAgent:
    """LangGraph-based agentic SQL pipeline."""

    MAX_RETRIES = 2

    def __init__(self, tools: AgentTools):
        self.tools = tools
        self.llm = ChatGroq(
            api_key=Config.GROQ_API_KEY,
            model=Config.GROQ_MODEL,
            temperature=0.1,
            max_tokens=800,
        )
        self.graph = self._build_graph()
        print("[Agent] LangGraph agent initialized.")

    def _build_graph(self) -> Any:
        """Build the LangGraph state machine."""
        graph = StateGraph(AgentState)

        # Add nodes
        graph.add_node("classify", self._classify)
        graph.add_node("direct_answer", self._direct_answer)
        graph.add_node("retrieve_schema", self._retrieve_schema)
        graph.add_node("generate_sql", self._generate_sql)
        graph.add_node("execute_sql", self._execute_sql)
        graph.add_node("reflect", self._reflect)
        graph.add_node("retry_sql", self._retry_sql)
        graph.add_node("generate_answer", self._generate_answer)
        graph.add_node("generate_follow_ups", self._generate_follow_ups)

        # Set entry point — classify first
        graph.set_entry_point("classify")

        # Conditional: classify decides if it's a DB query or conversation
        graph.add_conditional_edges(
            "classify",
            self._route_after_classify,
            {
                "database": "retrieve_schema",
                "conversation": "direct_answer",
            }
        )

        # Database query pipeline
        graph.add_edge("retrieve_schema", "generate_sql")
        graph.add_edge("generate_sql", "execute_sql")
        graph.add_edge("execute_sql", "reflect")

        # Conditional: reflect decides whether to retry or answer
        graph.add_conditional_edges(
            "reflect",
            self._should_retry,
            {
                "retry": "retry_sql",
                "answer": "generate_answer",
            }
        )

        graph.add_edge("retry_sql", "execute_sql")
        graph.add_edge("generate_answer", "generate_follow_ups")
        graph.add_edge("generate_follow_ups", END)
        graph.add_edge("direct_answer", END)

        return graph.compile()

    # ── Node Implementations ─────────────────────────────────

    def _classify(self, state: AgentState) -> dict:
        """Node: Classify whether the question needs SQL or is conversational."""
        question = state["question"].strip().lower()

        # Fast-path: obvious conversational patterns (no LLM call needed)
        # NOTE: Do NOT include "yes", "no", "sure", "ok" etc. here — those may be
        # follow-up responses to a bot question and need LLM + conversation context
        conversational_patterns = [
            'hi', 'hello', 'hey', 'good morning', 'good evening', 'good afternoon',
            'thanks', 'thank you', 'bye', 'goodbye',
            'what are you', 'who are you', 'how are you', 'what can you do',
            'help', 'what is this', 'tell me about yourself', 'tell me about you',
            'what do you do', 'can you help', 'what is your name', 'your name',
            'can you tell me about yourself', 'can you tell me everything',
            'everything you can do', 'everything that you can',
            'nice to meet', 'what questions', 'what should i ask', 'what can i ask',
        ]

        # Only fast-path if there's NO conversation history (first message)
        history = state.get("chat_history", [])
        is_conversational = (
            not history and
            any(question.startswith(g) or question == g for g in conversational_patterns)
        )

        if not is_conversational:
            # Build context from last bot message for follow-up understanding
            last_bot_msg = ""
            if history:
                for msg in reversed(history):
                    if msg["role"] == "assistant":
                        last_bot_msg = msg["content"][:200]
                        break

            context_hint = ""
            if last_bot_msg:
                context_hint = (
                    f"\n\nPREVIOUS BOT MESSAGE (for context): \"{last_bot_msg}\"\n"
                    "If the user's message is a follow-up to this (e.g., 'yes', 'sure', 'tell me more'), "
                    "classify as DATABASE since they likely want more data."
                )

            try:
                response = self.llm.invoke([
                    SystemMessage(content=(
                        "You classify user messages for an F1 (Formula 1) database chatbot. "
                        "Reply with EXACTLY one word: DATABASE or CONVERSATION.\n\n"
                        "DATABASE — The user wants to query actual F1 data, OR is saying 'yes'/'sure'/'tell me more' "
                        "in response to a bot question that offered to show more data.\n\n"
                        "CONVERSATION — The user is doing ANY of these:\n"
                        "  - Greetings, thanks, or goodbyes\n"
                        "  - Asking about YOU (the chatbot) or your capabilities\n"
                        "  - General chit-chat NOT about querying specific F1 data\n"
                        "  - Asking 'what can you do' or 'tell me everything'\n\n"
                        "When in doubt and there is conversation history, lean toward DATABASE."
                        f"{context_hint}"
                    )),
                    HumanMessage(content=question),
                ])
                classification = response.content.strip().upper()
                is_db = "DATABASE" in classification
            except Exception:
                is_db = True  # Default to database query on error
        else:
            is_db = False

        step = {
            "node": "classify",
            "action": "Classified user intent",
            "result": "📊 Database query" if is_db else "💬 Conversational",
        }

        return {
            "is_database_query": is_db,
            "agent_steps": state.get("agent_steps", []) + [step],
        }

    def _route_after_classify(self, state: AgentState) -> str:
        """Conditional edge: route to SQL pipeline or direct answer."""
        return "database" if state.get("is_database_query", True) else "conversation"

    def _direct_answer(self, state: AgentState) -> dict:
        """Node: Answer conversational messages directly without SQL."""
        question = state["question"]
        history = state.get("chat_history", [])

        # Build full conversation context with numbered user questions
        context = ""
        if history:
            context = "\n\nFull conversation history:\n"
            q_num = 0
            for msg in history:
                if msg["role"] == "user":
                    q_num += 1
                    context += f"  Question #{q_num}: {msg['content']}\n"
                else:
                    context += f"  Answer: {msg['content'][:200]}\n"

        try:
            response = self.llm.invoke([
                SystemMessage(content=(
                    "You are F1InsightAI, a friendly AI assistant for querying a Formula 1 database. "
                    "The database contains F1 data from 1950 to 2024 — drivers, races, constructors, "
                    "circuits, lap times, pit stops, qualifying, standings, and more.\n\n"
                    "The user sent a conversational message. Respond warmly and helpfully.\n\n"
                    "IMPORTANT: If the user asks about previous questions or the conversation history, "
                    "refer to the FULL CONVERSATION HISTORY provided below. "
                    "Questions are numbered (Question #1, #2, etc.) for easy reference.\n\n"
                    "If the user is just greeting, mention you can help explore F1 stats and history. "
                    "Keep your response concise (2-3 sentences max)."
                )),
                HumanMessage(content=f"User message: {question}{context}"),
            ])
            answer = response.content.strip()
        except Exception as e:
            answer = "Hi! I'm F1InsightAI 🏎️ Ask me anything about Formula 1 — drivers, races, teams, lap times, pit stops, and 75 years of racing history!"

        step = {
            "node": "direct_answer",
            "action": "Conversational response (no SQL needed)",
            "result": answer[:80] + "..." if len(answer) > 80 else answer,
        }

        return {
            "answer": answer,
            "agent_steps": state.get("agent_steps", []) + [step],
        }

    def _retrieve_schema(self, state: AgentState) -> dict:
        """Node: Retrieve relevant schema using RAG."""
        question = state["question"]
        # Include chat context for multi-turn queries
        history = state.get("chat_history", [])
        if history:
            # Enrich query with recent context for better RAG retrieval
            recent = [m["content"] for m in history[-4:] if m["role"] == "user"]
            enriched_query = " ".join(recent + [question])
        else:
            enriched_query = question

        context = self.tools.schema_lookup(enriched_query)

        # Get retrieved tables with scores for RAG evaluation
        retrieved_tables = self.tools.rag.retrieve_with_scores(enriched_query)

        step = {
            "node": "retrieve_schema",
            "action": "RAG search for relevant tables",
            "result": f"Found schema context ({len(context)} chars)"
        }

        return {
            "schema_context": context,
            "retrieved_tables": retrieved_tables,
            "agent_steps": state.get("agent_steps", []) + [step],
        }

    def _generate_sql(self, state: AgentState) -> dict:
        """Node: Generate SQL using the LLM."""
        question = state["question"]
        schema_context = state["schema_context"]
        history = state.get("chat_history", [])

        system_prompt = self.tools.get_system_prompt(schema_context)

        # Build messages with multi-turn context
        messages = [SystemMessage(content=system_prompt)]

        # Add recent chat history for multi-turn context
        if history:
            context_note = "Previous conversation context:\n"
            for msg in history[-6:]:
                role = "User" if msg["role"] == "user" else "Assistant"
                context_note += f"{role}: {msg['content'][:200]}\n"
            context_note += f"\nNow answer the new question considering the above context.\n"
            messages.append(HumanMessage(content=context_note + f"\nQuestion: {question}"))
        else:
            messages.append(HumanMessage(content=f"Question: {question}\n\nGenerate ONLY the SQL query, nothing else."))

        try:
            response = self.llm.invoke(messages)
            raw = response.content
            sql = self.tools.extract_sql(raw)
            is_safe, safety_err = self.tools.validate_sql_safety(sql)

            step = {
                "node": "generate_sql",
                "action": "LLM generated SQL",
                "result": sql[:100] + "..." if len(sql) > 100 else sql,
                "safe": is_safe,
            }

            if not is_safe:
                return {
                    "sql": "",
                    "error": safety_err,
                    "agent_steps": state.get("agent_steps", []) + [step],
                }

            return {
                "sql": sql,
                "sql_attempts": state.get("sql_attempts", 0) + 1,
                "agent_steps": state.get("agent_steps", []) + [step],
            }

        except Exception as e:
            return {
                "sql": "",
                "error": f"SQL generation failed: {str(e)}",
                "agent_steps": state.get("agent_steps", []) + [{
                    "node": "generate_sql", "action": "Failed", "result": str(e)
                }],
            }

    def _execute_sql(self, state: AgentState) -> dict:
        """Node: Execute the SQL query."""
        sql = state.get("sql", "")

        if not sql:
            return {
                "execution_result": {"success": False, "error": state.get("error", "No SQL generated"), "rows": [], "columns": [], "row_count": 0},
                "agent_steps": state.get("agent_steps", []) + [{
                    "node": "execute_sql", "action": "Skipped", "result": "No SQL to execute"
                }],
            }

        result = self.tools.execute_sql(sql)

        step = {
            "node": "execute_sql",
            "action": f"Executed SQL",
            "result": f"{'✅' if result['success'] else '❌'} {result.get('row_count', 0)} rows" +
                      (f" | Error: {result.get('error', '')}" if not result['success'] else ""),
        }

        return {
            "execution_result": result,
            "agent_steps": state.get("agent_steps", []) + [step],
        }

    def _reflect(self, state: AgentState) -> dict:
        """Node: Self-reflect on results — validate and decide next action."""
        question = state["question"]
        sql = state.get("sql", "")
        result = state.get("execution_result", {})

        validation = self.tools.validate_results(question, sql, result)

        step = {
            "node": "reflect",
            "action": "Validating results",
            "result": "✅ Results look good" if validation["is_valid"] else f"⚠️ Issues: {validation['issues']}",
        }

        return {
            "validation": validation,
            "agent_steps": state.get("agent_steps", []) + [step],
        }

    def _should_retry(self, state: AgentState) -> str:
        """Conditional edge: decide whether to retry or generate answer."""
        result = state.get("execution_result", {})
        validation = state.get("validation", {})
        attempts = state.get("sql_attempts", 0)

        # Retry if: execution failed or validation has issues, AND we haven't exceeded retries
        if attempts < self.MAX_RETRIES:
            if not result.get("success"):
                return "retry"
            if not validation.get("is_valid") and validation.get("issues"):
                return "retry"

        return "answer"

    def _retry_sql(self, state: AgentState) -> dict:
        """Node: Retry SQL generation with error feedback."""
        question = state["question"]
        schema_context = state["schema_context"]
        failed_sql = state.get("sql", "")
        result = state.get("execution_result", {})
        validation = state.get("validation", {})

        # Build error context
        if not result.get("success"):
            error_info = f"SQL Error: {result.get('error', 'Unknown')}"
        else:
            error_info = f"Validation issues: {validation.get('issues', [])}"

        retry_prompt = (
            f"The previous SQL query failed or produced suspicious results.\n"
            f"Previous SQL: {failed_sql}\n"
            f"Error: {error_info}\n"
            f"Original question: {question}\n\n"
            f"Please generate a corrected SQL query. Return ONLY the SQL."
        )

        system_prompt = self.tools.get_system_prompt(schema_context)

        try:
            response = self.llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=retry_prompt),
            ])

            sql = self.tools.extract_sql(response.content)
            is_safe, safety_err = self.tools.validate_sql_safety(sql)

            step = {
                "node": "retry_sql",
                "action": f"Retry attempt #{state.get('sql_attempts', 0) + 1}",
                "result": sql[:100] if is_safe else f"Unsafe: {safety_err}",
            }

            return {
                "sql": sql if is_safe else "",
                "sql_attempts": state.get("sql_attempts", 0) + 1,
                "error": safety_err if not is_safe else "",
                "agent_steps": state.get("agent_steps", []) + [step],
            }

        except Exception as e:
            return {
                "sql": "",
                "error": str(e),
                "sql_attempts": state.get("sql_attempts", 0) + 1,
                "agent_steps": state.get("agent_steps", []) + [{
                    "node": "retry_sql", "action": "Retry failed", "result": str(e)
                }],
            }

    def _generate_answer(self, state: AgentState) -> dict:
        """Node: Generate natural language answer from results."""
        question = state["question"]
        sql = state.get("sql", "")
        result = state.get("execution_result", {})

        if not result.get("success"):
            answer = f"I generated the SQL but it failed to execute: {result.get('error', 'Unknown error')}"
        elif not result.get("rows"):
            answer = "The query executed successfully but returned no results. Try broadening your question."
        else:
            # Format results for the prompt
            results_text = ""
            for row in result["rows"][:20]:
                results_text += f"  {row}\n"
            if result["row_count"] > 20:
                results_text += f"  ... and {result['row_count'] - 20} more rows\n"

            user_msg = ANSWER_USER_TEMPLATE.format(
                question=question,
                sql=sql,
                row_count=result["row_count"],
                results=results_text,
            )

            try:
                response = self.llm.invoke([
                    SystemMessage(content=ANSWER_SYSTEM_PROMPT),
                    HumanMessage(content=user_msg),
                ])
                answer = response.content.strip()
            except Exception as e:
                answer = f"Results found but couldn't generate summary: {str(e)}"

        step = {
            "node": "generate_answer",
            "action": "Generated natural language answer",
            "result": answer[:80] + "..." if len(answer) > 80 else answer,
        }

        return {
            "answer": answer,
            "agent_steps": state.get("agent_steps", []) + [step],
            "rag_metrics": self._compute_rag_metrics(state, answer),
        }

    def _generate_follow_ups(self, state: AgentState) -> dict:
        """Node: Generate follow-up question suggestions."""
        question = state["question"]
        answer = state.get("answer", "")
        result = state.get("execution_result", {})

        if not result.get("success") or not answer:
            return {"follow_ups": []}

        # If the query returned 0 rows, instruct the LLM to suggest broader questions
        zero_rows_instruction = ""
        if result.get("row_count", 0) == 0:
            zero_rows_instruction = (
                "CRITICAL: The previous query returned 0 rows, meaning the data they asked about "
                "(e.g., specific countries, categories, names) DOES NOT EXIST in the database. "
                "DO NOT suggest follow-ups asking for more details about those specific missing things. "
                "Instead, suggest broader questions to help them discover what data ACTUALLY exists "
                "(e.g., 'What countries ARE in the database?', 'Show all available categories').\n\n"
            )

        prompt = (
            f'The user asked about a Formula 1 database: "{question}"\n'
            f'The answer was: "{answer[:300]}"\n\n'
            f'{zero_rows_instruction}'
            "Suggest exactly 3 short, relevant follow-up questions. "
            "Each should be different (drill-down, comparison, aggregation). "
            "Return ONLY the 3 questions, one per line."
        )

        try:
            response = self.llm.invoke([
                SystemMessage(content="You suggest short follow-up database questions. Return exactly 3 questions, one per line."),
                HumanMessage(content=prompt),
            ])

            lines = response.content.strip().split("\n")
            follow_ups = []
            for line in lines:
                cleaned = line.strip().lstrip("0123456789.-) ").strip()
                if cleaned and len(cleaned) > 5:
                    follow_ups.append(cleaned)
            return {"follow_ups": follow_ups[:3]}

        except Exception:
            return {"follow_ups": []}

    def _compute_rag_metrics(self, state: AgentState, answer: str) -> dict:
        """Compute RAG evaluation metrics: MRR, Recall@K, Context Relevance, Faithfulness."""
        sql = state.get("sql", "")
        retrieved_tables = state.get("retrieved_tables", [])
        execution_result = state.get("execution_result", {})

        if not sql or not retrieved_tables:
            return {}

        # Extract table names from SQL (proxy ground truth)
        tables_in_sql = self.tools.extract_tables_from_sql(sql)
        retrieved_names = [t["table"] for t in retrieved_tables]

        if not tables_in_sql:
            return {}

        # ── MRR (Mean Reciprocal Rank) ──
        # Find the rank of the first SQL-used table in the FAISS results
        mrr = 0.0
        for needed_table in tables_in_sql:
            if needed_table in retrieved_names:
                rank = retrieved_names.index(needed_table) + 1
                mrr = 1.0 / rank
                break  # MRR uses the FIRST relevant result

        # ── Recall@K ──
        # Of all tables needed by SQL, how many were retrieved?
        found = [t for t in tables_in_sql if t in retrieved_names]
        recall_at_k = len(found) / len(tables_in_sql) if tables_in_sql else 0
        k = len(retrieved_names)

        # ── Context Relevance ──
        # Of all tables retrieved, how many were actually used in SQL?
        relevant_retrieved = [t for t in retrieved_names if t in tables_in_sql]
        context_relevance = len(relevant_retrieved) / len(retrieved_names) if retrieved_names else 0

        # ── Faithfulness ──
        faithfulness = self.tools.compute_faithfulness(answer, execution_result)

        return {
            "mrr": round(mrr, 4),
            "recall_at_k": round(recall_at_k, 4),
            "k": k,
            "context_relevance": round(context_relevance, 4),
            "faithfulness_score": faithfulness["score"],
            "faithfulness_matched": faithfulness["matched"],
            "faithfulness_total": faithfulness["total"],
            "retrieved_tables": retrieved_names,
            "tables_used_in_sql": tables_in_sql,
            "tables_found_in_retrieval": found,
        }

    # ── Public API ───────────────────────────────────────────

    def run(self, question: str, chat_history: list = None) -> dict:
        """
        Run the agent on a question.

        Args:
            question: User's natural language question
            chat_history: Previous messages for multi-turn context

        Returns:
            dict with: answer, sql, results, agent_steps, follow_ups, error, execution_time
        """
        import time
        start = time.time()

        initial_state = {
            "question": question,
            "chat_history": chat_history or [],
            "schema_context": "",
            "retrieved_tables": [],
            "sql": "",
            "sql_attempts": 0,
            "execution_result": {},
            "validation": {},
            "answer": "",
            "follow_ups": [],
            "agent_steps": [],
            "error": "",
            "is_database_query": True,
            "rag_metrics": {},
        }

        try:
            final_state = self.graph.invoke(initial_state)
            elapsed = round(time.time() - start, 2)

            result = final_state.get("execution_result", {})

            return {
                "answer": final_state.get("answer", ""),
                "sql": final_state.get("sql", ""),
                "results": {
                    "columns": result.get("columns", []),
                    "rows": result.get("rows", []),
                    "row_count": result.get("row_count", 0),
                } if result.get("success") else None,
                "execution_time": elapsed,
                "follow_ups": final_state.get("follow_ups", []),
                "agent_steps": final_state.get("agent_steps", []),
                "rag_metrics": final_state.get("rag_metrics", {}),
                "error": final_state.get("error") or (result.get("error") if not result.get("success") else None),
            }

        except Exception as e:
            elapsed = round(time.time() - start, 2)
            return {
                "answer": None,
                "sql": None,
                "results": None,
                "execution_time": elapsed,
                "follow_ups": [],
                "agent_steps": [],
                "error": f"Agent error: {str(e)}",
            }
