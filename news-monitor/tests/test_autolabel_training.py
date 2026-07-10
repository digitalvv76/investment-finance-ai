"""Tests for autolabel_training core mapping (ground-truth move% → intensity)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from autolabel_training import move_to_intensity


class TestMoveToIntensity:
    def test_sector_level_surge_is_5(self):
        # Marvell +32.5%, quantum +30~33% → 板块级暴涨
        assert move_to_intensity(32.5) == 5
        assert move_to_intensity(-18.0) == 5   # 大幅下跌同样是强催化(做空向)

    def test_single_stock_surge_is_4(self):
        # Nokia +20%, IBM +12%, Rigetti +15% → 个股大概率暴涨
        assert move_to_intensity(12.0) == 4
        assert move_to_intensity(-8.78) == 4   # 高通 N1X 当日 -8.78%

    def test_clear_move_is_3(self):
        # QCOM +8% intraday / 明显异动
        assert move_to_intensity(4.7) == 3
        assert move_to_intensity(-3.0) == 3

    def test_mild_is_2(self):
        assert move_to_intensity(2.0) == 2
        assert move_to_intensity(-1.6) == 2

    def test_noise_is_1(self):
        assert move_to_intensity(0.4) == 1
        assert move_to_intensity(-1.0) == 1

    def test_missing_move_is_none(self):
        assert move_to_intensity(None) is None
