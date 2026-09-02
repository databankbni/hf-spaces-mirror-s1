"""
core/retriever.py
ChromaDB 向量检索与 BM25 关键词检索双路召回。
基于 RRF (Reciprocal Rank Fusion) 算法合并多查询（Multi-Query）结果。
已针对批量推理 (Batch Inference) 与 Top-K 计算复杂度进行性能优化。
"""

from __future__ import annotations

import time
import threading
import logging
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
import torch
import jieba
import numpy as np
from rank_bm25 import BM25Okapi

# 抑制 jieba 默认的 Debug 输出
jieba.setLogLevel(logging.INFO)

class Retriever:
    def __init__(
        self,
        chroma_dir: str | Path,
        model_path: str,
        collection_name: str = "akizuki_blog",
        score_threshold: float = 0.4,
        max_seq_length: int = 512,
    ):
        self.score_threshold = score_threshold
        self._embed_lock = threading.Lock()

        # 初始化向量模型
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[Retriever] 加载 BGE-M3 (device={device})...")
        t0 = time.time()
        self.model = SentenceTransformer(model_path, device=device)
        self.model.max_seq_length = max_seq_length
        print(f"[Retriever] 向量模型加载完成，耗时 {time.time() - t0:.1f}s")

        # 初始化 ChromaDB
        client = chromadb.PersistentClient(
            path=str(chroma_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self.content_col = client.get_collection(f"{collection_name}_content")
        self.title_col = client.get_collection(f"{collection_name}_title")
        print(
            f"[Retriever] ChromaDB 已加载: "
            f"content={self.content_col.count()}, title={self.title_col.count()}"
        )

        # 初始化 BM25 内存索引
        self._init_bm25()

    def _init_bm25(self):
        """读取 ChromaDB 中的全量 content 数据，在内存中构建 BM25 索引。"""
        print("[Retriever] 正在构建 BM25 内存索引...")
        t0 = time.time()

        # 获取全部数据文档
        res = self.content_col.get(include=["documents", "metadatas"])
        docs = res.get("documents", [])
        metas = res.get("metadatas", [])

        self.bm25_mapping = []
        corpus = []
        # (url, chunk_index) → doc dict，用于相邻 chunk 扩展
        self._chunk_index_map: dict[tuple[str, int], dict] = {}

        for doc, meta in zip(docs, metas):
            corpus.append(self._tokenize(doc))
            entry = {
                "content": doc,
                "title": meta.get("title", ""),
                "url": meta.get("url", ""),
                "date": meta.get("date", ""),
                "h2": meta.get("h2", ""),
                "chunk_index": int(meta.get("chunk_index", -1)),
            }
            self.bm25_mapping.append(entry)
            url = meta.get("url", "")
            idx = int(meta.get("chunk_index", -1))
            if url and idx >= 0:
                self._chunk_index_map[(url, idx)] = entry

        if corpus:
            self.bm25 = BM25Okapi(corpus)
            print(f"[Retriever] BM25 索引构建完成，包含 {len(corpus)} 条文档，耗时 {time.time() - t0:.1f}s")
        else:
            self.bm25 = None
            print("[Retriever] 警告：未找到正文数据，跳过 BM25 索引构建。")

    def _tokenize(self, text: str) -> list[str]:
        """使用 jieba 进行基础分词，剔除空白字符。"""
        return [w for w in jieba.lcut(text) if w.strip()]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """执行批量向量化，受线程锁保护。"""
        with self._embed_lock:
            vecs = self.model.encode(
                texts,
                batch_size=32,
                convert_to_tensor=True,
                normalize_embeddings=True,
            )
        return vecs.cpu().float().numpy().tolist()

    def _batch_query_vector(self, queries_embeddings: list[list[float]], n_results: int) -> list[list[dict]]:
        """
        双路向量检索（正文路 + 标题路）加权合并。
        cid 用 url + chunk_index 构造，避免内容前缀碰撞导致的去重错误。
        title_col 只贡献分数，content 始终来自 content_col，
        防止纯标题文本混入最终结果。
        """
        batch_size = len(queries_embeddings)
        batch_results: list[dict[str, dict]] = [{} for _ in range(batch_size)]

        for col, weight in [(self.content_col, 0.7), (self.title_col, 0.3)]:
            res = col.query(
                query_embeddings=queries_embeddings,
                n_results=min(n_results, col.count()),
                include=["documents", "metadatas", "distances"],
            )

            if not res["documents"]:
                continue

            for i in range(batch_size):
                if not res["documents"][i]:
                    continue

                for doc, meta, dist in zip(
                    res["documents"][i],
                    res["metadatas"][i],
                    res["distances"][i],
                ):
                    score = (1 - dist) * weight
                    url = meta.get("url", "")
                    chunk_index = int(meta.get("chunk_index", -1))
                    cid = f"{url}#{chunk_index}"

                    if cid not in batch_results[i]:
                        batch_results[i][cid] = {
                            "id":           cid,
                            "content":      doc if col is self.content_col else "",
                            "title":        meta.get("title", ""),
                            "url":          url,
                            "date":         meta.get("date", ""),
                            "h2":           meta.get("h2", ""),
                            "chunk_index":  chunk_index,
                            "vector_score": score,
                        }
                    else:
                        # 累加分数；title_col 命中时补充正文内容
                        batch_results[i][cid]["vector_score"] += score
                        if col is self.content_col:
                            batch_results[i][cid]["content"] = doc

        # 过滤仅被 title_col 命中、无正文内容的条目
        final_batch_results = []
        for results_dict in batch_results:
            valid = [v for v in results_dict.values() if v["content"]]
            sorted_res = sorted(valid, key=lambda x: x["vector_score"], reverse=True)
            final_batch_results.append(sorted_res)

        return final_batch_results

    def _query_bm25(self, query: str, n_results: int) -> list[dict]:
        """单次 BM25 正文关键词检索，[优化点3] 使用 numpy.argpartition 降低排序复杂度。"""
        if not self.bm25:
            return []

        tokenized_query = self._tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)

        scores_arr = np.array(scores)
        k = min(n_results, len(scores_arr))
        if k == 0:
            return []

        # 使用 argpartition 获取 Top-K 的无序索引，时间复杂度降至 O(N)
        top_k_idx = np.argpartition(scores_arr, -k)[-k:]
        # 仅对这 K 个结果进行局部精确排序 (降序)
        top_k_idx = top_k_idx[np.argsort(scores_arr[top_k_idx])[::-1]]

        results = []
        for idx in top_k_idx:
            score = scores_arr[idx]
            if score > 0:
                info = self.bm25_mapping[idx]
                cid = f"{info['url']}#{info['chunk_index']}"
                results.append({
                    "id":          cid,
                    "content":     info["content"],
                    "title":       info["title"],
                    "url":         info["url"],
                    "date":        info["date"],
                    "h2":          info["h2"],
                    "chunk_index": info["chunk_index"],
                    "bm25_score":  score,
                })
        return results

    def search(
        self,
        queries: list[str],
        n_results: int = 10,
    ) -> list[dict]:
        """
        执行 Multi-query 检索，结合 Vector 与 BM25 进行 RRF 结果融合。
        """
        if not queries:
            return []

        k_rrf = 60
        rrf_scores: dict[str, float] = {}
        doc_store: dict[str, dict] = {}

        # [优化点1] 批量处理所有 queries 的 Embedding 提取，避免多次加载和锁竞争
        queries_embeddings = self._embed(queries)

        # [优化点2] 一次性获取所有 query 的向量检索结果
        batch_vec_results = self._batch_query_vector(queries_embeddings, n_results)

        for i, q in enumerate(queries):
            # 1. 提取当前 query 对应的向量结果
            vec_results = batch_vec_results[i]
            for rank, item in enumerate(vec_results):
                cid = item["id"]
                doc_store[cid] = item
                rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k_rrf + rank + 1)

            # 2. BM25 检索 (仅限正文)
            bm25_results = self._query_bm25(q, n_results)
            for rank, item in enumerate(bm25_results):
                cid = item["id"]
                if cid not in doc_store:
                    doc_store[cid] = item
                rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k_rrf + rank + 1)

        # 按 RRF 分数进行最终全局排序
        ranked_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        final_results = []
        for cid, rrf_score in ranked_docs[:n_results]:
            doc = doc_store[cid].copy()
            doc.pop("id", None)
            doc.pop("vector_score", None)
            doc.pop("bm25_score", None)
            doc["score"] = rrf_score
            final_results.append(doc)

        return final_results

    def fetch_adjacent(self, url: str, chunk_index: int) -> list[dict]:
        """
        取指定 chunk 在同文章内的前后相邻块，供 fetch_context 工具调用。
        边界处理：
          - 首块（无前驱）：向后取两个
          - 末块（无后继）：向前取两个
          - 中间块：前后各取一个
        返回列表长度 0~2，每项包含 content / title / url / h2 / chunk_index。
        """
        has_prev = (url, chunk_index - 1) in self._chunk_index_map
        has_next = (url, chunk_index + 1) in self._chunk_index_map

        if has_prev and has_next:
            candidates = [chunk_index - 1, chunk_index + 1]
        elif not has_prev:
            candidates = [chunk_index + 1, chunk_index + 2]
        else:
            candidates = [chunk_index - 2, chunk_index - 1]

        results = []
        for idx in candidates:
            if idx < 0:
                continue
            entry = self._chunk_index_map.get((url, idx))
            if entry is None:
                continue
            results.append({
                "content":     entry["content"],
                "title":       entry["title"],
                "url":         url,
                "h2":          entry["h2"],
                "chunk_index": idx,
            })
        return results