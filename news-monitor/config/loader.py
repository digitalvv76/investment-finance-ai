"""Configuration loader with env var interpolation and validation."""
import logging
import os
import re
import yaml
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Required top-level keys in settings.yaml (matching actual file structure)
REQUIRED_SETTINGS_KEYS = {"frequencies", "thresholds", "storage", "deep_lane", "fast_lane"}
REQUIRED_STORAGE_KEYS = {"sqlite_path", "chroma_path"}
REQUIRED_FREQUENCY_KEYS = {"heartbeat", "fast", "normal", "slow"}
REQUIRED_THRESHOLD_KEYS = {"urgent_priority", "important_priority"}
REQUIRED_SOURCES_KEYS = {"tier_1_rss"}


class ConfigValidationError(Exception):
    """Raised when configuration fails validation."""


class ConfigLoader:
    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self._cache: Dict[str, Any] = {}

    def _load_yaml(self, filename: str) -> dict:
        path = self.config_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read()
        # Interpolate ${ENV_VAR} placeholders
        raw = self._interpolate_env(raw)
        return yaml.safe_load(raw)

    def _interpolate_env(self, text: str) -> str:
        pattern = re.compile(r'\$\{(\w+)\}')
        def replace(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        return pattern.sub(replace, text)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> List[str]:
        """Validate all config files and return a list of issues.

        Returns an empty list if everything is valid. Call this at startup
        to catch config errors before they cause runtime failures.
        """
        issues = []

        # --- settings.yaml ---
        try:
            settings = self.load_settings()
        except Exception as e:
            issues.append(f"settings.yaml: failed to load — {e}")
            return issues  # Cannot continue without settings

        # Check required top-level keys
        for key in REQUIRED_SETTINGS_KEYS:
            if key not in settings:
                issues.append(f"settings.yaml: missing required key '{key}'")

        # Check storage section
        storage = settings.get("storage", {})
        for key in REQUIRED_STORAGE_KEYS:
            if key not in storage:
                issues.append(f"settings.yaml storage: missing '{key}'")

        # Check frequencies
        freq = settings.get("frequencies", {})
        for key in REQUIRED_FREQUENCY_KEYS:
            if key not in freq:
                issues.append(f"settings.yaml frequencies: missing '{key}'")

        # Check thresholds
        thresholds = settings.get("thresholds", {})
        for key in REQUIRED_THRESHOLD_KEYS:
            if key not in thresholds:
                issues.append(f"settings.yaml thresholds: missing '{key}'")

        # Validate threshold values are numeric
        for key in REQUIRED_THRESHOLD_KEYS:
            val = thresholds.get(key)
            if val is not None and not isinstance(val, (int, float)):
                issues.append(f"settings.yaml thresholds.{key}: expected number, got {type(val).__name__}")

        # --- sources.yaml ---
        try:
            sources = self.load_sources()
        except Exception as e:
            issues.append(f"sources.yaml: failed to load — {e}")
        else:
            for key in REQUIRED_SOURCES_KEYS:
                if key not in sources:
                    issues.append(f"sources.yaml: missing required key '{key}'")
            if "tier_1_rss" in sources and not isinstance(sources["tier_1_rss"], list):
                issues.append("sources.yaml: tier_1_rss must be a list")

        # --- keywords.yaml ---
        try:
            keywords = self.load_keywords()
        except Exception as e:
            issues.append(f"keywords.yaml: failed to load — {e}")

        # --- Env var checks (warnings, not errors) ---
        if not os.environ.get("TELEGRAM_BOT_TOKEN"):
            issues.append("env: TELEGRAM_BOT_TOKEN not set — bot will be disabled")
        if not os.environ.get("DEEPSEEK_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
            issues.append("env: No LLM API key set (DEEPSEEK_API_KEY or ANTHROPIC_API_KEY)")

        # Log validation result
        if issues:
            for issue in issues:
                logger.warning("Config validation: %s", issue)
        else:
            logger.info("Config validation: all checks passed")

        return issues

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def load_settings(self) -> dict:
        if 'settings' not in self._cache:
            self._cache['settings'] = self._load_yaml('settings.yaml')
        return self._cache['settings']

    def load_sources(self) -> dict:
        if 'sources' not in self._cache:
            self._cache['sources'] = self._load_yaml('sources.yaml')
        return self._cache['sources']

    def load_keywords(self) -> dict:
        if 'keywords' not in self._cache:
            self._cache['keywords'] = self._load_yaml('keywords.yaml')
        return self._cache['keywords']

    def reload(self):
        self._cache.clear()
