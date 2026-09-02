import os
import structlog
from typing import Optional, List

log = structlog.get_logger()

SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL", "")
SUPABASE_DB_HOST = os.environ.get("SUPABASE_DB_HOST", "")

_mem0_client: Optional[any] = None
# In-memory storage for local dev / fallback when Supabase is down
_local_memory_store: dict[str, list[str]] = {}

def get_mem0_client():
    """Get the Mem0 client, or raise Exception if not configured/available."""
    global _mem0_client
    if _mem0_client is None:
        if not SUPABASE_DB_HOST:
            raise ValueError("SUPABASE_DB_HOST is not configured. Falling back to local in-memory store.")
            
        from mem0 import Memory
        config = {
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "dbname": "postgres",
                    "user": "postgres",
                    "password": os.environ.get("SUPABASE_DB_PASSWORD", ""),
                    "host": SUPABASE_DB_HOST,
                    "port": 5432,
                    "collection_name": "memories",
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": "bge-m3",
                    "ollama_base_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
                },
            },
            "llm": {
                "provider": "litellm",
                "config": {
                    "model": "gemma-3-1b",
                    "api_base": os.environ.get("LITELLM_URL", "http://localhost:4000"),
                    "api_key": os.environ.get("LITELLM_MASTER_KEY", "sk-test"),
                },
            },
        }
        _mem0_client = Memory.from_config(config)
        log.info("mem0_initialized")
    return _mem0_client

def store_memory(customer_id: str, tenant_id: str, content: str, agent_id: str = "triage_agent"):
    """Store customer memory either in Mem0/Supabase or local in-memory store."""
    user_id = f"{tenant_id}:{customer_id}"
    try:
        client = get_mem0_client()
        client.add(
            messages=[{"role": "user", "content": content}],
            user_id=user_id,
            agent_id=agent_id,
        )
        log.info("memory_stored", user_id=user_id, agent_id=agent_id)
    except Exception as e:
        # Fallback to local dict store
        log.debug("mem0_store_failed_using_local_fallback", user_id=user_id, error=str(e))
        if user_id not in _local_memory_store:
            _local_memory_store[user_id] = []
        _local_memory_store[user_id].append(content)
        log.info("memory_stored_locally", user_id=user_id)

def recall_memories(customer_id: str, tenant_id: str, query: str, limit: int = 5) -> List[str]:
    """Recall customer memories from Mem0 or local in-memory store."""
    user_id = f"{tenant_id}:{customer_id}"
    try:
        client = get_mem0_client()
        results = client.search(query=query, user_id=user_id, limit=limit)
        memories = [r.get("memory", "") for r in results]
        log.info("memories_recalled", user_id=user_id, count=len(memories))
        return memories
    except Exception as e:
        # Fallback to local dict search
        log.debug("mem0_recall_failed_using_local_fallback", user_id=user_id, error=str(e))
        local_mems = _local_memory_store.get(user_id, [])
        # Very simple query match fallback: return matches or recent ones up to limit
        matches = []
        for mem in reversed(local_mems):
            if any(word in mem.lower() for word in query.lower().split()):
                matches.append(mem)
            if len(matches) >= limit:
                break
        if not matches:
            matches = local_mems[-limit:]
        log.info("memories_recalled_locally", user_id=user_id, count=len(matches))
        return matches

def get_all_memories(customer_id: str, tenant_id: str) -> List[str]:
    """Get all memories for a customer."""
    user_id = f"{tenant_id}:{customer_id}"
    try:
        client = get_mem0_client()
        results = client.get_all(user_id=user_id)
        return [r.get("memory", "") for r in results]
    except Exception as e:
        log.debug("mem0_get_all_failed_using_local_fallback", error=str(e))
        return _local_memory_store.get(user_id, [])
