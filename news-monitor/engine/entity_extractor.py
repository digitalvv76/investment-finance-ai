"""Entity extraction using spaCy NER + rule-based patterns."""
import logging
import re
from typing import Dict, List, Set

import spacy

from config.loader import ConfigLoader

logger = logging.getLogger(__name__)

# Fallback tickers for when config is unavailable
FALLBACK_TICKERS = {
    # US equities — core
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
    "AMD", "INTC", "BA", "JPM", "GS", "WMT", "XOM", "CVX",
    "NFLX", "CRM", "ORCL", "ADBE", "PYPL", "DIS", "NKE",
    # Watchlist — semiconductors / AI
    "PLTR", "SOXX", "SOXL", "LRCX", "ARM", "MRVL",
    "MRAAY", "CBRS",
    # Watchlist — space / defense
    "SPCX", "RKLB", "KTOS", "ASTS",
    # Watchlist — quantum / nuclear / emerging tech
    "RGTI", "OKLO", "SMR", "TEM", "NBIS",
    # Watchlist — ETFs / other
    "BOT", "ARKK",
    # Crypto-exposed US equities (publicly traded stocks, NOT crypto tokens)
    "COIN", "MSTR", "RIOT", "MARA", "CLSK", "HUT", "WULF",
    # Fintech / payments (relevant to regulatory/licensing news)
    "SQ", "AFRM", "SOFI", "HOOD",
}


