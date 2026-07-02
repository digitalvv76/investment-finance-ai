"""Standalone test runner — validates config module without pytest dependency.
Mirrors the 5 test cases from test_config.py using built-in unittest.
Run with: python tests/run_config_tests.py
"""
import os
import sys
import unittest

# Ensure the news-monitor package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.loader import ConfigLoader


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.loader = ConfigLoader(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
        )

    def test_01_load_settings(self):
        """Test 1: load_settings returns expected structure."""
        settings = self.loader.load_settings()
        self.assertIn("frequencies", settings)
        self.assertIn("fast_lane", settings)
        self.assertEqual(settings["frequencies"]["heartbeat"], 60)

    def test_02_load_sources(self):
        """Test 2: load_sources returns tier_1_rss with at least 5 feeds."""
        sources = self.loader.load_sources()
        self.assertIn("tier_1_rss", sources)
        self.assertGreaterEqual(len(sources["tier_1_rss"]), 5)

    def test_03_load_keywords(self):
        """Test 3: load_keywords returns macro_alerts, breaking_markers, etc."""
        keywords = self.loader.load_keywords()
        self.assertIn("macro_alerts", keywords)
        self.assertIn("FOMC", keywords["macro_alerts"])
        self.assertIn("breaking_markers", keywords)
        self.assertIn("BREAKING", keywords["breaking_markers"])

    def test_04_env_interpolation(self):
        """Test 4: ${ENV_VAR} placeholders are interpolated from environment."""
        # Set a test variable
        os.environ["TEST_VAR"] = "test_value"
        settings = self.loader.load_settings()
        # settings.yaml has ${FRED_API_KEY} — verify it gets resolved
        fred_val = settings["api_keys"]["fred"]
        self.assertNotEqual(fred_val, "${FRED_API_KEY}",
                            "Expected $FRED_API_KEY to be interpolated, got: " + str(fred_val))

    def test_05_cache_and_reload(self):
        """Test 5: Cache returns same object; reload clears cache."""
        s1 = self.loader.load_settings()
        s2 = self.loader.load_settings()
        self.assertIs(s1, s2)  # cached — same object

        self.loader.reload()
        s3 = self.loader.load_settings()
        self.assertIsNot(s1, s3)  # new dict after reload


if __name__ == "__main__":
    unittest.main(verbosity=2)
