"""Tests for Twitter/X fetcher (Playwright + auth cookie)."""
import pytest
from collector.twitter_fetcher import TwitterFetcher, _generate_ct0, _load_auth_token


def test_generate_ct0():
    """ct0 is a 32-char hex string derived from auth_token."""
    ct0 = _generate_ct0("test_token_123")
    assert len(ct0) == 32
    assert all(c in "0123456789abcdef" for c in ct0)
    # Deterministic
    assert ct0 == _generate_ct0("test_token_123")


def test_generate_ct0_empty():
    """Empty token still produces a hash."""
    ct0 = _generate_ct0("")
    assert len(ct0) == 32


def test_load_auth_token_from_config():
    """auth_token is read from config dict."""
    token = _load_auth_token({"auth_token": "abc123"})
    assert token == "abc123"


def test_load_auth_token_empty_config():
    """Returns empty string when no config or env var."""
    import os
    old = os.environ.pop("TWITTER_AUTH_TOKEN", None)
    try:
        token = _load_auth_token({})
        assert token == ""
    finally:
        if old:
            os.environ["TWITTER_AUTH_TOKEN"] = old


def test_twitter_fetcher_init():
    """Fetcher initializes with config."""
    fetcher = TwitterFetcher({
        "accounts": ["@testuser"],
        "auth_token": "test123",
        "max_items_per_account": 5,
        "request_delay_seconds": 1.0,
    })
    assert fetcher.accounts == ["@testuser"]
    assert fetcher.auth_token == "test123"
    assert fetcher.max_items == 5


def test_twitter_fetcher_empty():
    """Fetcher handles empty config."""
    fetcher = TwitterFetcher({})
    assert fetcher.accounts == []
    assert fetcher.max_items == 5  # default


@pytest.mark.asyncio
async def test_fetch_all_without_startup():
    """fetch_all returns empty if browser not started."""
    fetcher = TwitterFetcher({
        "accounts": ["@test"],
        "auth_token": "test123",
    })
    items = await fetcher.fetch_all()
    assert items == []


@pytest.mark.asyncio
async def test_fetch_all_empty_accounts():
    """Empty account list returns empty."""
    fetcher = TwitterFetcher({
        "accounts": [],
        "auth_token": "test123",
    })
    items = await fetcher.fetch_all()
    assert items == []
