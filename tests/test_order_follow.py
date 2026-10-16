"""Pending stop order follows a newer, nearer H1 pivot (execution_spec 4-2)."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from oku100 import indicators
from oku100.models import Bar, Params, Pivot
from oku100.pipeline import DecisionPipeline, TimeframeState

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def hour(i):
    return START + timedelta(hours=i)


class OrderFollowTests(unittest.TestCase):
    """Long order placed at bar 2 on the pivot high 105 (cancel level 95).

    `later` maps a bar index to the pivot list confirmed from that bar on.
    """

    BASE = [(99, 100, 98, 99)] * 3
    PLACED = [Pivot(0, hour(0), 95, "low"), Pivot(1, hour(1), 105, "high")]

    def setUp(self):
        for name in ("_PIVOT_CACHE", "_SMA_CACHE", "_ATR_CACHE"):
            getattr(indicators, name).clear()

    def run_bars(self, after, later=None, params=None):
        later = later or {}
        pipeline = DecisionPipeline(params or Params(N_h1=1))
        bars = [Bar(hour(i), *v) for i, v in enumerate(self.BASE + list(after))]
        state = TimeframeState(bars, 2, [], 1, 1, 100, 1, 100, 100, 1)

        def pivots(_bars, index, _width):
            current = self.PLACED
            for start in sorted(later):
                if index >= start:
                    current = later[start]
            return current

        fills = {}
        with patch("oku100.pipeline.confirmed_pivots", side_effect=pivots), \
                patch.object(pipeline, "_d_setup_ready_at", side_effect=lambda b, index, d: index == 2):
            for index in range(2, len(bars)):
                state.index = index
                fill = pipeline._stop_entry_fill(state, 1)
                if fill is not None:
                    fills[index] = fill.price
        order = pipeline._stop_order_cache[(id(bars), 1)]
        return pipeline, order, fills

    def newer(self, price, index=3):
        return self.PLACED + [Pivot(index, hour(index), 99, "low"), Pivot(index, hour(index), price, "high")]

    def test_newer_lower_high_moves_the_order(self):
        _, order, fills = self.run_bars(
            [(100, 101, 99, 100), (100, 102.5, 99.5, 101)], later={3: self.newer(102)},
        )
        self.assertEqual(fills, {4: 102})
        self.assertEqual(order["placed_at"], 2)

    def test_moved_order_does_not_fill_on_the_moving_bar(self):
        # Bar 3 reaches 102 but the move only applies from bar 4.
        _, _, fills = self.run_bars(
            [(100, 102.5, 99, 101), (101, 101.5, 100, 101)], later={3: self.newer(102)},
        )
        self.assertEqual(fills, {})

    def test_newer_higher_pivot_does_not_move(self):
        _, order, fills = self.run_bars(
            [(100, 101, 99, 100), (100, 106, 99.5, 105.5)], later={3: self.newer(107)},
        )
        self.assertEqual(fills, {4: 105})
        self.assertEqual(order["moved_at"], -1)

    def test_pivot_behind_close_does_not_move(self):
        _, order, _ = self.run_bars([(102, 103, 101.5, 102.5)], later={3: self.newer(102)})
        self.assertEqual(order["active"].price, 105)

    def test_follow_disabled_keeps_order_price(self):
        _, _, fills = self.run_bars(
            [(100, 101, 99, 100), (100, 106, 99.5, 105.5)], later={3: self.newer(102)},
            params=Params(N_h1=1, order_follow=False),
        )
        self.assertEqual(fills, {4: 105})

    def test_moves_are_counted(self):
        pipeline, _, _ = self.run_bars([(100, 101, 99, 100)], later={3: self.newer(102)})
        self.assertEqual(pipeline.cancel_stats["moved"], 1)

    def test_cancel_level_follows_the_newer_low(self):
        _, order, _ = self.run_bars([(100, 101, 99.5, 100)], later={3: self.newer(102)})
        self.assertEqual(order["cancel_level"], 99)

    def test_cancel_level_fixed_when_disabled(self):
        _, order, _ = self.run_bars(
            [(100, 101, 99.5, 100)], later={3: self.newer(102)}, params=Params(N_h1=1, cancel_follow=False),
        )
        self.assertEqual(order["cancel_level"], 95)

    def test_break_of_newer_low_cancels_before_old_level(self):
        # Newer low 99 confirmed at bar 3; bar 4 dips to 98.5 (above the old 95): cancelled.
        pipeline, order, fills = self.run_bars(
            [(100, 101, 99.5, 100), (100, 100.5, 98.5, 99), (99, 106, 99, 105.5)],
            later={3: self.newer(102)},
        )
        self.assertEqual(fills, {})
        self.assertEqual(pipeline.cancel_stats["cancelled"], 1)

    def test_old_level_kept_without_cancel_follow_fills_later(self):
        _, _, fills = self.run_bars(
            [(100, 101, 99.5, 100), (100, 100.5, 98.5, 99), (99, 106, 99, 105.5)],
            later={3: self.newer(102)}, params=Params(N_h1=1, cancel_follow=False),
        )
        self.assertEqual(fills, {5: 102})


if __name__ == "__main__":
    unittest.main()
