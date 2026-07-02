"""Deduplication manager for incoming news items.

Three-tier dedup:
1. Exact: URL already in DB → skip
2. Near-duplicate: content hash match (SHA-256 of title + snippet)
3. Semantic: ChromaDB vector similarity (rephrased duplicates)
"""
import hashlib
import logging
import re
from typing import List, Optional

from storage.models import NewsItem

logger = logging.getLogger(__name__)


class DedupManager:
    """Check incoming news items for duplicates before insertion.

    Maintains an in-memory cache of recent content fingerprints to
    catch near-duplicates that differ only in URL tracking params.
    Optionally uses a VectorStore for semantic duplicate detection.

    Three-tier architecture:
        Tier 1: Exact URL match (in-memory + DB seed)
        Tier 2: SHA-256 content hash match
        Tier 3: Semantic similarity via VectorStore (if available)
    """

    def __init__(self, max_cache_size: int = 5000, vector_store=None):
        self._seen_urls: set[str] = set()
        self._seen_hashes: set[str] = set()
        self._max_cache = max_cache_size
        self._vector_store = vector_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_duplicate(self, item: NewsItem, existing_urls: set[str] = None) -> bool:
        """Check if this item is a duplicate.

        Returns True if the item should be skipped (already seen).

        Args:
            item: The news item to check.
            existing_urls: Set of URLs already in the database (optional).
        """
        # Tier 1: exact URL match against DB + in-memory cache
        normalized_url = self._normalize_url(item.url)
        if existing_urls and normalized_url in existing_urls:
            return True
        if normalized_url in self._seen_urls:
            return True

        # Tier 2: content hash match
        content_hash = self._content_hash(item)
        if content_hash in self._seen_hashes:
            logger.debug(f"Dedup: content hash match — {item.title[:60]}...")
            return True

        # Tier 3: semantic similarity via vector store
        if self._vector_store and self._vector_store.is_ready:
            text = f"{item.title or ''} {item.content_snippet or ''}"
            if self._vector_store.is_semantic_duplicate(text, threshold=0.92):
                logger.debug(f"Dedup: semantic match — {item.title[:60]}...")
                return True

        # Not a duplicate — record for future checks
        self._record(item, normalized_url, content_hash)
        return False

    def index_item(self, item: NewsItem):
        """Add item to the vector store after DB insertion (has an ID).

        Call this AFTER db.insert_news() so the item has a valid ID.
        Safe to call if vector store is not configured — silently no-ops.
        """
        if not self._vector_store or not self._vector_store.is_ready:
            return
        if not item.id:
            logger.warning("Dedup: cannot index item without ID — call after DB insert")
            return
        text = f"{item.title or ''} {item.content_snippet or ''}"
        self._vector_store.add_article(
            item.id, text,
            metadata={"source": item.source or "", "tickers": item.tickers_found or ""},
        )

    def is_similar(self, item1: NewsItem, item2: NewsItem, threshold: float = 0.70) -> bool:
        """Check if two news items are semantically similar by title.

        Uses word-level Jaccard similarity on normalized titles.

        Args:
            item1, item2: Items to compare.
            threshold: Similarity threshold (0.0 - 1.0). Default 0.70.

        Returns:
            True if title similarity >= threshold.
        """
        if not item1.title or not item2.title:
            return False

        score = self.title_similarity(item1.title, item2.title)
        return score >= threshold

    def filter_duplicates(
        self, items: List[NewsItem], existing_urls: set[str] = None
    ) -> List[NewsItem]:
        """Filter a batch of items, returning only new ones."""
        new_items = []
        for item in items:
            if not self.is_duplicate(item, existing_urls):
                new_items.append(item)
        skipped = len(items) - len(new_items)
        if skipped:
            logger.info(f"Dedup: skipped {skipped}/{len(items)} duplicates")
        return new_items

    # ------------------------------------------------------------------
    # Similarity helpers
    # ------------------------------------------------------------------

    @staticmethod
    def title_similarity(title1: str, title2: str) -> float:
        """Compute Jaccard similarity between two titles.

        Normalizes: lowercase, strip punctuation, split to words.
        """
        def tokenize(t: str) -> set:
            t = t.lower()
            t = re.sub(r'[^a-z0-9\s]', '', t)
            return set(t.split())

        words1 = tokenize(title1)
        words2 = tokenize(title2)

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Strip tracking params and fragments from URL."""
        # Remove fragment
        url = url.split('#')[0]
        # Remove common tracking params
        url = re.sub(r'[?&](utm_\w+|ref|source|fbclid|gclid)=[^&]*', '', url)
        # Clean up trailing ? or &
        url = re.sub(r'[?&]$', '', url)
        return url

    @staticmethod
    def _content_hash(item: NewsItem) -> str:
        """Create a fingerprint from (title + first 200 chars of snippet)."""
        material = f"{item.title}|{item.content_snippet[:200]}"
        return hashlib.sha256(material.encode('utf-8', errors='ignore')).hexdigest()

    def _record(self, item: NewsItem, normalized_url: str, content_hash: str):
        """Record an item as seen."""
        self._seen_urls.add(normalized_url)
        self._seen_hashes.add(content_hash)

        # Prune caches if they grow too large
        if len(self._seen_urls) > self._max_cache:
            # Clear half the cache (simple FIFO approximation)
            self._seen_urls.clear()
            self._seen_urls.add(normalized_url)
        if len(self._seen_hashes) > self._max_cache:
            self._seen_hashes.clear()
            self._seen_hashes.add(content_hash)

    def load_existing_urls(self, urls: List[str]):
        """Pre-seed the URL cache from database (called at startup)."""
        for url in urls:
            self._seen_urls.add(self._normalize_url(url))
        logger.info(f"Dedup: seeded {len(urls)} existing URLs")
