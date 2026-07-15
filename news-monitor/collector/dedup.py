"""Deduplication manager for incoming news items.

Four-tier dedup:
1. Exact: URL already in DB → skip
2. Near-duplicate: normalized content hash match (prefix-stripped)
3. Within-batch: Jaccard title similarity against current batch
4. Semantic: ChromaDB vector similarity (rephrased duplicates)

Macro news exemption: titles matching macro_indicators.yaml whitelist
bypass dedup to prevent critical releases (CPI, FOMC, etc.) from being
silently dropped as duplicates of preview/forecast articles.
"""
import hashlib
import logging
import os
import re
from collections import deque
from typing import List, Optional

import yaml

from storage.models import NewsItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Breaking/urgency prefixes — stripped before content hashing so that
# "BREAKING: Iran attacks" and "Iran attacks" share the same fingerprint.
# ---------------------------------------------------------------------------
_BREAKING_PREFIXES = [
    "BREAKING:", "BREAKING—", "BREAKING -",
    "URGENT:", "URGENT—", "URGENT -",
    "JUST IN:", "JUST IN—", "JUST IN -",
    "FLASH:", "FLASH—", "FLASH -",
    "ALERT:", "ALERT—", "ALERT -",
    "DEVELOPING:", "DEVELOPING—", "DEVELOPING -",
    "突发:", "突发—", "突发 -",
    "快讯:", "快讯—", "快讯 -",
    "重磅:", "重磅—", "重磅 -",
]


