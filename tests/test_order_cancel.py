"""Pending stop-order cancellation on a break of the order-time stop level (execution_spec 4-1)."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from oku100 import indicators
from oku100.models import Bar, Params, Pivot
from oku100.pipeline import DecisionPipeline, TimeframeState

START = datetime(2024, 1, 1, tzinfo=timezone.utc)
# Closes stay below the long order (101) / above the short order (99) so the order is placed.
BASE = {1: [(99, 100, 98, 99)] * 3, -1: [(101, 102, 100, 101)] * 3}


def hour(i):
    return START + timedelta(hours=i)


def pivots_for(direction):
    # Long: order at the pivot high 101, cancel level = pivot low 95.
    # Short: order at the pivot low 99, cancel level = pivot high 105.
    if direction == 1:
        return [Pivot(0, hour(0), 95, "low"), Pivot(1, hour(1), 101, "high")]
    return [Pivot(0, hour(0), 105, "high"), Pivot(1, hour(1), 99, "low")]


def m15(i, values):
    return [Bar(hour(i) + timedelta(minutes=15 * k), *v) for k, v in enumerate(values)]


class OrderCancelTests(unittest.TestCase):
    def setUp(self):
        for name in ("_PIVOT_CACHE", "_SMA_CACHE", "_ATR_CACHE"):
            getattr(indicators, name).clear()

    def run_bars(self, direction, after, m15_bars=None, setup_at=(2,)):
        """Place at bar 2, then feed `after` bars. Returns (pipeline, fills by index)."""
        pipeline = DecisionPipeline(Params(N_h1=1), m15=m15_bars)
        bars = [Bar(hour(i), *v) for i, v in enumerate(BASE[direction] + list(after))]
        state = TimeframeState(bars, 2, [], direction, 1, 100, direction, 100, 100, direction)
        fills = {}
        with patch("oku100.pipeline.confirmed_pivots", return_value=pivots_for(direction)), \
                patch.object(pipeline, "_d_setup_ready_at", side_effect=lambda b, index, d: index in setup_at):
            for index in range(2, len(bars)):
                state.index = index
                fill = pipeline._stop_entry_fill(state, direction)
                if fill is not None:
                    fills[index] = fill.price
        return pipeline, fills

    def test_placement_records_stop_level(self):
        for direction, level in [(1, 95), (-1, 105)]:
            with self.subTest(direction=direction):
                pipeline, _ = self.run_bars(direction, [])
                order = next(iter(pipeline._stop_order_cache.values()))
                self.assertEqual(order["cancel_level"], level)

    def test_buy_break_cancels_before_later_touch(self):
        pipeline, fills = self.run_bars(1, [(97, 98, 94, 96), (99, 102, 98, 101)])
        self.assertEqual(fills, {})
        self.assertEqual(pipeline.cancel_stats["cancelled"], 1)

    def test_sell_break_cancels_before_later_touch(self):
        pipeline, fills = self.run_bars(-1, [(103, 106, 102, 104), (101, 102, 98, 99)])
        self.assertEqual(fills, {})
        self.assertEqual(pipeline.cancel_stats["cancelled"], 1)

    def test_touching_level_exactly_does_not_cancel(self):
        for direction, after, price in [
            (1, [(97, 98, 95, 96), (99, 102, 98, 101)], 101),
            (-1, [(103, 105, 102, 104), (101, 102, 98, 99)], 99),
        ]:
            with self.subTest(direction=direction):
                pipeline, fills = self.run_bars(direction, after)
                self.assertEqual(fills, {4: price})
                self.assertEqual(pipeline.cancel_stats["cancelled"], 0)

    def test_same_bar_open_through_order_fills(self):
        pipeline, fills = self.run_bars(1, [(101.5, 102, 94, 95)])
        self.assertEqual(fills, {3: 101.5})
        self.assertEqual(pipeline.cancel_stats["same_bar_resolved"], 1)

    def test_same_bar_open_through_level_cancels(self):
        pipeline, fills = self.run_bars(1, [(94.5, 102, 94, 101)])
        self.assertEqual(fills, {})
        self.assertEqual(pipeline.cancel_stats["cancelled"], 1)

    def test_same_bar_m15_fill_first(self):
        sub = m15(3, [(97, 101.5, 96.5, 101), (101, 101.2, 98, 98), (98, 98, 94, 95), (95, 96, 95, 96)])
        pipeline, fills = self.run_bars(1, [(97, 101.5, 94, 96)], m15_bars=sub)
        self.assertEqual(fills, {3: 101})
        self.assertEqual(pipeline.cancel_stats["same_bar_resolved"], 1)

    def test_same_bar_m15_break_first(self):
        sub = m15(3, [(97, 97.5, 94, 95), (95, 99, 95, 98), (98, 101.5, 97, 101), (101, 101, 96, 96)])
        pipeline, fills = self.run_bars(1, [(97, 101.5, 94, 96)], m15_bars=sub)
        self.assertEqual(fills, {})
        self.assertEqual(pipeline.cancel_stats["cancelled"], 1)

    def test_same_bar_sell_m15_break_first(self):
        sub = m15(3, [(103, 106, 102.5, 105), (105, 105, 101, 101), (101, 101, 98.5, 99), (99, 104, 99, 104)])
        pipeline, fills = self.run_bars(-1, [(103, 106, 98.5, 104)], m15_bars=sub)
        self.assertEqual(fills, {})
        self.assertEqual(pipeline.cancel_stats["cancelled"], 1)

    def test_same_bar_without_m15_is_ambiguous_fill(self):
        pipeline, fills = self.run_bars(1, [(97, 101.5, 94, 96)])
        self.assertEqual(fills, {3: 101})
        self.assertEqual(pipeline.cancel_stats["same_bar_ambiguous"], 1)

    def test_same_m15_bar_both_is_ambiguous_fill(self):
        sub = m15(3, [(97, 101.5, 94, 96), (96, 97, 95, 96), (96, 97, 95, 96), (96, 97, 95, 96)])
        pipeline, fills = self.run_bars(1, [(97, 101.5, 94, 96)], m15_bars=sub)
        self.assertEqual(fills, {3: 101})
        self.assertEqual(pipeline.cancel_stats["same_bar_ambiguous"], 1)

    def test_new_setup_after_cancel_places_fresh_order(self):
        pipeline, fills = self.run_bars(
            1, [(97, 98, 94, 96), (96, 97, 95.5, 96), (99, 102, 98, 101)], setup_at=(2, 4),
        )
        self.assertEqual(pipeline.cancel_stats["cancelled"], 1)
        self.assertEqual(fills, {5: 101})


if __name__ == "__main__":
    unittest.main()
