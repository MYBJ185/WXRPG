from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from jianghu_rpg.models import WorldDocument


class HashingEmbeddingFunction(EmbeddingFunction[Documents]):
    def __init__(self, dimensions: int = 192):
        self.dimensions = dimensions

    def __call__(self, input: Documents) -> Embeddings:
        return [self.embed_text(text) for text in input]

    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+", text.lower())
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (len(token) / 10.0)
            vector[index] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class LoreVectorStore:
    def __init__(self, persist_dir: Path):
        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.embedding = HashingEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name="jianghu_world",
            embedding_function=self.embedding,
            metadata={"hnsw:space": "cosine"},
        )

    def ingest(self, documents: list[WorldDocument]) -> None:
        existing = self.collection.count()
        if existing >= len(documents):
            return
        if existing:
            self.collection.delete(ids=[doc.id for doc in documents if self._has_id(doc.id)])
        self.collection.add(
            ids=[doc.id for doc in documents],
            documents=[doc.text for doc in documents],
            metadatas=[
                {
                    "title": doc.title,
                    "category": doc.category,
                    "tags": ",".join(doc.tags),
                }
                for doc in documents
            ],
        )

    def search(self, query: str, limit: int = 4) -> list[dict[str, str]]:
        results = self.collection.query(query_texts=[query], n_results=limit)
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        response: list[dict[str, str]] = []
        for text, meta in zip(docs, metas):
            response.append(
                {
                    "title": str(meta.get("title", "")),
                    "category": str(meta.get("category", "")),
                    "tags": str(meta.get("tags", "")),
                    "text": text,
                }
            )
        return response

    def _has_id(self, document_id: str) -> bool:
        result = self.collection.get(ids=[document_id])
        return bool(result.get("ids"))
