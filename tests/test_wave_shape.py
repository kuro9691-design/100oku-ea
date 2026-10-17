"""3 shape: the H1 wave starts at the H4 MA (docs/execution_spec.md 7-6)."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from oku100 import indicators
from oku100.models import Bar, Params, Pivot
from oku100.pipeline import DecisionPipeline, TimeframeState

START = datetime(2024, 1, 1, tzinfo=timezone.utc)
SL_AT = START + timedelta(hours=1000)


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


class WaveFromH4LineTests(unittest.TestCase):
    """3 shape (alt support): the SL pivot sits at a 4H line instead of the
    MA (execution_spec 7-6/7-3). Band = k1 x H1 ATR, same as the MA check."""

    def setUp(self):
        for name in ("_PIVOT_CACHE", "_SMA_CACHE", "_ATR_CACHE"):
            getattr(indicators, name).clear()
        self.pipeline = DecisionPipeline()
        self.h1 = flat_h1()  # H1 ATR 2 everywhere; band = 0.6 x 2 = 1.2.

    @staticmethod
    def _flat_state(count, hours_per_bar, close, pivots):
        bars = [
            Bar(START + timedelta(hours=hours_per_bar * i), close, close, close, close)
            for i in range(count)
        ]
        return TimeframeState(bars, count - 1, pivots, 0, 1.0, close, 0.0, close, close, 0.0)

    def h4(self, pivots):
        return self._flat_state(400, 4, 90.0, pivots)

    def d1(self, pivots):
        return self._flat_state(200, 24, 80.0, pivots)

    def line_pass(self, sl_pivots, h4_pivots, d1_pivots=(), rejected=None, entry=103.0, direction=1):
        rejected = rejected if rejected is not None else {p.price for p in h4_pivots}
        reaction = lambda _state, pivot: 1.0 if pivot.price in rejected else 0.0
        with patch.object(self.pipeline, "_pivot_reaction_atr", side_effect=reaction):
            return self.pipeline._wave_starts_at_h4_line(
                self.h1, self.h4(list(h4_pivots)), self.d1(list(d1_pivots)), sl_pivots, entry, direction,
            )

    def test_line_only_pass_two_touched_pivots(self):
        # SL (95.0) is far from the H1 MA (100, band 1.2) but sits on a line
        # made of two confirmed-rejected H4 pivots within k2(0.4) x ATR(1.0).
        sl = [Pivot(150, SL_AT, 95.0, "low")]
        h4_pivots = [Pivot(300, START, 95.0, "high"), Pivot(301, START + timedelta(hours=4), 95.3, "high")]
        self.assertTrue(self.line_pass(sl, h4_pivots))
        self.assertFalse(self.pipeline._wave_starts_at_h4_ma(self.h1, sl, 103.0, 1))

    def test_single_pivot_without_d1_overlap_is_not_a_line(self):
        sl = [Pivot(150, SL_AT, 95.0, "low")]
        h4_pivots = [Pivot(300, START, 95.0, "high")]
        self.assertFalse(self.line_pass(sl, h4_pivots))

    def test_d1_overlap_makes_a_line(self):
        sl = [Pivot(150, SL_AT, 95.0, "low")]
        h4_pivots = [Pivot(300, START, 95.0, "high")]
        d1_pivots = [Pivot(100, START, 95.1, "high")]
        self.assertTrue(self.line_pass(sl, h4_pivots, d1_pivots=d1_pivots))

    def test_future_line_does_not_count(self):
        # The second touch that completes the line is confirmed only after
        # the SL pivot's own confirmation time (SL_AT + N_h1 hours) -> no line yet.
        sl = [Pivot(150, SL_AT, 95.0, "low")]
        late = SL_AT + timedelta(hours=100)
        h4_pivots = [Pivot(300, START, 95.0, "high"), Pivot(301, late, 95.3, "high")]
        self.assertFalse(self.line_pass(sl, h4_pivots))

    def test_future_d1_overlap_does_not_count(self):
        sl = [Pivot(150, SL_AT, 95.0, "low")]
        h4_pivots = [Pivot(300, START, 95.0, "high")]
        late_daily = [Pivot(100, SL_AT + timedelta(hours=100), 95.1, "high")]
        self.assertFalse(self.line_pass(sl, h4_pivots, d1_pivots=late_daily))

    def test_short_mirror(self):
        sl = [Pivot(150, SL_AT, 106.0, "high")]
        h4_pivots = [Pivot(300, START, 106.0, "low"), Pivot(301, START + timedelta(hours=4), 105.7, "low")]
        self.assertTrue(self.line_pass(sl, h4_pivots, entry=97.0, direction=-1))

    def test_ma_and_line_can_both_pass(self):
        # SL at the H4 MA (100, band 1.2) and also on a confirmed line.
        sl = [Pivot(150, SL_AT, 100.2, "low")]
        h4_pivots = [Pivot(300, START, 100.2, "high"), Pivot(301, START + timedelta(hours=4), 100.5, "high")]
        self.assertTrue(self.pipeline._wave_starts_at_h4_ma(self.h1, sl, 103.0, 1))
        self.assertTrue(self.line_pass(sl, h4_pivots))


if __name__ == "__main__":
    unittest.main()
