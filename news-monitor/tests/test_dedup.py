"""Tests for dedup manager."""
import pytest
from collector.dedup import DedupManager
from storage.models import NewsItem


@pytest.fixture
def dedup():
    return DedupManager()


class TestDedupManager:
    """Deduplication tests."""

    def test_exact_url_duplicate(self, dedup):
        """Same URL should be detected as duplicate."""
        item1 = NewsItem(
            title="Market update",
            url="https://example.com/news/123",
            source="Test",
        )
        item2 = NewsItem(
            title="Market update (slightly different title)",
            url="https://example.com/news/123",
            source="Test",
        )

        # First should not be duplicate
        assert not dedup.is_duplicate(item1)
        # Second with same URL should be duplicate
        assert dedup.is_duplicate(item2)

    def test_url_tracking_params_normalized(self, dedup):
        """URLs differing only in tracking params should match."""
        item1 = NewsItem(
            title="Breaking news",
            url="https://example.com/news?utm_source=twitter&ref=home",
            source="Test",
        )
        item2 = NewsItem(
            title="Breaking news",
            url="https://example.com/news",
            source="Test",
        )
        assert not dedup.is_duplicate(item1)
        assert dedup.is_duplicate(item2)

    def test_content_hash_duplicate(self, dedup):
        """Same content should be detected via hash."""
        item1 = NewsItem(
            title="Fed raises rates by 25bp",
            url="https://source-a.com/article",
            content_snippet="The Federal Reserve announced a 25 basis point rate hike today.",
            source="Source A",
        )
        item2 = NewsItem(
            title="Fed raises rates by 25bp",
            url="https://source-b.com/different-url",
            content_snippet="The Federal Reserve announced a 25 basis point rate hike today.",
            source="Source B",
        )

        assert not dedup.is_duplicate(item1)
        assert dedup.is_duplicate(item2)

    def test_different_content_not_duplicate(self, dedup):
        """Different articles should not be flagged."""
        item1 = NewsItem(
            title="Fed raises rates",
            url="https://example.com/fed-rates",
            content_snippet="Fed announces rate hike.",
            source="Test",
        )
        item2 = NewsItem(
            title="Tech stocks rally",
            url="https://example.com/tech-rally",
            content_snippet="Tech stocks surge on earnings.",
            source="Test",
        )

        assert not dedup.is_duplicate(item1)
        assert not dedup.is_duplicate(item2)

    def test_filter_duplicates(self, dedup):
        """Batch filter should remove duplicates."""
        items = [
            NewsItem(title="A", url="https://x.com/1", source="T"),
            NewsItem(title="B", url="https://x.com/2", source="T"),
            NewsItem(title="A", url="https://x.com/1", source="T"),  # dup
            NewsItem(title="C", url="https://x.com/3", source="T"),
        ]
        filtered = dedup.filter_duplicates(items)
        assert len(filtered) == 3

    def test_title_similarity_identical(self, dedup):
        """Identical titles should have similarity 1.0."""
        score = dedup.title_similarity(
            "Fed raises interest rates by 25 basis points",
            "Fed raises interest rates by 25 basis points",
        )
        assert score == 1.0

    def test_title_similarity_different(self, dedup):
        """Completely different titles should have low similarity."""
        score = dedup.title_similarity(
            "Apple announces new iPhone",
            "Federal Reserve cuts interest rates",
        )
        assert score < 0.3

    def test_title_similarity_related(self, dedup):
        """Titles about the same event with different wording."""
        score = dedup.title_similarity(
            "Fed raises rates by 25 basis points amid inflation concerns",
            "Federal Reserve hikes interest rates 25bp on inflation worries",
        )
        # Some word overlap expected
        assert score > 0.1

    def test_is_similar(self, dedup):
        """is_similar should use title similarity threshold."""
        item1 = NewsItem(
            title="BREAKING: NVDA reports record earnings",
            url="https://x.com/1",
            source="T",
        )
        item2 = NewsItem(
            title="NVDA reports record earnings beat",
            url="https://x.com/2",
            source="T",
        )
        assert dedup.is_similar(item1, item2, threshold=0.5)

    def test_existing_urls_check(self, dedup):
        """Pre-loaded existing URLs should be checked."""
        dedup.load_existing_urls(["https://example.com/old-article"])

        item = NewsItem(
            title="Old article",
            url="https://example.com/old-article",
            source="Test",
        )
        assert dedup.is_duplicate(item)

    def test_empty_items(self, dedup):
        """Empty item list should return empty."""
        assert dedup.filter_duplicates([]) == []


class TestBatchSemanticDedupPerformance:
    """Root-cause guard: within-batch semantic dedup must encode each text
    ONCE (O(N)), not re-encode per pair (O(N^2)).

    Regression: a 156-item cold-start batch made ~12k pair_similarity calls,
    each re-encoding via SentenceTransformer (~120ms), blocking the event
    loop ~24 min → zero ingestion (the shadow "stall" bug, 2026-07-10).
    """

    class _FakeVS:
        is_ready = True

        def __init__(self):
            self.embed_calls = 0

        def _embed(self, text):
            self.embed_calls += 1
            return (text,)  # identity vector; distinct texts → not similar

        def embed_batch(self, texts):
            return [self._embed(t) for t in texts]

        @staticmethod
        def cosine(a, b):
            return 1.0 if a == b else 0.0

        def is_semantic_duplicate(self, text, threshold=0.9):
            return False

        def pair_similarity(self, a, b):  # the O(N^2) hot path (pre-fix)
            self._embed(a)
            self._embed(b)
            return 0.0

    def test_batch_dedup_is_linear_not_quadratic(self):
        vs = self._FakeVS()
        dedup = DedupManager(vector_store=vs)
        N = 40
        items = [
            NewsItem(title=f"distinct alpha{i} bravo{i} charlie{i} delta{i}",
                     url=f"https://x.com/{i}", source="T",
                     content_snippet=f"body echo{i} foxtrot{i}")
            for i in range(N)
        ]
        kept = dedup.filter_duplicates(items)
        assert len(kept) == N  # all distinct → all kept
        # O(N): each item's text encoded ~once. Pre-fix this was ~N^2 (1600+).
        assert vs.embed_calls <= 3 * N, (
            f"embed called {vs.embed_calls} times for N={N} — expected O(N), "
            f"got quadratic (re-encoding per pair)")
