"""Tests for configuration loader."""
import pytest
import os
import tempfile
import yaml
from pathlib import Path
from config.loader import ConfigLoader, ConfigValidationError


def test_load_settings():
    loader = ConfigLoader("config")
    settings = loader.load_settings()
    assert "frequencies" in settings
    assert "fast_lane" in settings
    assert settings["frequencies"]["heartbeat"] == 60


def test_load_sources():
    loader = ConfigLoader("config")
    sources = loader.load_sources()
    assert "tier_1_rss" in sources
    assert len(sources["tier_1_rss"]) >= 5


def test_load_keywords():
    loader = ConfigLoader("config")
    keywords = loader.load_keywords()
    assert "macro_alerts" in keywords
    assert "FOMC" in keywords["macro_alerts"]
    assert "breaking_markers" in keywords
    assert "BREAKING" in keywords["breaking_markers"]


def test_env_interpolation(monkeypatch):
    monkeypatch.setenv("TEST_VAR", "test_value")
    monkeypatch.setenv("FRED_API_KEY", "test_fred_key")
    loader = ConfigLoader("config")
    # settings.yaml has ${FRED_API_KEY} etc — verify they get interpolated
    settings = loader.load_settings()
    assert settings["api_keys"]["fred"] != "${FRED_API_KEY}"  # should be resolved when env var is set


def test_cache_and_reload():
    loader = ConfigLoader("config")
    s1 = loader.load_settings()
    s2 = loader.load_settings()
    assert s1 is s2  # cached

    loader.reload()
    s3 = loader.load_settings()
    assert s1 is not s3  # new dict after reload


# ---------------------------------------------------------------------------
# Config validation tests
# ---------------------------------------------------------------------------


def _write_temp_config(tmpdir: Path, settings: dict, sources: dict = None, keywords: dict = None):
    """Write minimal config files to a temp dir for validation testing."""
    with open(tmpdir / "settings.yaml", "w") as f:
        yaml.dump(settings, f)
    if sources is not None:
        with open(tmpdir / "sources.yaml", "w") as f:
            yaml.dump(sources, f)
    if keywords is not None:
        with open(tmpdir / "keywords.yaml", "w") as f:
            yaml.dump(keywords, f)


MINIMAL_SETTINGS = {
    "frequencies": {"heartbeat": 60, "fast": 300, "normal": 900, "slow": 1800},
    "thresholds": {
        "urgent_priority": 0.7, "important_priority": 0.4,
    },
    "storage": {"sqlite_path": "data/news.db", "chroma_path": "data/chroma"},
    "deep_lane": {"llm_model": "deepseek-chat", "max_tokens": 800},
    "fast_lane": {"multi_source_count": 3, "multi_source_window": 300},
}
MINIMAL_SOURCES = {"tier_1_rss": [{"name": "test", "url": "https://example.com/rss"}]}
MINIMAL_KEYWORDS = {"macro_alerts": ["test"], "breaking_markers": ["BREAKING"]}


def test_validate_all_good(tmp_path):
    _write_temp_config(tmp_path, MINIMAL_SETTINGS, MINIMAL_SOURCES, MINIMAL_KEYWORDS)
    loader = ConfigLoader(str(tmp_path))
    issues = loader.validate()
    # Should have no structural issues (may warn about missing env vars)
    structural = [i for i in issues if "missing" in i.lower() or "must be" in i.lower()]
    assert len(structural) == 0, f"Unexpected structural issues: {structural}"


def test_validate_missing_frequencies(tmp_path):
    bad = {**MINIMAL_SETTINGS}
    bad["frequencies"] = {"heartbeat": 60}  # Missing fast, normal, slow
    _write_temp_config(tmp_path, bad, MINIMAL_SOURCES, MINIMAL_KEYWORDS)
    loader = ConfigLoader(str(tmp_path))
    issues = loader.validate()
    assert any("fast" in i for i in issues)
    assert any("normal" in i for i in issues)


def test_validate_missing_storage_key(tmp_path):
    bad = {**MINIMAL_SETTINGS}
    bad["storage"] = {"sqlite_path": "data/news.db"}  # Missing chroma_path
    _write_temp_config(tmp_path, bad, MINIMAL_SOURCES, MINIMAL_KEYWORDS)
    loader = ConfigLoader(str(tmp_path))
    issues = loader.validate()
    assert any("chroma_path" in i for i in issues)


def test_validate_missing_thresholds(tmp_path):
    bad = {**MINIMAL_SETTINGS}
    bad["thresholds"] = {"urgent_priority": 0.7}  # Missing important_priority
    _write_temp_config(tmp_path, bad, MINIMAL_SOURCES, MINIMAL_KEYWORDS)
    loader = ConfigLoader(str(tmp_path))
    issues = loader.validate()
    assert any("important_priority" in i for i in issues)


def test_validate_threshold_not_numeric(tmp_path):
    bad = {**MINIMAL_SETTINGS}
    bad["thresholds"]["urgent_priority"] = "high"  # Should be a number
    _write_temp_config(tmp_path, bad, MINIMAL_SOURCES, MINIMAL_KEYWORDS)
    loader = ConfigLoader(str(tmp_path))
    issues = loader.validate()
    assert any("expected number" in i for i in issues)


def test_validate_missing_tier1_rss(tmp_path):
    bad_sources = {}  # No tier_1_rss
    _write_temp_config(tmp_path, MINIMAL_SETTINGS, bad_sources, MINIMAL_KEYWORDS)
    loader = ConfigLoader(str(tmp_path))
    issues = loader.validate()
    assert any("tier_1_rss" in i for i in issues)


def test_validate_tier1_not_list(tmp_path):
    bad_sources = {"tier_1_rss": "not a list"}
    _write_temp_config(tmp_path, MINIMAL_SETTINGS, bad_sources, MINIMAL_KEYWORDS)
    loader = ConfigLoader(str(tmp_path))
    issues = loader.validate()
    assert any("must be a list" in i for i in issues)


def test_validate_missing_settings_file(tmp_path):
    # No settings.yaml at all
    loader = ConfigLoader(str(tmp_path))
    issues = loader.validate()
    assert any("failed to load" in i.lower() for i in issues)