class DedupManager:
    """Check incoming news items for duplicates before insertion.

    Maintains an in-memory cache of recent content fingerprints to
    catch near-duplicates that differ only in URL tracking params.
    Optionally uses a VectorStore for semantic duplicate detection.

    Four-tier architecture:
        Tier 1: Exact URL match (in-memory + DB seed)
        Tier 2: Normalized content hash match (prefix-stripped)
        Tier 2.5: Within-batch Jaccard title similarity (fast, no vector DB)
        Tier 3: Semantic similarity via VectorStore (if available)
    """

    # Semantic similarity threshold — 0.82 catches rephrased duplicates
    # from different sources while avoiding false positives.
    SEMANTIC_THRESHOLD = 0.82

    # Within-batch Jaccard title similarity threshold — fast pre-check
    # before the more expensive vector lookup.
    BATCH_JACCARD_THRESHOLD = 0.65

    def __init__(self, max_cache_size: int = 10000, vector_store=None):
        self._seen_urls: deque[str] = deque(maxlen=max_cache_size)
        self._seen_hashes: deque[str] = deque(maxlen=max_cache_size)
        self._url_set: set[str] = set()
        self._hash_set: set[str] = set()

        # Macro indicator whitelist — loaded once at startup
        self._macro_patterns: list[tuple[str, re.Pattern]] = []
        self._load_macro_whitelist()
        self._max_cache = max_cache_size
        self._vector_store = vector_store
        # Tracks items accepted in the current batch for within-batch dedup
        self._batch_titles: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_duplicate(self, item: NewsItem, existing_urls: set[str] = None,
                     batch_items: list = None, embed_cache: dict = None) -> bool:
        """Check if this item is a duplicate.

        Returns True if the item should be skipped (already seen).

        Args:
            item: The news item to check.
            existing_urls: Set of URLs already in the database (optional).
            batch_items: Items already accepted in the current batch (optional).
        """
        # Tier 1: exact URL match against DB + in-memory cache
        normalized_url = self._normalize_url(item.url)
        if existing_urls and normalized_url in existing_urls:
            return True
        if normalized_url in self._url_set:
            return True

        # Tier 2: normalized content hash (prefix-stripped)
        content_hash = self._content_hash(item)
        if content_hash in self._hash_set:
            logger.debug("Dedup: content hash match — %s...", item.title[:60])
            return True

        # Tier 2.5: within-batch dedup (Jaccard → semantic)
        item_title_norm = self._strip_prefix(item.title or "")
        item_text = f"{item.title or ''} {item.content_snippet or ''}"

        if batch_items:
            for accepted in batch_items:
                # Fast pre-check: Jaccard title similarity
                accepted_title = self._strip_prefix(
                    getattr(accepted, 'title', '') or ""
                )
                if self.title_similarity(item_title_norm, accepted_title) >= self.BATCH_JACCARD_THRESHOLD:
                    logger.debug(
                        "Dedup: batch Jaccard match — %s... ≈ %s...",
                        (item.title or "")[:60],
                        (getattr(accepted, 'title', '') or "")[:60],
                    )
                    return True

                # Semantic pre-check: cached-vector cosine (NO re-encoding).
                # Each unique text is embedded once (pre-warmed batch cache);
                # this comparison is a cheap dot product.
                if self._vector_store and self._vector_store.is_ready:
                    accepted_text = (
                        f"{getattr(accepted, 'title', '') or ''} "
                        f"{getattr(accepted, 'content_snippet', '') or ''}"
                    )
                    v_item = self._cached_embed(item_text, embed_cache)
                    v_acc = self._cached_embed(accepted_text, embed_cache)
                    sim = self._vector_store.cosine(v_item, v_acc)
                    if sim >= self.SEMANTIC_THRESHOLD:
                        logger.debug(
                            "Dedup: batch semantic match (%.3f) — %s...",
                            sim, (item.title or "")[:60],
                        )
                        return True

        # Tier 3: semantic similarity via vector store
        if self._vector_store and self._vector_store.is_ready:
            text = f"{item.title or ''} {item.content_snippet or ''}"
            if self._vector_store.is_semantic_duplicate(text, threshold=self.SEMANTIC_THRESHOLD):
                logger.debug("Dedup: semantic match — %s...", item.title[:60])
                return True

        # Not a duplicate — record for future checks
        self._record(item, normalized_url, content_hash)
        self._batch_titles.append(item_title_norm)
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
        """Filter a batch of items, returning only new ones.

        Uses within-batch dedup: items accepted earlier in the batch
        are compared against later items via Jaccard title similarity.
        """
        # Reset batch tracking at the start of each batch
        self._batch_titles = []

        # Pre-encode every item's text ONCE (one vectorized call). This kills
        # the O(N^2) re-encoding that made large cold-start batches (156 items
        # → ~24k encodes) block the event loop for tens of minutes.
        embed_cache: dict[str, list] = {}
        if self._vector_store and self._vector_store.is_ready:
            texts = [f"{it.title or ''} {it.content_snippet or ''}" for it in items]
            try:
                vecs = self._vector_store.embed_batch(texts)
                if vecs is not None:
                    for t, v in zip(texts, vecs):
                        embed_cache[t] = v
            except Exception:
                logger.debug("Dedup: batch pre-encode failed, falling back to lazy")

        new_items = []
        for item in items:
            # Macro indicators (CPI, FOMC, NFP, etc.) bypass dedup entirely.
            # A PPI release is NOT a duplicate of a PPI preview — the real data
            # must always reach the pipeline.  (MacroAgent V2.1 design, §1)
            if self.is_macro_title(item.title or ""):
                new_items.append(item)
                continue
            if not self.is_duplicate(item, existing_urls, batch_items=new_items,
                                     embed_cache=embed_cache):
                new_items.append(item)
        skipped = len(items) - len(new_items)
        if skipped:
            logger.info("Dedup: skipped %d/%d duplicates (T1-3 + batch)", skipped, len(items))
        return new_items

    # ------------------------------------------------------------------
    # Macro whitelist — titles matching these patterns bypass dedup
    # ------------------------------------------------------------------

    def _load_macro_whitelist(self):
        """Load macro indicator keywords from config/macro_indicators.yaml."""
        try:
            config_dir = os.path.join(
                os.path.dirname(__file__), "..", "config",
            )
            path = os.path.join(config_dir, "macro_indicators.yaml")
            if not os.path.exists(path):
                logger.debug("Dedup: macro_indicators.yaml not found, skipping")
                return
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for entry in data.get("indicators", []):
                for kw in entry.get("keywords", []):
                    self._macro_patterns.append((
                        entry["id"],
                        re.compile(re.escape(kw), re.IGNORECASE),
                    ))
            logger.info("Dedup: loaded %d macro keyword patterns", len(self._macro_patterns))
        except Exception:
            logger.warning("Dedup: failed to load macro whitelist", exc_info=True)

    def is_macro_title(self, title: str) -> bool:
        """Return True if the title matches a macro indicator keyword."""
        if not title or not self._macro_patterns:
            return False
        for _ind_id, pattern in self._macro_patterns:
            if pattern.search(title):
                return True
        return False

    def _cached_embed(self, text: str, embed_cache: dict | None):
        """Fetch an embedding from the per-batch cache, encoding on miss."""
        if embed_cache is not None and text in embed_cache:
            return embed_cache[text]
        vec = self._vector_store._embed(text[:2000])
        if embed_cache is not None:
            embed_cache[text] = vec
        return vec

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
    def _strip_prefix(title: str) -> str:
        """Remove breaking/urgency prefixes from a title.

        "BREAKING: Iran attacks ships" → "Iran attacks ships"
        """
        for prefix in _BREAKING_PREFIXES:
            if title.startswith(prefix):
                return title[len(prefix):].strip()
        return title

    @staticmethod
    def _content_hash(item: NewsItem) -> str:
        """Create a fingerprint from (prefix-stripped title + first 300 chars of snippet).

        Prefix stripping ensures "BREAKING: Event X" and "Event X" share the
        same hash.  Extended to 300 chars for better coverage of short articles.
        """
        title = DedupManager._strip_prefix(item.title or "")
        snippet = (item.content_snippet or "")[:300]
        material = f"{title}|{snippet}"
        return hashlib.sha256(material.encode('utf-8', errors='ignore')).hexdigest()

    def _record(self, item: NewsItem, normalized_url: str, content_hash: str):
        """Record an item as seen. Uses deque with maxlen for automatic
        FIFO eviction — no more destructive clear-all when cache fills."""
        # Remove from set if deque is about to evict an old entry
        if len(self._seen_urls) == self._max_cache:
            old = self._seen_urls[0]
            self._url_set.discard(old)
        if len(self._seen_hashes) == self._max_cache:
            old = self._seen_hashes[0]
            self._hash_set.discard(old)

        self._seen_urls.append(normalized_url)
        self._seen_hashes.append(content_hash)
        self._url_set.add(normalized_url)
        self._hash_set.add(content_hash)

    def load_existing_urls(self, urls: List[str]):
        """Pre-seed the URL cache from database (called at startup)."""
        for url in urls:
            norm = self._normalize_url(url)
            self._seen_urls.append(norm)
            self._url_set.add(norm)
        logger.info("Dedup: seeded %d existing URLs", len(urls))
