"""Tests for IngestStage."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.ingest import IngestStage
from pipeline.item import PipelineItem


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.insert_news = MagicMock(return_value=42)
    return db


@pytest.fixture
def mock_dedup():
    dedup = MagicMock()
    dedup.filter_duplicates = MagicMock(side_effect=lambda items: items)
    dedup.index_item = MagicMock()
    return dedup


@pytest.fixture
def mock_vector():
    vec = MagicMock()
    vec.add_article = MagicMock()
    return vec


@pytest.fixture
def stage(mock_db, mock_dedup, mock_vector):
    return IngestStage(db=mock_db, dedup=mock_dedup, vector_store=mock_vector)


class TestIngestStage:

    @pytest.mark.asyncio
    async def test_happy_path(self, stage, mock_dedup, mock_db, mock_vector):
        """Normal items pass through dedup → insert → index."""
        items = [
            PipelineItem(id=0, title="News 1", source="src1", url="http://a.com/1", snippet="s1"),
            PipelineItem(id=0, title="News 2", source="src2", url="http://a.com/2", snippet="s2"),
        ]
        result = await stage.process(items)

        assert len(result) == 2
        assert result[0].id == 42  # mock returns 42
        assert result[1].id == 42
        assert mock_dedup.filter_duplicates.called
        assert mock_db.insert_news.call_count == 2
        # After fix: vector_store.add_article is used instead of dedup.index_item
        assert mock_vector.add_article.call_count == 2

    @pytest.mark.asyncio
    async def test_single_item_failure_isolation(self, stage, mock_db):
        """One item failing DB insert doesn't block others."""
        mock_db.insert_news = MagicMock(side_effect=[Exception("DB down"), 99])

        items = [
            PipelineItem(id=0, title="Bad", source="s", url="http://a.com/1", snippet="s"),
            PipelineItem(id=0, title="Good", source="s", url="http://a.com/2", snippet="s"),
        ]
        result = await stage.process(items)

        assert len(result) == 1
        assert result[0].title == "Good"
        assert result[0].id == 99

    @pytest.mark.asyncio
    async def test_empty_input(self, stage):
        result = await stage.process([])
        assert result == []

    @pytest.mark.asyncio
    async def test_all_duplicates_filtered(self, stage, mock_dedup):
        """When dedup removes everything, return empty list."""
        mock_dedup.filter_duplicates = MagicMock(return_value=[])

        items = [PipelineItem(id=0, title="Dup", source="s", url="http://a.com/1", snippet="s")]
        result = await stage.process(items)

        assert result == []

    @pytest.mark.asyncio
    async def test_skip_db_duplicate(self, stage, mock_db, mock_vector):
        """INSERT OR IGNORE returns 0 → item skipped (not pushed to pipeline)."""
        mock_db.insert_news = MagicMock(return_value=0)  # IGNORE → lastrowid=0

        items = [
            PipelineItem(id=0, title="Already in DB", source="s", url="http://a.com/1", snippet="s"),
            PipelineItem(id=0, title="New item", source="s", url="http://a.com/2", snippet="s2"),
        ]
        # Second insert succeeds
        mock_db.insert_news = MagicMock(side_effect=[0, 99])

        result = await stage.process(items)

        assert len(result) == 1
        assert result[0].id == 99
        assert result[0].title == "New item"
        assert mock_vector.add_article.call_count == 1  # only indexed the survivor
