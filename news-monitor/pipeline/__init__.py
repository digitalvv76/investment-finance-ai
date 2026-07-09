"""Pipeline — chains stages sequentially with per-item error isolation."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from pipeline.item import PipelineItem

logger = logging.getLogger(__name__)


@runtime_checkable
class PipelineStage(Protocol):
    """Every pipeline stage exposes this single entry point."""
    async def process(self, items: list[PipelineItem]) -> list[PipelineItem]: ...


class Pipeline:
    """Sequential pipeline: runs items through each stage in order.

    Each stage receives the FULL list of items and returns the items
    that should continue to the next stage. Stages are responsible for
    their own per-item error isolation.
    """

    def __init__(self, stages: list[PipelineStage]) -> None:
        self._stages = stages

    async def run(self, items: list[PipelineItem]) -> list[PipelineItem]:
        if not items:
            return []
        for i, stage in enumerate(self._stages):
            stage_name = type(stage).__name__
            try:
                items = await stage.process(items)
                logger.debug("%s: %d items → %d items", stage_name,
                             len(items), len(items))
            except Exception:
                logger.exception("%s: stage-level failure", stage_name)
                # Stage-level failure: return what we have so far
                return items
            if not items:
                break
        return items
