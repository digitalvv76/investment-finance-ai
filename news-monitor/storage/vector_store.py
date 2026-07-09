"""Vector store for semantic dedup and article embeddings.

Uses ChromaDB for storage and sentence-transformers for embeddings.
Enables semantic similarity search to catch articles that rephrase
the same news without sharing keywords.
"""
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


class VectorStore:
    """ChromaDB-backed vector store for news articles.

    Stores article embeddings and supports semantic similarity search.
    Used for:
    1. Semantic dedup — catch rephrased duplicates
    2. Semantic search — find related articles by meaning
    """

    def __init__(self, persist_path: str = "data/chroma"):
        self._persist_path = persist_path
        self._client = None
        self._collection = None
        self._model = None
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self):
        """Initialize ChromaDB client and embedding model."""
        if self._initialized:
            return

        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=self._persist_path)
            self._collection = self._client.get_or_create_collection(
                name="news_articles",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("ChromaDB initialized at %s", self._persist_path)
        except ImportError:
            logger.warning("chromadb not installed — vector store disabled")
            return
        except Exception as e:
            logger.error("ChromaDB init failed: %s", e)
            return

        try:
            from sentence_transformers import SentenceTransformer
            # Use a small, fast model suitable for news dedup
            self._model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("SentenceTransformer model loaded")
        except ImportError:
            logger.warning("sentence-transformers not installed — embeddings disabled")
        except Exception as e:
            logger.error("SentenceTransformer load failed: %s", e)

        self._initialized = True

    @property
    def is_ready(self) -> bool:
        return self._initialized and self._collection is not None and self._model is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_article(self, article_id: int, text: str, metadata: dict = None) -> bool:
        """Add an article embedding to the vector store.

        Args:
            article_id: Database ID of the news item.
            text: Title + content snippet to embed.
            metadata: Optional dict with source, tickers, etc.

        Returns:
            True if added successfully, False otherwise.
        """
        if not self.is_ready:
            return False

        try:
            embedding = self._embed(text)
            if embedding is None:
                return False

            meta = metadata or {"source": ""}
            if not meta:
                meta = {"source": ""}
            self._collection.add(
                ids=[str(article_id)],
                embeddings=[embedding],
                metadatas=[meta],
            )
            logger.debug("Vector store: added article %d", article_id)
            return True
        except Exception as e:
            logger.error("Vector store add failed for %d: %s", article_id, e)
            return False

    def find_similar(
        self, text: str, threshold: float = 0.85, max_results: int = 5
    ) -> List[int]:
        """Find articles semantically similar to the given text.

        Args:
            text: The query text (title + snippet).
            threshold: Cosine similarity threshold (0.0-1.0).
            max_results: Maximum results to return.

        Returns:
            List of article IDs that are similar above the threshold.
        """
        if not self.is_ready:
            return []

        try:
            embedding = self._embed(text)
            if embedding is None:
                return []

            if self._collection.count() == 0:
                return []

            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=min(max_results, max(1, self._collection.count())),
                include=["distances"],
            )

            similar_ids = []
            if results and results['ids'] and results['ids'][0]:
                for doc_id, distance in zip(results['ids'][0], results['distances'][0]):
                    # ChromaDB returns cosine distance (0=identical, 2=opposite)
                    similarity = 1.0 - (distance / 2.0)
                    if similarity >= threshold:
                        similar_ids.append(int(doc_id))

            return similar_ids
        except Exception as e:
            logger.error("Vector store search failed: %s", e)
            return []

    def max_similarity(self, text: str) -> float:
        """Return the cosine similarity to the most similar article.

        Returns 0.0 if the store is empty or no articles are similar.
        """
        if not self.is_ready or self._collection.count() == 0:
            return 0.0

        try:
            embedding = self._embed(text)
            if embedding is None:
                return 0.0

            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=min(3, max(1, self._collection.count())),
                include=["distances"],
            )

            if results and results['distances'] and results['distances'][0]:
                best_distance = results['distances'][0][0]
                # ChromaDB cosine distance: 0=identical, 2=opposite
                similarity = 1.0 - (best_distance / 2.0)
                return round(max(similarity, 0.0), 4)

            return 0.0
        except Exception as e:
            logger.error("Vector store max_similarity failed: %s", e)
            return 0.0

    def is_semantic_duplicate(self, text: str, threshold: float = 0.90) -> bool:
        """Check if an article is a semantic duplicate of any stored article.

        Args:
            text: The article text to check.
            threshold: Similarity threshold for duplicate detection.

        Returns:
            True if a very similar article already exists.
        """
        similar = self.find_similar(text, threshold=threshold, max_results=1)
        return len(similar) > 0

    def delete_article(self, article_id: int):
        """Remove an article from the vector store."""
        if not self._collection:
            return
        try:
            self._collection.delete(ids=[str(article_id)])
        except Exception as e:
            logger.error("Vector store delete failed: %s", e)

    def count(self) -> int:
        """Return the number of stored embeddings."""
        if not self._collection:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def clear(self):
        """Delete all embeddings (for testing)."""
        if not self._collection:
            return
        try:
            all_ids = self._collection.get()['ids']
            if all_ids:
                self._collection.delete(ids=all_ids)
        except Exception:
            pass

    def close(self):
        """Release the ChromaDB client and its underlying file handles.

        ChromaDB caches systems process-wide and the persistent HNSW segment
        keeps ``data_level0.bin`` memory-mapped. On Windows an open handle blocks
        directory removal, so we drop references, clear ChromaDB's shared-system
        cache, and force a GC pass to let the OS release the files. Safe to call
        on an uninitialized store.
        """
        self._collection = None
        self._model = None
        try:
            from chromadb.api.shared_system_client import SharedSystemClient
            SharedSystemClient.clear_system_cache()
        except Exception:
            pass
        self._client = None
        self._initialized = False
        import gc
        gc.collect()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _embed(self, text: str) -> Optional[List[float]]:
        """Generate embedding vector for text."""
        if not self._model or not text:
            return None
        try:
            # Truncate to avoid excessive embedding time
            truncated = text[:2000]
            embedding = self._model.encode(truncated, show_progress_bar=False)
            return embedding.tolist()
        except Exception as e:
            logger.error("Embedding failed: %s", e)
            return None
