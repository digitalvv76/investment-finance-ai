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
