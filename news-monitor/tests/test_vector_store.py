"""Tests for vector store — skip if ChromaDB not installed."""
import pytest

# Try importing; skip all tests if dependencies unavailable
try:
    import chromadb
    import sentence_transformers
    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False

pytestmark = pytest.mark.skipif(not DEPS_AVAILABLE, reason="chromadb or sentence-transformers not installed")

from storage.vector_store import VectorStore
import tempfile
import os


@pytest.fixture
def vector_store():
    """Create a temporary vector store for testing.

    ChromaDB keeps files memory-mapped, so we explicitly close the store before
    the temp dir is removed and tolerate any lingering-handle cleanup errors
    (Windows [WinError 32]) rather than failing teardown.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        store = VectorStore(persist_path=tmpdir)
        store.initialize()
        try:
            yield store
        finally:
            store.clear()
            store.close()


class TestVectorStore:
    """Vector store tests — requires ChromaDB + sentence-transformers."""

    def test_initialize(self, vector_store):
        """Initialization should set up ChromaDB and model."""
        assert vector_store._client is not None
        # Model may not load if sentence-transformers fails; store gracefully
        assert vector_store._collection is not None

    def test_add_and_search(self, vector_store):
        """Adding and finding articles by semantic similarity."""
        if not vector_store.is_ready:
            pytest.skip("Embedding model not available")

        # Add an article
        assert vector_store.add_article(
            1,
            "Federal Reserve raises interest rates by 25 basis points amid inflation concerns",
            {"source": "Bloomberg", "tickers": ""}
        )
        assert vector_store.count() >= 1

        # Search for similar
        similar = vector_store.find_similar(
            "Fed hikes rates 25bp as inflation worries persist",
            threshold=0.6,
        )
        # Should find the original article
        assert 1 in similar

    def test_semantic_duplicate_detection(self, vector_store):
        """Very similar text should be detected as duplicate."""
        if not vector_store.is_ready:
            pytest.skip("Embedding model not available")

        vector_store.add_article(1, "Apple announces new iPhone with revolutionary AI features", {})

        # Nearly identical text
        is_dup = vector_store.is_semantic_duplicate(
            "Apple unveils new iPhone with groundbreaking AI capabilities",
            threshold=0.70,
        )
        assert is_dup

    def test_different_topics_not_duplicate(self, vector_store):
        """Different topics should not trigger duplicate detection."""
        if not vector_store.is_ready:
            pytest.skip("Embedding model not available")

        vector_store.add_article(1, "Federal Reserve raises interest rates", {})

        is_dup = vector_store.is_semantic_duplicate(
            "Local sports team wins championship in overtime thriller",
            threshold=0.70,
        )
        assert not is_dup

    def test_empty_collection_search(self, vector_store):
        """Search on empty collection should return empty."""
        similar = vector_store.find_similar("anything")
        assert similar == []

    def test_delete_article(self, vector_store):
        """Deleting an article should remove it."""
        if not vector_store.is_ready:
            pytest.skip("Embedding model not available")

        vector_store.add_article(1, "Test article for deletion", {})
        assert vector_store.count() >= 1

        vector_store.delete_article(1)
        # After deletion, search should not find it
        similar = vector_store.find_similar("Test article for deletion", threshold=0.95)
        assert 1 not in similar

    def test_uninitialized_store(self):
        """Uninitialized store should handle calls gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = VectorStore(persist_path=tmpdir)
            assert not store.is_ready
            assert store.find_similar("test") == []
            assert store.count() == 0
            assert store.is_semantic_duplicate("test") is False
