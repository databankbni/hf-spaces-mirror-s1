"""Flask application — F1InsightAI Text-to-SQL RAG Chatbot."""

import os
import time
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from config import Config
from database.connector import DatabaseConnector
from database.chat_store import ChatStore
from rag.embeddings import SchemaRAG
from agent.tools import AgentTools
from agent.agent import SQLAgent

# ── Initialize Flask ──────────────────────────────────────────
app = Flask(__name__)
app.secret_key = Config.FLASK_SECRET_KEY
CORS(app)

# ── Initialize Components ────────────────────────────────────
print("\n" + "=" * 50)
print("  F1InsightAI — Starting up...")
print("=" * 50 + "\n")

# Database
db = DatabaseConnector()
# Chat Store (server-side conversations)
chat_store = ChatStore(db)
# RAG
rag = SchemaRAG()

# Index schema into RAG at startup
print("[INIT] Building schema index...")
schema_info = db.get_schema_info()
rag.index_schema(schema_info)

# Agent
tools = AgentTools(db, rag)
agent = SQLAgent(tools)
print("[INIT] Ready!\n")


# ── Routes ────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the chat UI."""
    return render_template("index.html")


@app.route("/architecture")
def architecture():
    """Serve the architecture showcase page."""
    return render_template("architecture.html")


@app.route("/api/health", methods=["GET"])
def health_check():
    """Check system health: database + LLM."""
    db_ok = db.test_connection()
    return jsonify({
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "model": Config.GROQ_MODEL,
        "rag_indexed": rag._is_indexed,
    })


@app.route("/api/tables", methods=["GET"])
def get_tables():
    """Return list of available tables."""
    tables = rag.get_all_table_names()
    return jsonify({"tables": tables, "count": len(tables)})


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Return database statistics for the welcome screen."""
    tables = rag.get_all_table_names()
    total_rows = sum(t.get("row_count", 0) for t in schema_info)
    total_columns = sum(len(t.get("columns", [])) for t in schema_info)
    return jsonify({
        "table_count": len(tables),
        "total_rows": total_rows,
        "total_columns": total_columns,
        "model": Config.GROQ_MODEL,
        "database": Config.MYSQL_DATABASE,
    })


# ── Conversation API (server-side storage) ───────────────────

@app.route("/api/conversations", methods=["GET"])
def list_conversations():
    """Get all conversations."""
    convos = chat_store.get_conversations()
    return jsonify({"conversations": convos})


@app.route("/api/conversations", methods=["POST"])
def create_conversation():
    """Create a new conversation."""
    data = request.get_json()
    title = data.get("title", "New Chat") if data else "New Chat"
    conv_id = chat_store.create_conversation(title)
    return jsonify({"id": conv_id, "title": title})


@app.route("/api/conversations/<conv_id>", methods=["GET"])
def get_conversation(conv_id):
    """Get messages for a specific conversation."""
    messages = chat_store.get_messages(conv_id)
    return jsonify({"messages": messages})


@app.route("/api/conversations/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id):
    """Delete a conversation."""
    ok = chat_store.delete_conversation(conv_id)
    return jsonify({"deleted": ok})


@app.route("/api/conversations/clear", methods=["DELETE"])
def clear_conversations():
    """Delete all conversations."""
    count = chat_store.clear_all()
    return jsonify({"cleared": count})


@app.route("/api/conversations/<conv_id>/rename", methods=["PATCH"])
def rename_conversation_api(conv_id):
    """Rename a conversation."""
    data = request.get_json()
    title = data.get("title", "").strip() if data else ""
    if not title:
        return jsonify({"error": "Title required"}), 400
    ok = chat_store.rename_conversation(conv_id, title)
    return jsonify({"renamed": ok, "title": title})


@app.route("/api/conversations/<conv_id>/pin", methods=["PATCH"])
def pin_conversation_api(conv_id):
    """Pin or unpin a conversation."""
    data = request.get_json()
    pinned = data.get("pinned", True) if data else True
    ok = chat_store.pin_conversation(conv_id, pinned)
    return jsonify({"pinned": pinned, "ok": ok})


# ── Chat Endpoint (Agentic) ─────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def chat():
    """Main chat endpoint — uses LangGraph agent."""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "No message provided"}), 400

    question = data["message"].strip()
    if not question:
        return jsonify({"error": "Empty message"}), 400

    conversation_id = data.get("conversation_id")

    # Create conversation if needed
    if not conversation_id:
        title = question[:50] + "..." if len(question) > 50 else question
        conversation_id = chat_store.create_conversation(title)

    # Get chat history for multi-turn context
    history = chat_store.get_recent_history(conversation_id, limit=20)

    # Save user message
    chat_store.add_message(conversation_id, "user", question)

    # Run the agent
    result = agent.run(question, chat_history=history)

    # Save assistant response
    chat_store.add_message(
        conversation_id, "assistant", result.get("answer", ""),
        data=result
    )

    # Add conversation_id to response
    result["conversation_id"] = conversation_id

    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=Config.FLASK_DEBUG
    )
