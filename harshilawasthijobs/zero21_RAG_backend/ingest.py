import json
import uuid
import os
import asyncio

from embeddings import embed_documents
from chunker import smart_chunk
from retriever import get_collection
from config import AGENT_CONFIG

def batch_list(data: list, batch_size: int):
    """Yield successive n-sized chunks from a list."""
    for i in range(0, len(data), batch_size):
        yield data[i:i + batch_size]

async def ingest_for_agent(agent_name: str, path: str):
    """
    Asynchronously ingests a text file for an agent, now with batching
    to handle large numbers of chunks without crashing the database.
    """
    collection = get_collection(agent_name)
    if not collection:
        print(f"ℹ️ No collection for agent '{agent_name}'. Skipping.")
        return

    if not os.path.exists(path):
        print(f"❌ Input file not found for {agent_name}: {path}")
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            full_text = f.read()
        if not full_text:
            print(f"⚠️ Data file for agent '{agent_name}' is empty. Skipping.")
            return
    except Exception as e:
        print(f"❌ Error reading file for agent '{agent_name}': {e}")
        return

    chunked_docs = smart_chunk(full_text)
    if not chunked_docs:
        print(f"⚠️ No chunks generated for '{agent_name}'.")
        return

    print(f"Embedding {len(chunked_docs)} chunks for agent '{agent_name}'...")
    vectors = await embed_documents(chunked_docs, batch_size=32)
    ids = [str(uuid.uuid4()) for _ in chunked_docs]
    metadatas = [{"source_file": path, "preview": doc[:256]} for doc in chunked_docs]

    # --- BATCHING FIX ---
    # Process and upsert the data in smaller, manageable batches to avoid errors.
    batch_size = 4000 # Safely under the ChromaDB limit
    total_batches = len(chunked_docs) // batch_size + (1 if len(chunked_docs) % batch_size > 0 else 0)

    for i, batch_docs in enumerate(batch_list(chunked_docs, batch_size)):
        start_index = i * batch_size
        end_index = start_index + len(batch_docs)
        print(f"  -> Upserting batch {i+1}/{total_batches} for agent '{agent_name}'...")

        collection.upsert(
            ids=ids[start_index:end_index],
            embeddings=vectors[start_index:end_index],
            metadatas=metadatas[start_index:end_index],
            documents=batch_docs
        )
    # --- END OF FIX ---

    print(f"✅ Ingested {len(chunked_docs)} chunks for agent '{agent_name}'.")


async def ingest_all_agents_if_needed():
    # This function remains logically the same
    tasks = [
        ingest_for_agent(name, conf["data_file"])
        for name, conf in AGENT_CONFIG.items()
    ]
    await asyncio.gather(*tasks)