"""INGEST stage: dedup → DB insert → vector index."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pipeline.item import PipelineItem

if TYPE_CHECKING:
    from storage.database import Database
    from collector.dedup import DedupManager
    from storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


class IngestStage:
    """Pipeline stage 0: ingest raw items into the system.

    Responsibilities:
      1. Deduplicate against existing items (URL hash + content hash)
      2. Insert new items into SQLite
      3. Index items in vector store for semantic dedup
    """

    def __init__(
        self,
        db: Database,
        dedup: DedupManager,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._db = db
        self._dedup = dedup
        self._vector = vector_store

    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]:
        """Process raw items: dedup → DB insert → vector index.

        Accepts PipelineItems (with id=0 for new items).  Runs dedup
        against existing content, inserts survivors into the database,
        and indexes them in the vector store.
        """
        if not items:
            return []

        # Step 1: Convert PipelineItem → NewsItem for DedupManager compatibility
        from storage.models import NewsItem
        news_items = [_to_news_item(it) for it in items]
        new_items = self._dedup.filter_duplicates(news_items)
        if not new_items:
            return []

        # Step 2: Insert into DB (per-item isolation)
        results: list[PipelineItem] = []
        for news in new_items:
            try:
                news_id = self._db.insert_news(news)
                item = PipelineItem(
                    id=news_id,
                    title=news.title,
                    source=news.source,
                    url=news.url,
                    snippet=news.content_snippet,
                    published_at=str(news.published_at) if news.published_at else "",
                    raw_tickers=news.tickers_found.split(",") if news.tickers_found else [],
                    _raw={"id": news_id, "title": news.title, "source": news.source,
                           "url": news.url, "snippet": news.content_snippet,
                           "tickers_found": news.tickers_found,
                           "macro_tags": getattr(news, "macro_tags", ""),
                           "published_at": str(news.published_at) if news.published_at else ""},
                )
                results.append(item)
            except Exception:
                logger.exception("INGEST: DB insert failed for %s", news.title[:60])

        # Step 3: Index in vector store
        if self._vector and results:
            for item, news in zip(results, new_items):
                try:
                    self._dedup.index_item(news)
                except Exception:
                    logger.debug("INGEST: vector index failed for id=%d", item.id)

        return results


def _to_news_item(item: PipelineItem) -> "NewsItem":
    """Convert PipelineItem to NewsItem for DedupManager/DB compatibility."""
    from datetime import datetime
    from storage.models import NewsItem
    return NewsItem(
        id=item.id if item.id else None,
        title=item.title,
        url=item.url,
        source=item.source,
        content_snippet=item.snippet,
        tickers_found=item.tickers_found,
        published_at=datetime.now(),
    )
