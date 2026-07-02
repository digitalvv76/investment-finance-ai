"""Knowledge base trainer — ingests URLs and documents for AI learning.

Users provide investment theses, analysis articles, or market frameworks.
The trainer fetches URL content (via aiohttp), summarizes via DeepSeek,
and stores everything for the curator to reference when scoring news.
"""
import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Optional

from storage.database import Database

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """Extract the key investment insights from this article. Focus on:
1. What sectors/stocks are discussed
2. The market thesis or analysis framework
3. How events might impact stock prices
4. Key indicators or signals mentioned

Summarize in 3-5 bullet points in Chinese. Be specific about cause-effect relationships.

Article:
{content}

Key Insights:"""


class Trainer:
    """Ingests training materials for the AI curator.

    Supports:
    - URLs: fetches page content, extracts text, summarizes via LLM
    - Text: directly stores user-provided text/summaries
    - Web search: future support for topic-based research
    """

    def __init__(self, db: Database):
        self.db = db
        self._client = None

    def _get_client(self):
        if self._client is None:
            key = os.environ.get("DEEPSEEK_API_KEY", "")
            if key:
                try:
                    from openai import OpenAI
                    self._client = OpenAI(
                        api_key=key,
                        base_url="https://api.deepseek.com",
                    )
                except ImportError:
                    pass
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ingest_url(self, url: str, title: str = "") -> int:
        """Fetch a URL, extract content, summarize, and store.

        Returns the training doc ID.
        """
        # Fetch the page
        content = await self._fetch_url(url)
        if not content:
            logger.warning("Could not fetch URL: %s", url)
            return 0

        # Generate summary via LLM
        summary = await self._summarize(content)
        if not summary:
            summary = content[:500]

        doc_id = self.db.add_training_doc(
            doc_type="url",
            source=url,
            title=title or url[:100],
            content=content[:5000],
            summary=summary,
        )
        logger.info("Trainer: ingested URL #%d (%d chars)", doc_id, len(content))
        return doc_id

    def ingest_text(self, text: str, title: str = "", source: str = "") -> int:
        """Store a text document directly.

        Returns the training doc ID.
        """
        summary = text[:500]
        doc_id = self.db.add_training_doc(
            doc_type="text",
            source=source or "manual",
            title=title or text[:80],
            content=text[:5000],
            summary=summary,
        )
        logger.info("Trainer: ingested text #%d", doc_id)
        return doc_id

    async def ingest_file(self, file_path: str, filename: str = "") -> dict:
        """Ingest a .docx, .pdf, .md, or .txt file for AI training.

        Returns a feedback dict with:
            {id, ok, word_count, summary, topics, quality_score, filename}
        """
        import os as _os
        ext = _os.path.splitext(file_path)[1].lower()

        # Extract text based on file type
        if ext == '.docx':
            text = self._extract_docx(file_path)
            doc_type = "docx"
        elif ext == '.pdf':
            text = self._extract_pdf(file_path)
            doc_type = "pdf"
        elif ext in ('.md', '.txt', '.markdown'):
            text = self._extract_text(file_path)
            doc_type = ext.lstrip('.')
        else:
            raise ValueError(f"Unsupported file type: {ext}. Use .docx, .pdf, .md, or .txt")

        if not text or len(text.strip()) < 20:
            return {
                "ok": False,
                "error": "File contains too little text to learn from (min 20 chars)",
                "word_count": len(text.split()) if text else 0,
                "filename": filename or file_path,
            }

        word_count = len(text.split())
        title = filename or file_path

        # Generate LLM summary
        summary = await self._summarize(text)
        if not summary:
            summary = text[:500]

        # Extract key topics from the text
        topics = self._extract_topics(text)

        # Store
        doc_id = self.db.add_training_doc(
            doc_type=doc_type,
            source=f"file:{filename or file_path}",
            title=title[:250],
            content=text[:8000],   # Allow more content for files
            summary=summary,
        )

        # Compute quality score
        quality_score = self._compute_quality(text, summary, topics)

        logger.info(
            "Trainer: ingested %s #%d (%d words, quality=%.1f)",
            doc_type, doc_id, word_count, quality_score,
        )

        return {
            "id": doc_id,
            "ok": True,
            "word_count": word_count,
            "summary": summary,
            "topics": topics,
            "quality_score": quality_score,
            "filename": filename or file_path,
            "doc_type": doc_type,
        }

    # ------------------------------------------------------------------
    # File extraction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(file_path: str) -> str:
        """Extract text from a plain-text file (.md, .txt, .markdown)."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='gbk') as f:
                    return f.read()
            except Exception as e:
                logger.error("Text extraction failed: %s", e)
                return ""

    @staticmethod
    def _extract_docx(file_path: str) -> str:
        """Extract text from a .docx file."""
        try:
            import docx
            doc = docx.Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return '\n'.join(paragraphs)
        except Exception as e:
            logger.error("docx extraction failed: %s", e)
            return ""

    @staticmethod
    def _extract_pdf(file_path: str) -> str:
        """Extract text from a .pdf file."""
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(file_path)
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return '\n'.join(pages)
        except Exception as e:
            logger.error("PDF extraction failed: %s", e)
            return ""

    @staticmethod
    def _extract_topics(text: str, max_topics: int = 5) -> list[str]:
        """Extract key financial topics from text via keyword matching."""
        TOPIC_PATTERNS = {
            "semiconductor": ["芯片", "半导体", "wafer", "foundry", "fab", "台积电", "TSMC", "NVIDIA", "GPU", "CPU"],
            "AI": ["artificial intelligence", "AI", "machine learning", "deep learning", "LLM", "transformer", "GPT"],
            "monetary_policy": ["interest rate", "利率", "FOMC", "Federal Reserve", "美联储", "加息", "降息", "QE"],
            "geopolitics": ["sanction", "制裁", "export control", "chip ban", "tariff", "关税", "trade war"],
            "energy": ["oil", "crude", "OPEC", "natural gas", "renewable", "solar", "石油", "能源"],
            "crypto": ["Bitcoin", "Ethereum", "crypto", "blockchain", "BTC", "ETH", "DeFi", "比特币"],
            "EV": ["Tesla", "EV", "electric vehicle", "battery", "电动车", "锂电", "BYD"],
            "pharma": ["FDA", "drug", "clinical trial", "biotech", "pharma", "疫苗", "制药"],
            "real_estate": ["housing", "mortgage", "房地产", "房价", "REIT"],
            "fintech": ["payment", "fintech", "digital bank", "支付", "金融科技"],
        }
        text_lower = text.lower()
        scores = {}
        for topic, keywords in TOPIC_PATTERNS.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > 0:
                scores[topic] = score
        return sorted(scores, key=scores.get, reverse=True)[:max_topics]

    @staticmethod
    def _compute_quality(text: str, summary: str, topics: list[str]) -> float:
        """Compute a quality score (0-10) for ingested content."""
        score = 5.0  # baseline

        word_count = len(text.split())
        # Length bonus (optimal: 200-2000 words)
        if 200 <= word_count <= 2000:
            score += 2.0
        elif 50 <= word_count < 200:
            score += 1.0
        elif word_count > 2000:
            score += 1.5

        # Topic relevance
        if topics:
            score += min(len(topics) * 0.5, 2.0)

        # Summary quality (rough heuristic: should be shorter than original)
        if summary and len(summary) < len(text) * 0.8:
            score += 0.5

        return round(min(score, 10.0), 1)

    def list_docs(self) -> list:
        """List all training documents."""
        return self.db.get_training_docs()

    def delete_doc(self, doc_id: int):
        """Delete a training document."""
        self.db.delete_training_doc(doc_id)

    def get_context(self) -> str:
        """Get all training knowledge as context for AI curation."""
        return self.db.get_training_context()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _fetch_url(self, url: str) -> str:
        """Fetch a URL and extract text content."""
        try:
            import aiohttp
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        return ""
                    html = await resp.text()

            # Simple text extraction: remove scripts, styles, HTML tags
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:10000]  # Cap at 10k chars
        except Exception as e:
            logger.error("URL fetch failed: %s", e)
            return ""

    async def _summarize(self, content: str) -> str:
        """Summarize content via DeepSeek."""
        client = self._get_client()
        if not client:
            return ""

        prompt = EXTRACT_PROMPT.format(content=content[:4000])

        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.chat.completions.create(
                        model="deepseek-chat",
                        max_tokens=400,
                        temperature=0.3,
                        messages=[{"role": "user", "content": prompt}],
                        timeout=30,  # 30s timeout per request
                    )
                ),
                timeout=45,  # 45s hard timeout for the whole operation
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error("Summarization failed: %s", e)
            return ""
