"""Agent tools — callable functions the LangGraph agent can invoke."""

import re
from database.connector import DatabaseConnector
from rag.embeddings import SchemaRAG
from llm.prompt_templates import SYSTEM_PROMPT, FEW_SHOT_EXAMPLES


class AgentTools:
    """Provides tools for the LangGraph agent to use."""

    def __init__(self, db: DatabaseConnector, rag: SchemaRAG):
        self.db = db
        self.rag = rag

    def schema_lookup(self, question: str) -> str:
        """Retrieve relevant schema context for a question using FAISS RAG."""
        try:
            context = self.rag.retrieve(question)
            return context if context else "No relevant schema found."
        except Exception as e:
            return f"Schema lookup failed: {str(e)}"

    def execute_sql(self, sql: str) -> dict:
        """Execute a read-only SQL query safely."""
        return self.db.execute_query(sql)

    def validate_results(self, question: str, sql: str, results: dict) -> dict:
        """
        Validate query results for sanity.
        Returns dict with is_valid, issues list.
        """
        issues = []

        if not results.get("success"):
            return {"is_valid": False, "issues": [results.get("error", "Unknown error")]}

        row_count = results.get("row_count", 0)
        rows = results.get("rows", [])

        # Check for empty results on questions that expect data
        question_lower = question.lower()
        if row_count == 0:
            expecting_data = any(w in question_lower for w in [
                "how many", "count", "total", "list", "show", "top", "all"
            ])
            if expecting_data:
                issues.append(f"Query returned 0 rows but the question expects data. The SQL might be too restrictive.")

        # Check for suspiciously large single values
        if rows and len(rows) == 1:
            for key, val in rows[0].items():
                if isinstance(val, (int, float)) and val < 0:
                    issues.append(f"Negative value found in '{key}': {val}. This might indicate a calculation error.")

        return {
            "is_valid": len(issues) == 0,
            "issues": issues,
            "row_count": row_count,
        }

    def get_system_prompt(self, schema_context: str) -> str:
        """Build the full system prompt with schema context and few-shot examples."""
        return SYSTEM_PROMPT.format(schema_context=schema_context) + "\n" + FEW_SHOT_EXAMPLES

    @staticmethod
    def extract_sql(response_text: str) -> str:
        """Extract clean SQL from LLM response."""
        text = response_text.strip()

        # Remove markdown code blocks
        match = re.search(r"```(?:sql)?\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
        if match:
            text = match.group(1).strip()

        text = text.strip("`").strip()

        # Extract SQL statements
        lines = text.split("\n")
        sql_lines = []
        in_sql = False
        for line in lines:
            stripped = line.strip().upper()
            if stripped.startswith(("SELECT", "WITH", "SHOW")):
                in_sql = True
            if in_sql:
                sql_lines.append(line)

        if sql_lines:
            text = "\n".join(sql_lines)

        text = text.rstrip(";").strip() + ";"
        return text

    @staticmethod
    def extract_tables_from_sql(sql: str) -> list[str]:
        """Extract table names referenced in a SQL query (FROM and JOIN clauses)."""
        if not sql:
            return []
        # Match table names after FROM, JOIN, and their variants
        pattern = r'(?:FROM|JOIN)\s+`?(\w+)`?'
        matches = re.findall(pattern, sql, re.IGNORECASE)
        # Deduplicate while preserving order
        seen = set()
        tables = []
        for t in matches:
            t_lower = t.lower()
            if t_lower not in seen:
                seen.add(t_lower)
                tables.append(t_lower)
        return tables

    @staticmethod
    def compute_faithfulness(answer: str, execution_result: dict) -> dict:
        """
        Check if the LLM answer is faithful to the SQL query results.
        Compares key values from results against the answer text.

        Returns:
            dict with score (0-1), matched, total, details
        """
        if not answer or not execution_result.get("success"):
            return {"score": 0, "matched": 0, "total": 0, "details": []}

        rows = execution_result.get("rows", [])
        if not rows:
            return {"score": 1.0, "matched": 0, "total": 0, "details": []}

        answer_lower = answer.lower()

        # Extract key values from the first few rows of results
        values_to_check = []
        for row in rows[:5]:  # Check top 5 rows
            for key, val in row.items():
                if val is None:
                    continue
                val_str = str(val).strip()
                if not val_str or len(val_str) < 2:
                    continue
                # Skip ID-like columns
                if key.lower().endswith("id") or key.lower() == "url":
                    continue
                values_to_check.append({"column": key, "value": val_str})

        if not values_to_check:
            return {"score": 1.0, "matched": 0, "total": 0, "details": []}

        # Check each value in the answer
        matched = 0
        details = []
        for item in values_to_check:
            found = item["value"].lower() in answer_lower
            if found:
                matched += 1
            details.append({
                "column": item["column"],
                "value": item["value"],
                "found": found,
            })

        total = len(values_to_check)
        score = round(matched / total, 4) if total > 0 else 1.0

        return {
            "score": score,
            "matched": matched,
            "total": total,
            "details": details,
        }

    @staticmethod
    def validate_sql_safety(sql: str) -> tuple:
        """Check SQL is read-only. Returns (is_safe, error)."""
        blocked = [
            "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE",
            "CREATE", "REPLACE", "RENAME", "GRANT", "REVOKE"
        ]
        upper = sql.upper()
        for kw in blocked:
            if re.search(rf"\b{kw}\b", upper):
                return False, f"Blocked: SQL contains '{kw}'"

        if not (upper.lstrip().startswith("SELECT") or
                upper.lstrip().startswith("WITH") or
                upper.lstrip().startswith("SHOW")):
            return False, "Only SELECT/WITH/SHOW queries are allowed."

        return True, ""