class EntityExtractor:
    """Extract financial entities from news text.

    Combines three extraction strategies:
    1. spaCy NER for company names (ORG) and people (PERSON)
    2. Regex patterns for ticker symbols ($AAPL or bare AAPL)
    3. Keyword dictionary matching for macro indicators and sectors
    """

    def __init__(self, config: ConfigLoader = None):
        self.keywords: dict = {}
        if config:
            try:
                self.keywords = config.load_keywords()
            except Exception:
                pass

        # Lazy-load spaCy — only when first extract() is called
        self._nlp = None

        # Compile ticker regex — matches $AAPL or bare uppercase 1-5 chars.
        # Uses (?<![A-Z])…(?![A-Z]) instead of \b because Python 3 treats
        # CJK characters as \w, breaking word-boundary detection for Chinese
        # text like "批准XRP现货".
        self._ticker_re = re.compile(r'(?<![A-Z])\$?([A-Z]{1,5})(?![A-Z])')
        # Company-name → ticker map for crypto/fintech entities that often
        # appear in news with their full name rather than the stock symbol.
        self._company_to_ticker = {
            # Major tech — names often appear in headlines instead of tickers
            "nvidia": "NVDA", "apple": "AAPL", "microsoft": "MSFT",
            "google": "GOOGL", "alphabet": "GOOGL", "amazon": "AMZN",
            "meta": "META", "tesla": "TSLA", "palantir": "PLTR",
            "intel": "INTC", "amd": "AMD", "broadcom": "AVGO",
            "marvell": "MRVL", "lam research": "LRCX",
            "arm holdings": "ARM", "arm": "ARM",
            "rocket lab": "RKLB", "spacex": "SPCX",
            # Crypto-exposed equities (publicly traded)
            "coinbase": "COIN", "microstrategy": "MSTR",
            "riot blockchain": "RIOT", "riot platforms": "RIOT",
            "marathon digital": "MARA", "marathon": "MARA",
            "cleanspark": "CLSK", "hut 8": "HUT",
            # Fintech
            "block": "SQ", "square": "SQ",
            "affirm": "AFRM", "sofi": "SOFI",
            "robinhood": "HOOD",
            # Nuclear / energy
            "oklo": "OKLO", "nuscale": "SMR",
            # Space / defense
            "kratos": "KTOS", "ast spacemobile": "ASTS",
            "rigetti": "RGTI", "tempus": "TEM", "nebis": "NBIS",
            # ETFs
            "ark innovation": "ARKK",
        }

        # Known entities from keywords config
        self._known_people: Set[str] = set(self.keywords.get('key_people', []))
        self._known_macro: Set[str] = set(self.keywords.get('macro_alerts', []))
        self._sectors: Dict[str, List[str]] = self.keywords.get('sectors', {})

        # Build sector keyword → sector name reverse map
        self._kw_to_sector: Dict[str, str] = {}
        for sector_name, kws in self._sectors.items():
            for kw in kws:
                self._kw_to_sector[kw.lower()] = sector_name

    @property
    def nlp(self):
        """Lazy-load spaCy model on first access."""
        if self._nlp is None:
            try:
                self._nlp = spacy.load("en_core_web_sm")
            except OSError:
                logger.warning(
                    "spaCy model 'en_core_web_sm' not found. "
                    "Run: python -m spacy download en_core_web_sm"
                )
                # Return a blank English pipeline as fallback
                self._nlp = spacy.blank("en")
        return self._nlp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, text: str) -> Dict[str, List[str]]:
        """Extract all entity types from text.

        Returns:
            {
                "tickers": ["NVDA", "AAPL"],
                "companies": ["Nvidia Corp", "Apple Inc"],
                "people": ["Kevin Warsh", "Jensen Huang"],
                "indicators": ["CPI", "Federal Reserve"],
                "sectors": ["semiconductor", "tech"],
            }
        """
        result: Dict[str, List[str]] = {
            "tickers": [],
            "companies": [],
            "people": [],
            "indicators": [],
            "sectors": [],
        }

        # 1. Rule-based ticker extraction (fast, no NLP needed)
        tickers = self._extract_tickers(text)
        result["tickers"] = list(tickers)

        # 2. spaCy NER for companies and people
        try:
            doc = self.nlp(text[:3000])  # Cap for performance
            for ent in doc.ents:
                name = ent.text.strip()
                if not name or len(name) < 2:
                    continue
                if ent.label_ == "ORG" and name not in result["companies"]:
                    result["companies"].append(name)
                elif ent.label_ == "PERSON" and name not in result["people"]:
                    result["people"].append(name)
        except Exception as e:
            logger.debug(f"spaCy NER error (non-fatal): {e}")

        # 3. Keyword dictionary matching for indicators and sectors
        text_lower = text.lower()
        for kw in self._known_macro:
            if kw.lower() in text_lower and kw not in result["indicators"]:
                result["indicators"].append(kw)

        for kw, sector in self._kw_to_sector.items():
            if kw in text_lower and sector not in result["sectors"]:
                result["sectors"].append(sector)

        # 4. Dictionary-based people detection (catches names spaCy misses)
        for person in self._known_people:
            if person.lower() in text_lower and person not in result["people"]:
                result["people"].append(person)

        return result

    # ------------------------------------------------------------------
    # Internal extraction helpers
    # ------------------------------------------------------------------

    def _extract_tickers(self, text: str) -> Set[str]:
        """Extract uppercase ticker symbols from text.

        Three extraction strategies:
        1. Regex: $AAPL or bare uppercase 1-5 chars (validated against watchlist/fallback)
        2. Company-name → ticker mapping: "Ripple" → XRP, "Coinbase" → COIN
        """
        found: Set[str] = set()
        watchlist = self._load_watchlist()
        text_lower = text.lower()

        # 1. Regex-based extraction
        for match in self._ticker_re.finditer(text):
            ticker = match.group(1)
            # Accept if on watchlist or preceded by $
            if ticker in watchlist or match.group(0).startswith('$'):
                found.add(ticker)
            # Also accept if it's a well-known ticker
            elif ticker in FALLBACK_TICKERS:
                found.add(ticker)

        # 2. Company-name → ticker mapping (for crypto/fintech)
        for company_name, ticker in self._company_to_ticker.items():
            if company_name in text_lower and ticker in FALLBACK_TICKERS:
                found.add(ticker)

        return found

    def _load_watchlist(self) -> Set[str]:
        """Load watchlist tickers from memory file."""
        tickers = set(FALLBACK_TICKERS)
        try:
            from pathlib import Path
            for memfile in [
                "../../.claude/memory/watchlist-state.md",
                "../.claude/memory/watchlist-state.md",
            ]:
                path = Path(__file__).parent / memfile
                if path.exists():
                    text = path.read_text()
                    found = re.findall(r'\|\s*([A-Z]{1,5})\s*\|', text)
                    tickers.update(t for t in found if t.isalpha())
        except Exception:
            pass
        return tickers
