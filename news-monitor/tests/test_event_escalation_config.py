# tests/test_event_escalation_config.py
from config.loader import ConfigLoader


def test_load_event_escalation_defaults():
    cfg = ConfigLoader().load_event_escalation()
    assert cfg["alert_trigger"]["min_source_count"] == 3
    assert cfg["alert_trigger"]["min_peak_impact"] == 70
    assert cfg["market_confirm"]["spx_pct"] == 0.2
    assert cfg["market_confirm"]["vix_pct"] == 5.0
    assert cfg["market_confirm"]["brent_pct"] == 0.5
    assert cfg["close"]["silence_hours"] == 6
    assert cfg["cooldown_hours"] == 3
    assert cfg["max_pushes_per_event"] == 3
