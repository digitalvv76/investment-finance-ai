"""RSS/Atom feed fetcher with rate limiting."""
import asyncio
import hashlib
import logging
import re
from datetime import datetime
from time import mktime
from typing import List, Optional
import aiohttp
import feedparser

from storage.models import NewsItem

logger = logging.getLogger(__name__)

# Browser-like User-Agent to avoid 403/429 blocks
UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# Default delay between requests to the same host (seconds)
DEFAULT_DELAY = 2.0

# Track last request time per host for rate limiting
_host_last_request: dict[str, float] = {}


class RSSFetcher:
    def __init__(self, sources: list, session: Optional[aiohttp.ClientSession] = None):
        self.sources = sources
        self._session = session
        self._own_session = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            connector = aiohttp.TCPConnector(limit=3, limit_per_host=1)
            self._session = aiohttp.ClientSession(
                headers=UA_HEADERS,
                connector=connector,
            )
            self._own_session = True
        return self._session

    async def close(self):
        if self._own_session and self._session:
            await self._session.close()

    async def fetch_single(self, source: dict) -> List[NewsItem]:
        """Fetch a single RSS source and return parsed news items."""
        items = []
        url = source['url']
        name = source.get('name', url)
        category = source.get('category', 'general')
        delay = source.get('delay_seconds', DEFAULT_DELAY)

        # Rate limiting: wait if we've recently hit this host
        await self._rate_limit(url, delay)

        try:
            session = await self._get_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"RSS {name}: HTTP {resp.status}")
                    return items
                content = await resp.text()
        except asyncio.TimeoutError:
            logger.warning(f"RSS {name}: timeout")
            return items
        except Exception as e:
            logger.error(f"RSS {name}: {e}")
            return items

        try:
            feed = feedparser.parse(content)
        except Exception as e:
            logger.error(f"RSS {name}: parse error — {e}")
            return items

        for entry in feed.entries[:20]:  # Only take 20 most recent per source
            title = entry.get('title', '').strip()
            link = entry.get('link', '')
            summary = entry.get('summary', entry.get('description', ''))
            published = entry.get('published_parsed') or entry.get('updated_parsed')

            if not title or not link:
                continue

            pub_dt = datetime.now()
            if published:
                try:
                    pub_dt = datetime.fromtimestamp(mktime(published))
                except Exception:
                    pass

            # Clean HTML from summary
            clean_summary = re.sub(r'<[^>]+>', '', summary)[:500] if summary else ''

            items.append(NewsItem(
                title=title,
                url=link,
                source=name,
                content_snippet=clean_summary,
                published_at=pub_dt,
                captured_at=datetime.now(),
            ))

        logger.info(f"RSS {name}: {len(items)} items")
        return items

    async def fetch_all(self) -> List[NewsItem]:
        """Fetch all configured RSS sources sequentially with delays."""
        all_items = []
        for source in self.sources:
            try:
                items = await self.fetch_single(source)
                all_items.extend(items)
            except Exception as e:
                logger.error(f"RSS source {source.get('name')}: {e}")

        logger.info(f"RSS total: {len(all_items)} items from {len(self.sources)} sources")
        return all_items

    @staticmethod
    async def _rate_limit(url: str, delay: float):
        """Enforce per-host rate limiting."""
        from urllib.parse import urlparse
        host = urlparse(url).netloc or url
        now = asyncio.get_event_loop().time()
        last = _host_last_request.get(host, 0)
        wait = delay - (now - last)
        if wait > 0:
            logger.debug(f"Rate limit: waiting {wait:.1f}s for {host}")
            await asyncio.sleep(wait)
        _host_last_request[host] = asyncio.get_event_loop().time()
