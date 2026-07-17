"""Test Graham reviewer — value-investing pre-dispatch safety net."""
import pytest
from engine.graham_reviewer import GrahamReviewer, GrahamVerdict


class TestGrahamParser:
    """JSON parsing from LLM output."""

    def test_parse_push_all_pass(self):
        v = GrahamReviewer._parse(
            '{"verdict": "PUSH", "failures": [], "note": "ok"}'
        )
        assert v is not None
        assert v.verdict == "PUSH"
        assert v.failures == []
        assert v.note == "ok"

    def test_parse_drop_three_failures(self):
        v = GrahamReviewer._parse(
            '{"verdict": "DROP", "failures": [1, 3, 5], "note": "bad"}'
        )
        assert v is not None
        assert v.verdict == "DROP"
        assert v.failures == [1, 3, 5]

    def test_parse_silent_two_failures(self):
        v = GrahamReviewer._parse(
            '{"verdict": "SILENT", "failures": [2, 4], "note": "meh"}'
        )
        assert v is not None
        assert v.verdict == "SILENT"
        assert v.failures == [2, 4]

    def test_parse_markdown_code_fence(self):
        v = GrahamReviewer._parse(
            '```json\n{"verdict": "PUSH", "failures": [], "note": "ok"}\n```'
        )
        assert v is not None
        assert v.verdict == "PUSH"

    def test_parse_embedded_json_in_text(self):
        v = GrahamReviewer._parse(
            'Some preamble text \n{"verdict": "DROP", "failures": [2], "note": "bad"}\n more text'
        )
        assert v is not None
        assert v.verdict == "DROP"

    def test_parse_verdict_case_insensitive(self):
        v = GrahamReviewer._parse(
            '{"verdict": "push", "failures": [], "note": "ok"}'
        )
        assert v is not None
        assert v.verdict == "PUSH"

    def test_parse_invalid_verdict_returns_none(self):
        v = GrahamReviewer._parse(
            '{"verdict": "UPGRADE", "failures": [], "note": "nope"}'
        )
        assert v is None

    def test_parse_missing_verdict_returns_none(self):
        v = GrahamReviewer._parse(
            '{"failures": [], "note": "no verdict"}'
        )
        assert v is None

    def test_parse_failure_numbers_out_of_range_filtered(self):
        v = GrahamReviewer._parse(
            '{"verdict": "DROP", "failures": [0, 2, 6], "note": "bad"}'
        )
        assert v is not None
        assert v.failures == [2]  # 0 and 6 filtered out

    def test_parse_note_truncated(self):
        long_note = "x" * 300
        v = GrahamReviewer._parse(
            f'{{"verdict": "PUSH", "failures": [], "note": "{long_note}"}}'
        )
        assert v is not None
        assert len(v.note) <= 200

    def test_parse_non_json_returns_none(self):
        v = GrahamReviewer._parse("not json at all")
        assert v is None


class TestGrahamStageLogic:
    """Test the downgrade logic used by GrahamStage (pure function)."""

    @staticmethod
    def _apply(failures: list[int], original_level: str) -> str | None:
        """Mirror of GrahamStage.process downgrade logic."""
        n = len(failures)
        if n >= 3:
            return "NORMAL"
        elif n >= 2:
            return "NOTABLE"
        else:
            return None  # maintain

    def test_zero_failures_maintains(self):
        assert self._apply([], "IMPORTANT") is None

    def test_one_failure_maintains(self):
        assert self._apply([2], "IMPORTANT") is None

    def test_two_failures_silent(self):
        assert self._apply([2, 4], "IMPORTANT") == "NOTABLE"

    def test_three_failures_drop(self):
        assert self._apply([1, 3, 5], "CRITICAL") == "NORMAL"

    def test_four_failures_drop(self):
        assert self._apply([1, 2, 3, 4], "IMPORTANT") == "NORMAL"


class TestGrahamBuildUserText:
    """Verify prompt assembly for LLM calls."""

    def test_full_fields(self):
        r = GrahamReviewer()
        text = r._build_user_text(
            title="Test headline",
            snippet="This is a test snippet about CPI data.",
            source="Reuters",
            tickers="AAPL,NVDA",
            macro_tags="CPI,Macro",
        )
        assert "Test headline" in text
        assert "CPI data" in text
        assert "Reuters" in text
        assert "AAPL,NVDA" in text
        assert "CPI,Macro" in text

    def test_minimal_fields(self):
        r = GrahamReviewer()
        text = r._build_user_text(
            title="Short headline", snippet="", source="", tickers="", macro_tags="",
        )
        assert "Short headline" in text
        assert "摘要" not in text
        assert "来源" not in text
        assert "涉及标的" not in text
        assert "宏观标签" not in text

    def test_snippet_truncated(self):
        r = GrahamReviewer()
        long_snippet = "x" * 500
        text = r._build_user_text(
            title="T", snippet=long_snippet, source="", tickers="", macro_tags="",
        )
        # Snippet should be truncated to 300 chars
        snippet_part = text.split("摘要：")[1]
        assert len(snippet_part) <= 300
