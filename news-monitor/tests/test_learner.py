"""Tests for learning engine."""
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from engine.learner import Learner


@pytest.fixture
def mock_db():
    """Create a mock database with feedback data."""
    db = MagicMock()

    # Mock _get_conn for source weight update
    mock_conn = MagicMock()
    db._get_conn.return_value.__enter__.return_value = mock_conn

    # Simulate feedback data: 5 👍 and 1 👎 for Bloomberg
    mock_conn.execute.return_value.fetchall.return_value = [
        {"source": "Bloomberg", "reaction": "thumbs_up"},
        {"source": "Bloomberg", "reaction": "thumbs_up"},
        {"source": "Bloomberg", "reaction": "thumbs_up"},
        {"source": "Bloomberg", "reaction": "thumbs_up"},
        {"source": "Bloomberg", "reaction": "thumbs_up"},
        {"source": "Bloomberg", "reaction": "thumbs_down"},
        {"source": "ZeroHedge", "reaction": "thumbs_down"},
        {"source": "ZeroHedge", "reaction": "thumbs_down"},
        {"source": "ZeroHedge", "reaction": "thumbs_down"},
        {"source": "ZeroHedge", "reaction": "thumbs_up"},
    ]

    # Mock preferences store
    prefs = {}
    def get_pref(key):
        return prefs.get(key)
    def set_pref(key, value):
        prefs[key] = value

    db.get_preference.side_effect = get_pref
    db.set_preference.side_effect = set_pref

    return db


@pytest.fixture
def learner(mock_db):
    return Learner(db=mock_db)


class TestLearner:
    """Learning engine tests."""

    def test_update_source_weights_boost(self, learner):
        """Highly upvoted source should get weight boost."""
        weights = learner.update_source_weights(feedback_window_days=7)
        assert 'Bloomberg' in weights or 'bloomberg' in weights
        # Bloomberg: 5 up / 6 total = 83% → should boost
        bloomberg_weight = weights.get('Bloomberg', weights.get('bloomberg', 0))
        assert bloomberg_weight > 0.05  # Above default

    def test_update_source_weights_demote(self, learner):
        """Heavily downvoted source should get weight demotion."""
        weights = learner.update_source_weights(feedback_window_days=7)
        # ZeroHedge: 1 up / 4 total = 25% → should demote
        zh_weight = weights.get('ZeroHedge', weights.get('zerohedge', 0))
        assert zh_weight < 0.05  # Below default

    def test_get_source_weights_initial(self, learner, mock_db):
        """Before any learning, source weights should be empty."""
        mock_db.get_preference.side_effect = lambda key: None
        weights = learner.get_source_weights()
        assert weights == {}

    def test_update_topic_weights(self, learner):
        """Topic weights should reflect engagement."""
        # Override the mock to return topic feedback
        mock_conn = learner.db._get_conn.return_value.__enter__.return_value
        mock_conn.execute.return_value.fetchall.return_value = [
            {"macro_tags": "CPI,inflation", "reaction": "thumbs_up"},
            {"macro_tags": "CPI,FOMC", "reaction": "analyze"},
            {"macro_tags": "inflation", "reaction": "thumbs_down"},
        ]

        scores = learner.update_topic_weights()
        # CPI: 2 seen, 2 engaged = 1.0
        assert 'CPI' in scores
        # inflation: 2 seen, 1 engaged = 0.5
        assert 'inflation' in scores

    def test_adjust_threshold_lowers(self, learner):
        """High engagement should lower the threshold."""
        mock_conn = learner.db._get_conn.return_value.__enter__.return_value

        def mock_execute(query, params=None):
            result = MagicMock()
            query_str = str(query)
            if 'COUNT' in query_str and 'news' in query_str:
                result.fetchone.return_value = {"cnt": 10}
            elif 'COUNT' in query_str and 'feedback' in query_str:
                result.fetchone.return_value = {"cnt": 8}
            else:
                result.fetchone.return_value = None
            return result

        mock_conn.execute.side_effect = mock_execute

        new_threshold = learner.adjust_threshold()
        # 8/10 = 80% engagement → should lower from 0.30
        assert new_threshold <= 0.30

    def test_adjust_threshold_raises(self, learner):
        """Low engagement should raise the threshold."""
        mock_conn = learner.db._get_conn.return_value.__enter__.return_value

        def mock_execute(query, params=None):
            result = MagicMock()
            query_str = str(query)
            if 'COUNT' in query_str and 'news' in query_str:
                result.fetchone.return_value = {"cnt": 10}
            elif 'COUNT' in query_str and 'feedback' in query_str:
                result.fetchone.return_value = {"cnt": 0}
            else:
                result.fetchone.return_value = None
            return result

        mock_conn.execute.side_effect = mock_execute

        new_threshold = learner.adjust_threshold()
        # 0/10 = 0% engagement → should raise from 0.30
        assert new_threshold >= 0.30

    def test_personal_dict_add_remove(self, learner):
        """Personal dictionary should support add and remove."""
        # Add keywords
        kw1 = learner.update_personal_dict("semiconductor", "add")
        assert "semiconductor" in kw1

        kw2 = learner.update_personal_dict("China tech", "add")
        assert "China tech" in kw2
        assert len(kw2) == 2

        # Remove keyword
        kw3 = learner.update_personal_dict("semiconductor", "remove")
        assert "semiconductor" not in kw3
        assert "China tech" in kw3

    def test_personal_dict_no_duplicates(self, learner):
        """Adding the same keyword twice should not duplicate."""
        kw1 = learner.update_personal_dict("AI", "add")
        kw2 = learner.update_personal_dict("AI", "add")
        assert kw2.count("AI") == 1

    def test_run_adaptation_cycle(self, learner):
        """Full adaptation cycle should run all 4 dimensions."""
        mock_conn = learner.db._get_conn.return_value.__enter__.return_value

        # Set up execute to handle both source feedback and topic queries
        def mock_execute(query, params=None):
            result = MagicMock()
            query_str = str(query)
            if 'n.source' in query_str:
                # Source weight query
                result.fetchall.return_value = [
                    {"source": "Bloomberg", "reaction": "thumbs_up"},
                    {"source": "Bloomberg", "reaction": "thumbs_up"},
                    {"source": "Bloomberg", "reaction": "thumbs_up"},
                    {"source": "Bloomberg", "reaction": "thumbs_up"},
                    {"source": "Bloomberg", "reaction": "thumbs_down"},
                ]
            elif 'n.macro_tags' in query_str:
                # Topic query
                result.fetchall.return_value = [
                    {"macro_tags": "CPI,inflation", "reaction": "thumbs_up"},
                ]
            elif 'COUNT' in query_str and 'news' in query_str:
                result.fetchone.return_value = {"cnt": 5}
            elif 'COUNT' in query_str and 'feedback' in query_str:
                result.fetchone.return_value = {"cnt": 3}
            else:
                result.fetchone.return_value = None
            return result

        mock_conn.execute.side_effect = mock_execute

        results = learner.run_adaptation_cycle()
        assert 'source_weights' in results
        assert 'topic_scores' in results
        assert 'threshold' in results
        assert 'personal_dict' in results
