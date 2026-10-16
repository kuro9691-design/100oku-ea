"""3 shape: the H1 wave starts at the H4 MA (docs/execution_spec.md 7-6)."""
import unittest
from datetime import datetime, timedelta, timezone

from oku100 import indicators
from oku100.models import Bar, Params, Pivot
from oku100.pipeline import DecisionPipeline, TimeframeState

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def flat_h1(count=200):
    # Close 100 (so the 80 SMA is 100) and a true range of 2 (ATR 2): band = 0.6 x 2 = 1.2.
    bars = [Bar(START + timedelta(hours=i), 100, 101, 99, 100) for i in range(count)]
    return TimeframeState(bars, count - 1, [], 1, 2.0, 100, 0, 100, 100, 0)


class WaveFromH4MaTests(unittest.TestCase):
    def setUp(self):
        for name in ("_PIVOT_CACHE", "_SMA_CACHE", "_ATR_CACHE"):
            getattr(indicators, name).clear()
        self.pipeline = DecisionPipeline()
        self.h1 = flat_h1()

    def starts(self, pivots, entry=103.0, direction=1):
        return self.pipeline._wave_starts_at_h4_ma(self.h1, pivots, entry, direction)

    def test_low_at_the_ma_passes(self):
        self.assertTrue(self.starts([Pivot(150, START, 99.5, "low")]))

    def test_low_far_below_the_ma_fails(self):
        self.assertFalse(self.starts([Pivot(150, START, 98.0, "low")]))

    def test_low_far_above_the_ma_fails(self):
        self.assertFalse(self.starts([Pivot(150, START, 101.5, "low")]))

    def test_uses_the_latest_low_below_entry(self):
        pivots = [Pivot(100, START, 99.8, "low"), Pivot(150, START, 101.5, "low")]
        self.assertFalse(self.starts(pivots))

    def test_short_mirror(self):
        self.assertTrue(self.starts([Pivot(150, START, 100.8, "high")], entry=97.0, direction=-1))
        self.assertFalse(self.starts([Pivot(150, START, 102.0, "high")], entry=97.0, direction=-1))

    def test_no_pivot_fails(self):
        self.assertFalse(self.starts([]))

    def test_flag_default_on(self):
        self.assertTrue(Params().e_wave_from_h4_ma)


if __name__ == "__main__":
    unittest.main()
