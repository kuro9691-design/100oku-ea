"""SL from the pivots confirmed by the bar before the fill (docs/execution_spec.md 5-1)."""
import unittest

from oku100 import indicators
from oku100.indicators import confirmed_pivots
from oku100.models import Params, Pivot
from oku100.pipeline import DecisionPipeline, TimeframeState, _latest_pivot_beyond
from tests.helpers import bars


def clear_caches():
    for name in ("_PIVOT_CACHE", "_SMA_CACHE", "_ATR_CACHE"):
        getattr(indicators, name).clear()


class StopPivotsArgumentTests(unittest.TestCase):
    def test_stop_pivots_override_order_time_pivots(self):
        clear_caches()
        pipeline = DecisionPipeline()
        d1, h4, h1 = bars(220, 24, 0.8), bars(400, 4, 0.4), bars(1000, 1)
        states = pipeline._states((d1, h4, h1), (200, 380, 990))
        override = [Pivot(0, h1[0].timestamp, 1.0, "low"), Pivot(1, h1[1].timestamp, 2.0, "low")]
        result = pipeline._score_direction(1, *states, 0, stop_entry=None, stop_pivots=override)
        self.assertEqual(result["stop"], 2.0)


class FillTimeStopTests(unittest.TestCase):
    def setUp(self):
        clear_caches()
        self.d1, self.h4, self.h1 = bars(60, 24, 0.8), bars(100, 4, 0.4), bars(240, 1)

    def fills(self, params):
        pipeline = DecisionPipeline(params)
        probe = TimeframeState(self.h1, len(self.h1) - 1, [], 0, 1, 100, 0, 100, 100, 0)
        found = []
        for direction in (1, -1):
            pipeline._stop_entry_fill(probe, direction)
            order = pipeline._stop_order_cache[(id(self.h1), direction)]
            found += [(i, direction, order["fill_placed_at"][i]) for i in order["fills"]]
        return sorted(item for item in found if item[0] >= 48 and item[2] >= 48)

    def score(self, params, index, direction):
        clear_caches()
        pipeline = DecisionPipeline(params)
        indexes = pipeline._resolve_indexes(self.d1, self.h4, self.h1, self.h1[index].timestamp)
        states = pipeline._states((self.d1, self.h4, self.h1), indexes)
        return pipeline._score_at_order_time(direction, *states, 0)

    def check(self, params, reference):
        checked = 0
        for index, direction, placed_at in self.fills(params):
            result = self.score(params, index, direction)
            pivots = confirmed_pivots(self.h1, reference(index, placed_at), 3)
            self.assertEqual(result["stop"], _latest_pivot_beyond(pivots, result["entry"], direction))
            checked += 1
        return checked

    def test_stop_is_latest_pivot_confirmed_before_fill_bar(self):
        self.assertTrue(self.check(Params(), lambda index, placed_at: index - 1))

    def test_order_time_stop_when_disabled(self):
        self.assertTrue(self.check(Params(sl_at_fill=False), lambda index, placed_at: placed_at))



class NewerPivotBeforeFillTests(unittest.TestCase):
    """A higher low confirmed after placement but before the fill bar becomes the SL."""

    def setUp(self):
        clear_caches()

    def path(self):
        from datetime import datetime, timedelta, timezone
        from oku100.models import Bar
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        lows = [100, 99, 98, 95, 98, 99, 100, 101, 102, 101, 100, 99, 97, 99, 100, 101, 102, 103, 104, 105]
        return [Bar(start + timedelta(hours=i), low + 1, low + 2, low, low + 1) for i, low in enumerate(lows)]

    def captured_stop(self, params):
        from unittest.mock import patch
        h1_bars = self.path()
        fill_index, placed_at = 19, 9
        pipeline = DecisionPipeline(params)
        h1 = TimeframeState(h1_bars, fill_index, [], 1, 1, 100, 0, 100, 100, 0)
        order_h1 = TimeframeState(h1_bars, placed_at, confirmed_pivots(h1_bars, placed_at, 3), 1, 1, 100, 0, 100, 100, 0)
        seen = {}

        def fake_score(direction, d1, h4, h1_state, vision_bonus, *, stop_entry=None, stop_pivots=None):
            pivots = stop_pivots if stop_pivots is not None else h1_state.pivots
            seen["stop"] = _latest_pivot_beyond(pivots, stop_entry.price, direction)
            return {}

        fill = Pivot(17, h1_bars[17].timestamp, 104.5, "high")
        with patch.object(pipeline, "_stop_entry_fill", return_value=fill),                 patch.object(pipeline, "_fill_placed_at", return_value=placed_at),                 patch.object(pipeline, "_resolve_indexes", return_value=(0, 0, placed_at)),                 patch.object(pipeline, "_states", return_value=(order_h1, order_h1, order_h1)),                 patch.object(pipeline, "_score_direction", side_effect=fake_score):
            pipeline._score_at_order_time(1, order_h1, order_h1, h1, 0)
        return seen["stop"]

    def test_fill_time_stop_uses_newer_higher_low(self):
        self.assertEqual(self.captured_stop(Params()), 97)

    def test_order_time_stop_keeps_older_low(self):
        self.assertEqual(self.captured_stop(Params(sl_at_fill=False)), 95)


if __name__ == "__main__":
    unittest.main()
