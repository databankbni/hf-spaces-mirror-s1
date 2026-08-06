import pandas as pd
import numpy as np
import faiss
import pickle
import os
import time
from sentence_transformers import SentenceTransformer

print("=" * 55)
print("  Quran & Hadith Semantic Search — Embedding Script")
print("=" * 55)

print("\n[1/5] Dataset load ho raha hai...")
df = pd.read_csv("Data/final_dataset.csv", encoding="utf-8-sig")
print(f"      Total rows: {len(df)}")
print(f"      Quran rows: {len(df[df['source'] == 'Quran'])}")
print(f"      Hadith rows: {len(df[df['source'] == 'Hadith'])}")

print("\n[2/5] Embedding model load ho raha hai...")
print("      (Pehli baar internet se download hoga — ~90MB)")
print("      (Dobara nahi hoga — cache ho jaata hai)")

MODEL_NAME = "all-MiniLM-L6-v2"
model = SentenceTransformer(MODEL_NAME)
print(f"      Model ready: {MODEL_NAME}")

print("\n[3/5] Text prepare ho raha hai...")

texts = df["english"].fillna("").tolist()

metadata = df[["id", "source", "arabic", "english", "reference", "book"]].to_dict(orient="records")

print(f"      Total texts ready: {len(texts)}")
print(f"      Sample text: {texts[0][:80]}...")

print("\n[4/5] Embeddings generate ho rahi hain...")
print("      Yeh thoda time le sakta hai (5-15 minutes CPU pe)")
print("      Progress bar neeche dikh rahi hai:\n")

start_time = time.time()

embeddings = model.encode(
    texts,
    batch_size=64,          
    show_progress_bar=True, 
    convert_to_numpy=True,  
    normalize_embeddings=True  
)

end_time = time.time()
elapsed = round(end_time - start_time, 2)

print(f"\n      Done! Time laga: {elapsed} seconds")
print(f"      Embedding shape: {embeddings.shape}")
print(f"      Matlab: {embeddings.shape[0]} rows, {embeddings.shape[1]} dimensions har row mein")


print("\n[5/5] FAISS index ban raha hai aur save ho raha hai...")

embeddings = embeddings.astype("float32")
dimension = embeddings.shape[1]  # 384
index = faiss.IndexFlatIP(dimension)

index.add(embeddings)

print(f"      FAISS index mein vectors: {index.ntotal}")

faiss.write_index(index, "quran_hadith.index")
with open("metadata.pkl", "wb") as f:
    pickle.dump(metadata, f)

print("      quran_hadith.index  — saved!")
print("      metadata.pkl        — saved!")

print("\n" + "=" * 55)
print("  Quick Test — 'patience during hardship'")
print("=" * 55)

query = "patience during hardship"
query_vec = model.encode([query], normalize_embeddings=True).astype("float32")
scores, indices = index.search(query_vec, 5)

for rank, (score, idx) in enumerate(zip(scores[0], indices[0]), 1):
    row = metadata[idx]
    print(f"\n  #{rank} | Score: {round(float(score), 3)} | {row['reference']} ({row['source']})")
    print(f"       {row['english'][:120]}...")

print("\n" + "=" * 55)
print("  Embedding generation complete!")
print("  Ab search.py ya app.py run kar saktay hain")
print("=" * 55)