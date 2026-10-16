"""Execution-price regression checks; strategy setup is held fixed."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from oku100 import indicators
from oku100.models import Bar, Params, Pivot
from oku100.pipeline import DecisionPipeline, TimeframeState


class StopGapExecutionTests(unittest.TestCase):
    def setUp(self):
        # Existing indicator caches key by list identity. Isolate each fixture.
        for name in ("_PIVOT_CACHE", "_SMA_CACHE", "_ATR_CACHE"):
            getattr(indicators, name).clear()
        self.start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    def state(self, direction, last):
        # The middle high (long) / low (short) is confirmed at index 2.
        values = (
            [(99, 100, 98, 99), (99, 101, 98, 100), (99, 100, 98, 99)]
            if direction == 1 else
            [(101, 102, 100, 101), (101, 102, 99, 100), (101, 102, 100, 101)]
        )
        bars = [Bar(self.start + timedelta(hours=i), *v) for i, v in enumerate(values + [last])]
        return TimeframeState(bars, 3, [], direction, 1, 100, direction, 100, 100, direction)

    def fill(self, direction, last):
        pipeline = DecisionPipeline(Params(N_h1=1))
        state = self.state(direction, last)
        with patch.object(pipeline, "_d_setup_ready_at", side_effect=lambda bars, index, d: index == 2):
            state.index = 2
            self.assertIsNone(pipeline._stop_entry_fill(state, direction))
            pending = pipeline._stop_order_cache[(id(state.bars), direction)]["active"]
            self.assertIsNotNone(pending)
            state.index = 3
            fill = pipeline._stop_entry_fill(state, direction)
            self.assertEqual(pending.price, 101 if direction == 1 else 99)
            self.assertIs(pipeline._stop_entry_fill(state, direction), fill)
        return pipeline, state, fill

    def test_buy_gap_fills_at_open(self):
        _, _, fill = self.fill(1, (105, 106, 104, 105))
        self.assertEqual(fill.price, 105)

    def test_sell_gap_fills_at_open(self):
        _, _, fill = self.fill(-1, (95, 96, 94, 95))
        self.assertEqual(fill.price, 95)

    def test_buy_normal_touch_fills_at_order(self):
        _, _, fill = self.fill(1, (100, 102, 99, 101))
        self.assertEqual(fill.price, 101)

    def test_sell_normal_touch_fills_at_order(self):
        _, _, fill = self.fill(-1, (100, 101, 98, 99))
        self.assertEqual(fill.price, 99)

    def test_open_exactly_at_order(self):
        for direction, bar, expected in [(1, (101, 102, 100, 101), 101), (-1, (99, 100, 98, 99), 99)]:
            with self.subTest(direction=direction):
                self.setUp()
                _, _, fill = self.fill(direction, bar)
                self.assertEqual(fill.price, expected)

    def test_unreached_orders_do_not_fill(self):
        for direction, bar in [(1, (99, 100, 98, 99)), (-1, (101, 102, 100, 101))]:
            with self.subTest(direction=direction):
                self.setUp()
                _, _, fill = self.fill(direction, bar)
                self.assertIsNone(fill)

    def test_filled_order_is_not_reused_on_next_bar(self):
        pipeline, state, fill = self.fill(1, (105, 106, 104, 105))
        self.assertIsNotNone(fill)
        state.bars.append(Bar(self.start + timedelta(hours=4), 105, 107, 103, 106))
        state.index = 4
        with patch.object(pipeline, "_d_setup_ready_at", return_value=False):
            self.assertIsNone(pipeline._stop_entry_fill(state, 1))

    def test_gap_fill_propagates_to_entry_and_rr(self):
        pipeline, h1, fill = self.fill(1, (105, 106, 104, 105))
        h1.pivots = [Pivot(0, self.start, 98, "low")]
        h4 = self.state(1, (105, 106, 104, 105))
        h4.pivots = [Pivot(0, self.start, 120, "high")]
        d1 = self.state(1, (105, 106, 104, 105))
        result = pipeline._score_direction(1, d1, h4, h1, 0)
        self.assertEqual(result["entry"], 105)
        self.assertEqual(result["stop"], 98)
        self.assertEqual(result["target"], 120)
        self.assertAlmostEqual(result["rr"], 15 / 7)


if __name__ == "__main__":
    unittest.main()
