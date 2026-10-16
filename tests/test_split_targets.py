"""Split take-profit (docs/execution_spec.md 7)."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from oku100 import indicators
from oku100.backtest import _resolve_trade, group_m15_by_hour
from oku100.models import Bar, Direction, Params, Pivot
from oku100.pipeline import DecisionPipeline, TimeframeState

START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def clear_caches():
    for name in ("_PIVOT_CACHE", "_SMA_CACHE", "_ATR_CACHE"):
        getattr(indicators, name).clear()


def state(pivot_prices, fast_ma, close, count=100):
    """Flat bars at `close` (so every SMA equals `close`) with the given pivots."""
    bars = [Bar(START + timedelta(hours=4 * i), close, close, close, close) for i in range(count)]
    pivots = [Pivot(i, START, price, "high") for i, price in enumerate(pivot_prices)]
    return TimeframeState(bars, count - 1, pivots, 0, 1.0, fast_ma, 0.0, close, close, 0.0)


class SplitTargetSelectionTests(unittest.TestCase):
    def setUp(self):
        clear_caches()
        self.pipeline = DecisionPipeline()

    def targets(self, h4, d1, entry=100.0, direction=1):
        # Selection logic only: every H4 pivot is treated as a 7-3 line here.
        lines = [pivot.price for pivot in h4.pivots]
        with patch.object(self.pipeline, "_h4_lines", return_value=lines):
            return self.pipeline._split_targets(d1, h4, entry, direction)

    def assertLevels(self, targets, levels, direction=1):
        buffer = 1 - direction * 0.003
        self.assertEqual(len(targets), len(levels))
        for (price, fraction), level in zip(targets, levels):
            self.assertAlmostEqual(price, level * buffer)
            self.assertAlmostEqual(fraction, 1 / len(levels))

    def test_two_h4_targets_and_one_d1_target_split_in_thirds(self):
        # H4 MAs (fast 90, SMA80 = close 90) lie behind a long entry.
        h4 = state([103, 106, 110], fast_ma=90, close=90)
        d1 = state([104, 108, 115], fast_ma=80, close=80)
        self.assertLevels(self.targets(h4, d1), [103, 106, 108])

    def test_trigger_line_within_zone_is_excluded(self):
        h4 = state([100.3, 103, 106], fast_ma=90, close=90)
        d1 = state([120], fast_ma=80, close=80)
        self.assertLevels(self.targets(h4, d1), [103, 106, 120])

    def test_near_line_beyond_zone_is_not_skipped(self):
        h4 = state([100.6, 106], fast_ma=90, close=90)
        d1 = state([120], fast_ma=80, close=80)
        self.assertLevels(self.targets(h4, d1), [100.6, 106, 120])

    def test_overlapping_line_and_ma_merge_to_nearer_price(self):
        # H4 80SMA (close) at 103.3 overlaps the 103 line.
        h4 = state([103, 108], fast_ma=90, close=103.3)
        d1 = state([120], fast_ma=80, close=80)
        self.assertLevels(self.targets(h4, d1), [103, 108, 120])

    def test_h4_ma_can_be_first_target(self):
        h4 = state([110], fast_ma=102, close=90)
        d1 = state([120], fast_ma=80, close=80)
        self.assertLevels(self.targets(h4, d1), [102, 110, 120])

    def test_d1_structure_inside_h4_targets_gives_no_t3(self):
        h4 = state([103, 106], fast_ma=90, close=90)
        d1 = state([104, 106.2], fast_ma=80, close=80)
        self.assertLevels(self.targets(h4, d1), [103, 106])

    def test_d1_ma_can_be_final_target(self):
        h4 = state([103], fast_ma=90, close=90)
        d1 = state([], fast_ma=112, close=80)
        self.assertLevels(self.targets(h4, d1), [103, 112])

    def test_no_h4_structure_returns_empty(self):
        h4 = state([95], fast_ma=90, close=90)
        d1 = state([120], fast_ma=80, close=80)
        self.assertEqual(self.targets(h4, d1), [])

    def test_short_mirror(self):
        h4 = state([97, 94, 90], fast_ma=110, close=110)
        d1 = state([92, 85], fast_ma=120, close=120)
        self.assertLevels(self.targets(h4, d1, direction=-1), [97, 94, 92], direction=-1)


class H4LineDefinitionTests(unittest.TestCase):
    """execution_spec 7-3: only rejected pivots touched twice, or shared with D1, are lines."""

    def setUp(self):
        clear_caches()
        self.pipeline = DecisionPipeline()

    def lines(self, h4_prices, d1_prices, rejected):
        h4 = state(h4_prices, fast_ma=90, close=90)
        h4.atr = 1.0  # tolerance = k2 (0.4) x ATR
        d1 = state(d1_prices, fast_ma=80, close=80)
        reaction = lambda _state, pivot: 1.0 if pivot.price in rejected else 0.5
        with patch.object(self.pipeline, "_pivot_reaction_atr", side_effect=reaction):
            return self.pipeline._h4_lines(d1, h4)

    def test_two_rejected_touches_make_a_line(self):
        self.assertEqual(self.lines([103, 103.3, 106], [], {103, 103.3, 106}), [103, 103.3])

    def test_unrejected_touch_does_not_count(self):
        self.assertEqual(self.lines([103, 103.3], [], {103}), [])

    def test_touches_beyond_tolerance_are_separate(self):
        self.assertEqual(self.lines([103, 103.5], [], {103, 103.5}), [])

    def test_rejected_pivot_shared_with_d1_is_a_line(self):
        self.assertEqual(self.lines([103, 106], [106.2], {103, 106}), [106])

    def test_single_minor_swing_is_not_a_line(self):
        self.assertEqual(self.lines([101.5], [], {101.5}), [])


class SplitTargetDecisionTests(unittest.TestCase):
    """F and the single target stay as before; only the exit orders are added."""

    def test_split_targets_do_not_change_scoring(self):
        from tests.helpers import bars
        d1, h4, h1 = bars(220, 24, 0.8), bars(400, 4, 0.4), bars(1000, 1)
        found = 0
        for direction in (1, -1):
            results = []
            for split in (True, False):
                clear_caches()
                pipeline = DecisionPipeline(Params(split_targets=split))
                states = pipeline._states((d1, h4, h1), (200, 380, 990))
                results.append(pipeline._score_direction(direction, *states, 0, stop_entry=None))
            on, off = results
            found += bool(on["targets"])
            self.assertEqual(off["targets"], [])
            for key in ("entry", "stop", "target", "rr", "confidence"):
                self.assertEqual(on[key], off[key])
            self.assertEqual(
                {k: (v.passed, v.evidence) for k, v in on["criteria"].items()},
                {k: (v.passed, v.evidence) for k, v in off["criteria"].items()},
            )
        self.assertTrue(found)


class SplitTargetExitTests(unittest.TestCase):
    TARGETS = [(103.0, 1 / 3), (106.0, 1 / 3), (110.0, 1 / 3)]

    def resolve(self, values, entry=100.0, stop=98.0, targets=TARGETS, direction=Direction.LONG, m15=None):
        h1 = [Bar(START + timedelta(hours=i), *v) for i, v in enumerate(values)]
        grouped = group_m15_by_hour(m15) if m15 is not None else None
        return _resolve_trade(h1, 1, direction, entry, stop, targets[0][0], m15_by_hour=grouped, targets=targets)

    def m15(self, values):
        return [Bar(START + timedelta(minutes=15 * i), *v) for i, v in enumerate(values)]

    def test_all_targets_reached_over_several_bars(self):
        trade = self.resolve([(99, 100.5, 99, 100), (100, 103.5, 99.5, 103), (103, 107, 102, 106), (106, 111, 105, 110)])
        self.assertEqual(trade.reason, "target")
        self.assertEqual(trade.exit_index, 3)
        self.assertAlmostEqual(trade.pnl_r, (1.5 + 3 + 5) / 3)
        self.assertEqual([leg[0] for leg in trade.legs], [1, 2, 3])

    def test_one_bar_reaching_two_targets_fills_both(self):
        trade = self.resolve([(99, 100.5, 99, 100), (100, 107, 99.5, 106), (106, 106, 97, 97)])
        self.assertEqual(trade.reason, "partial_stop")
        self.assertAlmostEqual(trade.pnl_r, (1.5 + 3 - 1) / 3)
        self.assertEqual([(leg[0], leg[3]) for leg in trade.legs], [(1, "target"), (1, "target"), (2, "stop")])

    def test_later_bar_with_stop_and_target_stops_the_remainder(self):
        trade = self.resolve([(99, 100.5, 99, 100), (100, 104, 97, 100)])
        self.assertEqual(trade.reason, "stop")
        self.assertAlmostEqual(trade.pnl_r, -1.0)

    def test_fill_bar_midbar_fill_reaching_targets_without_stop(self):
        trade = self.resolve([(99, 106.5, 99, 106), (106, 106, 97, 97)])
        self.assertEqual([(leg[0], leg[3]) for leg in trade.legs], [(0, "target"), (0, "target"), (1, "stop")])
        self.assertEqual(trade.entry_index, 0)

    def test_fill_bar_m15_orders_target_before_stop(self):
        path = self.m15([(99, 100.5, 99, 100.2), (100.2, 103.5, 100, 103), (103, 103, 97.5, 98), (98, 99, 97.5, 98)])
        trade = self.resolve([(99, 103.5, 97.5, 98), (98, 120, 98, 119)], m15=path)
        self.assertEqual(trade.reason, "partial_stop")
        self.assertEqual(trade.exit_index, 0)
        self.assertAlmostEqual(trade.pnl_r, (1.5 - 2) / 3)

    def test_fill_bar_without_m15_is_ambiguous_stop(self):
        trade = self.resolve([(99, 103.5, 97.5, 98), (98, 120, 98, 119)])
        self.assertEqual(trade.reason, "stop_ambiguous")
        self.assertAlmostEqual(trade.pnl_r, -1.0)

    def test_gap_through_target_fills_at_target_price(self):
        trade = self.resolve([(99, 100.5, 99, 100), (104, 104.5, 103.8, 104), (104, 104, 97, 97)])
        self.assertEqual(trade.legs[0][1], 103.0)

    def test_end_of_data_closes_remainder(self):
        trade = self.resolve([(99, 100.5, 99, 100), (100, 104, 99.5, 104)])
        self.assertEqual(trade.reason, "end_of_data")
        self.assertAlmostEqual(trade.pnl_r, (1.5 + 2 + 2) / 3)

    def test_short_mirror(self):
        targets = [(97.0, 0.5), (94.0, 0.5)]
        trade = self.resolve([(101, 101, 99.5, 100), (100, 100.5, 96.5, 97), (97, 97.5, 93, 94)],
                             stop=102.0, targets=targets, direction=Direction.SHORT)
        self.assertEqual(trade.reason, "target")
        self.assertAlmostEqual(trade.pnl_r, (1.5 + 3) / 2)

    def test_without_targets_matches_single_target(self):
        values = [(99, 100.5, 99, 100), (100, 104, 99.5, 103.5)]
        h1 = [Bar(START + timedelta(hours=i), *v) for i, v in enumerate(values)]
        single = _resolve_trade(h1, 1, Direction.LONG, 100.0, 98.0, 103.0)
        split = _resolve_trade(h1, 1, Direction.LONG, 100.0, 98.0, 103.0, targets=[(103.0, 1.0)])
        self.assertEqual((single.reason, single.pnl_r, single.exit), ("target", 1.5, 103.0))
        self.assertEqual((split.reason, split.pnl_r, split.exit), (single.reason, single.pnl_r, single.exit))


if __name__ == "__main__":
    unittest.main()
