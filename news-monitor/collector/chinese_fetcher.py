"""Chinese financial news fetcher.

Covers real-time financial news from Chinese-language sources via JSON APIs.
Sources are configured in sources.yaml -> chinese_sources.

Currently supported:
  1. 新浪财经 7x24 快讯 (Sina Finance live feed)
     Endpoint: feed.mix.sina.com.cn/api/roll/get
     Channels: lid=2509 (综合), lid=2510 (全球)

  2. 华尔街见闻 7x24 快讯 (WallstreetCN live feed)
     Endpoint: api.wallstreetcn.com/apiv1/content/lives
     Channels: global, us-stock, forex, crypto, commodities
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import List, Optional

import aiohttp

from storage.models import NewsItem

logger = logging.getLogger(__name__)

UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# HTML tag cleaner
_HTML_RE = re.compile(r"<[^>]+>")


def _clean_html(text: str) -> str:
    return _HTML_RE.sub("", text).strip()


def _ts_to_datetime(ts: int) -> datetime:
    """Convert Unix timestamp (int seconds) to datetime."""
    try:
        return datetime.fromtimestamp(int(ts))
    except (ValueError, OSError):
        return datetime.now()


class ChineseNewsFetcher:
    """Fetch Chinese financial news from JSON API endpoints.

    Config dict (from sources.yaml -> chinese_sources):
        sina_channels:
          - {name: "综合", lid: 2509, category: "macro"}
          - {name: "全球", lid: 2510, category: "global"}
        wallstreetcn_channels:
          - {channel: "global", name: "全球"}
        max_items_per_source: 20
        request_delay_seconds: 2.0
    """

    # Chinese noise keywords — titles matching these are skipped at source.
    # These are categorically NOT market news: party propaganda, single-stock
    # limit-up moves, routine oil price adjustments, weather, traffic, etc.
    _NOISE_KEYWORDS: set[str] = {
        # Party propaganda
        "党委", "学习贯彻", "全会精神", "主题教育", "民主生活会",
        "团拜", "重要讲话", "指示精神", "新时代中国特色社会主义",
        "两个维护", "四个意识", "四个自信", "党史学习教育",
        "不忘初心", "牢记使命", "巡视整改", "全面从严治党",
        "中心组学习", "意识形态", "统战",
        # Single-stock noise
        "涨停", "跌停", "连续涨停", "一字板", "地天板", "天地板",
        "封板", "炸板", "尾盘拉升", "尾盘跳水",
        # Routine domestic announcements (no US market link)
        "油价调整", "成品油价格", "限行通知", "天气预报",
        "交通管制", "停水停电",
        # Non-financial domestic
        "文体活动", "文艺汇演",
    }

    def __init__(
        self,
        config: dict = None,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        config = config or {}
        self.sina_channels: list = config.get("sina_channels", [])
        self.wscn_channels: list = config.get("wallstreetcn_channels", [])
        self.max_items: int = config.get("max_items_per_source", 20)
        self.delay: float = config.get("request_delay_seconds", 2.0)
        self._session = session
        self._own_session = False

    def _is_noise_title(self, title: str) -> bool:
        """Quick check: is this title categorically noise?

        Returns True if the title should be skipped at the source level.
        """
        return any(kw in title for kw in self._NOISE_KEYWORDS)

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

    # ------------------------------------------------------------------
    # 新浪财经 7x24 快讯
    # ------------------------------------------------------------------

    SINA_FEED_URL = "https://feed.mix.sina.com.cn/api/roll/get"

    async def fetch_sina_channel(self, channel: dict) -> List[NewsItem]:
        """Fetch a single sina finance live feed channel.

        Args:
            channel: dict with keys: name, lid (int), category

        The API returns JSON:
          {"result": {"status": {"code": 0}, "data": [
            {"title": "...", "ctime": 1783052118, "url": "...", "intro": "..."}
          ]}}
        """
        items: List[NewsItem] = []
        channel_name = channel.get("name", "unknown")
        lid = channel.get("lid", 2509)

        session = await self._get_session()
        params = {
            "pageid": "153",
            "lid": str(lid),
            "k": "",
            "num": str(min(self.max_items, 50)),
            "page": "1",
        }

        try:
            async with session.get(
                self.SINA_FEED_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning("新浪财经[%s]: HTTP %d", channel_name, resp.status)
                    return items
                data = await resp.json()
        except asyncio.TimeoutError:
            logger.warning("新浪财经[%s]: timeout", channel_name)
            return items
        except Exception as e:
            logger.error("新浪财经[%s]: %s", channel_name, e)
            return items

        result = data.get("result", {})
        if result.get("status", {}).get("code") != 0:
            logger.warning("新浪财经[%s]: API error %s", channel_name, result.get("status"))
            return items

        for entry in result.get("data", [])[: self.max_items]:
            title = entry.get("title", "").strip()
            if not title:
                continue

            # Pre-filter: skip categorical noise at source level
            if self._is_noise_title(title):
                logger.debug("新浪财经[%s]: skipped noise — %s", channel_name, title[:60])
                continue

            ctime = entry.get("ctime", 0)
            pub_dt = _ts_to_datetime(int(ctime)) if ctime else datetime.now()
            intro = entry.get("intro", "")
            url = entry.get("url", "")

            items.append(NewsItem(
                title=title,
                url=url or self.SINA_FEED_URL,
                source=f"新浪财经·{channel_name}",
                content_snippet=intro[:500] if intro else title,
                published_at=pub_dt,
                captured_at=datetime.now(),
            ))

        if items:
            logger.info("新浪财经[%s]: %d items fetched", channel_name, len(items))
        return items

    # ------------------------------------------------------------------
    # 华尔街见闻 7x24 快讯
    # ------------------------------------------------------------------

    WSCN_LIVES_URL = "https://api.wallstreetcn.com/apiv1/content/lives"

    async def fetch_wallstreetcn_channel(self, channel: dict) -> List[NewsItem]:
        """Fetch a single WallstreetCN live channel.

        Args:
            channel: dict with keys: channel (str), name (str)

        The API returns JSON:
          {"code": 20000, "data": {"items": [
            {"title": "...", "content_text": "...", "display_time": 1783035782,
             "id": 3128284, "symbols": [], "channels": [...]}
          ]}}
        """
        items: List[NewsItem] = []
        channel_id = channel.get("channel", "global")
        channel_name = channel.get("name", channel_id)

        session = await self._get_session()
        params = {
            "channel": channel_id,
            "limit": str(min(self.max_items, 50)),
        }

        try:
            async with session.get(
                self.WSCN_LIVES_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.warning("华尔街见闻[%s]: HTTP %d", channel_name, resp.status)
                    return items
                data = await resp.json()
        except asyncio.TimeoutError:
            logger.warning("华尔街见闻[%s]: timeout", channel_name)
            return items
        except Exception as e:
            logger.error("华尔街见闻[%s]: %s", channel_name, e)
            return items

        if data.get("code") != 20000:
            logger.warning("华尔街见闻[%s]: API error code=%s", channel_name, data.get("code"))
            return items

        for entry in data.get("data", {}).get("items", [])[: self.max_items]:
            title = entry.get("title", "").strip()
            if not title:
                continue

            # Pre-filter: skip categorical noise at source level
            if self._is_noise_title(title):
                logger.debug("华尔街见闻[%s]: skipped noise — %s", channel_name, title[:60])
                continue

            content_text = entry.get("content_text", "")
            display_time = entry.get("display_time", 0)
            pub_dt = _ts_to_datetime(int(display_time)) if display_time else datetime.now()
            symbols = entry.get("symbols", [])
            wscn_id = entry.get("id", "")

            # Build URL to the live item
            url = f"https://wallstreetcn.com/live/global/{wscn_id}" if wscn_id else self.WSCN_LIVES_URL

            # Clean HTML from content
            clean_content = _clean_html(content_text)[:500] if content_text else title

            # Extract tickers from symbols list
            tickers = ""
            if symbols:
                ticker_list = []
                for s in symbols:
                    if isinstance(s, dict):
                        sym = s.get("symbol", "")
                        if sym:
                            ticker_list.append(sym)
                    elif isinstance(s, str):
                        ticker_list.append(s)
                tickers = ",".join(ticker_list[:10])

            items.append(NewsItem(
                title=title,
                url=url,
                source=f"华尔街见闻·{channel_name}",
                content_snippet=clean_content,
                published_at=pub_dt,
                captured_at=datetime.now(),
                tickers_found=tickers,
            ))

        if items:
            logger.info("华尔街见闻[%s]: %d items fetched", channel_name, len(items))
        return items

    # ------------------------------------------------------------------
    # Bulk fetch
    # ------------------------------------------------------------------

    async def fetch_all(self) -> List[NewsItem]:
        """Fetch all configured Chinese news sources."""
        all_items: List[NewsItem] = []

        # 新浪财经 channels
        for channel in self.sina_channels:
            try:
                items = await self.fetch_sina_channel(channel)
                all_items.extend(items)
                await asyncio.sleep(self.delay)
            except Exception as e:
                logger.error("新浪财经[%s] error: %s", channel.get("name", "?"), e)

        # 华尔街见闻 channels
        for channel in self.wscn_channels:
            try:
                items = await self.fetch_wallstreetcn_channel(channel)
                all_items.extend(items)
                await asyncio.sleep(self.delay)
            except Exception as e:
                logger.error("华尔街见闻[%s] error: %s", channel.get("name", "?"), e)

        logger.info(
            "Chinese sources total: %d items from %d channels",
            len(all_items),
            len(self.sina_channels) + len(self.wscn_channels),
        )
        return all_items
