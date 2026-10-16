"""Execution-spec checks (docs/execution_spec.md).

Synthetic cases ported from scripts/audit_fidelity_20261008.py (audit 4-4,
4-5, 4-6, 4-7) and asserted with the corrected behavior. Strategy
conditions and thresholds are not under test here.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from oku100 import indicators
from oku100.models import Bar, Direction, Params, Pivot
from oku100.pipeline import DecisionPipeline, TimeframeState

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def clear_caches():
    for name in ("_PIVOT_CACHE", "_LINE_TOUCH_CACHE", "_PIVOT_PRICE_CACHE", "_SMA_CACHE", "_ATR_CACHE"):
        getattr(indicators, name).clear()


def state(price=100.0, trend=1, pivots=None):
    bars = [Bar(BASE, price, price + 1, price - 1, price)]
    return TimeframeState(bars, 0, pivots or [], trend, 1, price, trend, price, price, trend)


class GapFillTests(unittest.TestCase):
    """Audit 4-4: a stop order jumped by the open fills at the open."""

    def setUp(self):
        clear_caches()

    def _fill(self, direction, values):
        pipeline = DecisionPipeline(Params(N_h1=1))
        h1 = state()
        h1.bars = [Bar(BASE + timedelta(hours=i), *v) for i, v in enumerate(values)]
        h1.index = len(values) - 1
        with patch.object(pipeline, "_d_setup_ready_at", side_effect=lambda bars, index, d: index == 2):
            return pipeline._stop_entry_fill(h1, direction)

    def test_buy_gap_fills_at_open_not_pivot(self):
        fill = self._fill(1, [(99, 100, 98, 99), (99, 101, 98, 100), (99, 100, 98, 99), (105, 106, 104, 105)])
        self.assertIsNotNone(fill)
        self.assertEqual(fill.price, 105)

    def test_sell_gap_fills_at_open_not_pivot(self):
        fill = self._fill(-1, [(101, 102, 100, 101), (101, 102, 99, 100), (101, 102, 100, 101), (95, 96, 94, 95)])
        self.assertIsNotNone(fill)
        self.assertEqual(fill.price, 95)

    def test_intrabar_touch_fills_at_order_price(self):
        fill = self._fill(1, [(99, 100, 98, 99), (99, 101, 98, 100), (99, 100, 98, 99), (100, 102, 99, 101)])
        self.assertEqual(fill.price, 101)


class FillBarExitTests(unittest.TestCase):
    """Audit 4-7: SL/TP are examined from the fill bar itself."""

    def resolve(self, values, entry, stop, target, direction=Direction.LONG, m15=None):
        from oku100.backtest import _resolve_trade, group_m15_by_hour
        h1 = [Bar(BASE + timedelta(hours=i), *v) for i, v in enumerate(values)]
        grouped = group_m15_by_hour(m15) if m15 is not None else None
        return _resolve_trade(h1, 1, direction, entry, stop, target, m15_by_hour=grouped)

    def m15(self, values):
        return [Bar(BASE + timedelta(minutes=15 * i), *v) for i, v in enumerate(values)]

    def test_audit_case_is_no_longer_a_target(self):
        # Audit probe: fill 101 mid-bar, low 97 <= SL 98 on the fill bar, TP 104 next bar.
        trade = self.resolve([(100, 102, 97, 100), (100, 105, 99, 104)], 101, 98, 104)
        self.assertEqual(trade.reason, "stop_ambiguous")
        self.assertEqual(trade.exit_index, 0)
        self.assertEqual(trade.pnl_r, -1.0)

    def test_m15_resolves_stop_after_fill(self):
        path = self.m15([(100, 101.5, 99.5, 101), (101, 101.2, 97.5, 98), (98, 99, 97, 98.5), (98.5, 100.5, 98, 100)])
        trade = self.resolve([(100, 102, 97, 100), (100, 105, 99, 104)], 101, 98, 104, m15=path)
        self.assertEqual((trade.reason, trade.exit_index), ("stop", 0))

    def test_m15_resolves_stop_before_fill_as_no_exit(self):
        # Low prints before the order is reached; after the fill no SL/TP in that hour.
        path = self.m15([(100, 100.5, 97, 99), (99, 100, 98.5, 99.5), (99.5, 102, 99.4, 101.5), (101.5, 101.8, 100, 100)])
        trade = self.resolve([(100, 102, 97, 100), (100, 105, 99, 104)], 101, 98, 104, m15=path)
        self.assertEqual((trade.reason, trade.exit_index), ("target", 1))

    def test_m15_same_bar_fill_and_stop_stays_ambiguous(self):
        path = self.m15([(100, 101.5, 97, 100), (100, 100.5, 99, 100), (100, 101, 99.5, 100), (100, 100.5, 99.5, 100)])
        trade = self.resolve([(100, 102, 97, 100), (100, 105, 99, 104)], 101, 98, 104, m15=path)
        self.assertEqual(trade.reason, "stop_ambiguous")

    def test_missing_m15_is_ambiguous_stop(self):
        path = self.m15([(100, 101.5, 97, 100)])
        trade = self.resolve([(100, 102, 97, 100), (100, 105, 99, 104)], 101, 98, 104, m15=path)
        self.assertEqual(trade.reason, "stop_ambiguous")

    def test_target_on_fill_bar_after_midbar_fill_is_certain(self):
        trade = self.resolve([(100, 105, 99.5, 104), (104, 104, 90, 91)], 101, 98, 104)
        self.assertEqual((trade.reason, trade.exit_index), ("target", 0))
        self.assertAlmostEqual(trade.pnl_r, 1.0)

    def test_gap_fill_then_stop_on_fill_bar_is_certain(self):
        trade = self.resolve([(105, 106, 97, 98), (98, 120, 98, 119)], 105, 98, 119)
        self.assertEqual((trade.reason, trade.exit_index), ("stop", 0))

    def test_short_mirror(self):
        trade = self.resolve([(100, 103, 98, 100), (100, 101, 95, 96)], 99, 102, 96, direction=Direction.SHORT)
        self.assertEqual(trade.reason, "stop_ambiguous")

    def test_untouched_fill_bar_keeps_later_resolution(self):
        trade = self.resolve([(100, 102, 99, 101.5), (101.5, 105, 100, 104)], 101, 98, 104)
        self.assertEqual((trade.reason, trade.entry_index, trade.exit_index), ("target", 0, 1))

    def test_metrics_report_ambiguous_count(self):
        from oku100.backtest import metrics
        from oku100.models import Trade
        trades = [Trade(Direction.LONG, 0, 0, 101, 98, -1.0, "stop_ambiguous"),
                  Trade(Direction.LONG, 2, 3, 101, 104, 1.0, "target")]
        self.assertEqual(metrics(trades).ambiguous, 1)


class OrderTimeScoringTests(unittest.TestCase):
    """Audit 4-6: a fill-bar decision must not depend on that bar's close."""

    def setUp(self):
        clear_caches()
        from tests.helpers import bars
        self.d1 = bars(60, 24, 0.8)
        self.h4 = bars(100, 4, 0.4)
        self.h1 = bars(240, 1)

    def fill_bars(self):
        pipeline = DecisionPipeline()
        probe = TimeframeState(self.h1, len(self.h1) - 1, [], 0, 1, 100, 0, 100, 100, 0)
        found = []
        for direction in (1, -1):
            pipeline._stop_entry_fill(probe, direction)
            order = pipeline._stop_order_cache[(id(self.h1), direction)]
            found += [(i, order["fill_placed_at"][i]) for i in order["fills"]]
        return sorted(item for item in found if item[0] >= 48 and item[1] >= 48)

    @staticmethod
    def summary(decision):
        return (
            decision.direction, decision.confidence, decision.entry, decision.stop, decision.target,
            {k: (v.passed, v.evidence) for k, v in decision.criteria.items()},
        )

    def decide_with_close(self, index, close):
        clear_caches()
        h1 = list(self.h1)
        bar = h1[index]
        h1[index] = Bar(bar.timestamp, bar.open, max(bar.high, close), min(bar.low, close), close)
        return DecisionPipeline().evaluate(self.d1, self.h4, h1, as_of=bar.timestamp), h1

    def test_fixture_has_fills(self):
        self.assertTrue(self.fill_bars())

    def test_fill_bar_close_does_not_change_decision(self):
        for index, placed_at in self.fill_bars():
            with self.subTest(index=index):
                bar = self.h1[index]
                low, keep_low = self.decide_with_close(index, bar.low)
                high, keep_high = self.decide_with_close(index, bar.high)
                self.assertEqual(self.summary(low), self.summary(high))
                self.assertEqual(low.metadata["scored_at"], self.h1[placed_at].timestamp.isoformat())

    def test_non_fill_bar_is_scored_at_its_own_close(self):
        fills = {index for index, _ in self.fill_bars()}
        index = next(i for i in range(200, 239) if i not in fills)
        decision = DecisionPipeline().evaluate(self.d1, self.h4, self.h1, as_of=self.h1[index].timestamp)
        self.assertEqual(decision.metadata["scored_at"], self.h1[index].timestamp.isoformat())


class DistributionHigherTimeframeTests(unittest.TestCase):
    """Audit 4-5: the distribution path must not read unfinished D1/H4 bars."""

    def test_scan_distribution_uses_confirmed_higher_bars(self):
        from datetime import timedelta as td
        from oku100.distribution import scan_distribution
        from tests.helpers import bars
        clear_caches()
        d1, h4, h1 = bars(8, 24, 0.8), bars(40, 4, 0.4), bars(120, 1)
        calls = []
        original = DecisionPipeline._state

        def spy(pipeline, series, index, *args):
            calls.append((getattr(series, "_values", series), index))
            return original(pipeline, series, index, *args)

        with patch.object(DecisionPipeline, "_state", spy):
            scan_distribution(d1, h4, h1, Params(h1_direction_ma_period=48))
        # States are always built D1, H4, H1 in that order.
        checked = []
        for start in range(0, len(calls) - 2, 3):
            triple = calls[start:start + 3]
            self.assertEqual([source for source, _ in triple], [d1, h4, h1])
            checked.append(tuple(index for _, index in triple))
        self.assertTrue(checked)
        for d1_index, h4_index, h1_index in checked:
            confirmed_at = h1[h1_index].timestamp + td(hours=1)
            self.assertLessEqual(d1[d1_index].timestamp + td(days=1), confirmed_at)
            self.assertLessEqual(h4[h4_index].timestamp + td(hours=4), confirmed_at)
        # Audit case: the 2024-01-03 07:00 H1 bar sees the 01-02 daily bar, not 01-03.
        at_0700 = [item for item in checked if h1[item[2]].timestamp == BASE + td(days=2, hours=7)]
        self.assertTrue(at_0700)
        self.assertEqual({d1[item[0]].timestamp for item in at_0700}, {BASE + td(days=1)})


class SharedCandidateGateTests(unittest.TestCase):
    """Audit 4-1: one candidate function, gate selectable, used by both paths."""

    def audit_decision(self):
        # Audit probe: C fails, 76 points, D/F pass, SL/TP present.
        clear_caches()
        pipeline = DecisionPipeline()
        d1, h4, h1 = state(), state(), state()
        h1.pivots = [Pivot(0, BASE, 98, "low")]
        h4.pivots = [Pivot(0, BASE, 106, "high")]
        fill = lambda s, d: Pivot(0, BASE, 101, "high") if d == 1 else None
        convergence = {"contracted": True, "near": True, "min_distance_atr": 0.1}
        with patch.object(pipeline, "_stop_entry_fill", side_effect=fill), \
                patch.object(pipeline, "_h1_convergence", return_value=convergence):
            return pipeline._decide(d1, h4, h1, 0)

    def test_gates_are_selectable_and_differ_on_audit_case(self):
        from oku100.distribution import candidate_ready, classify
        decision = self.audit_decision()
        self.assertFalse(decision.criteria["C"].passed)
        self.assertTrue(candidate_ready(decision, "actionable"))
        self.assertFalse(candidate_ready(decision, "strict"))
        self.assertEqual(classify(decision, "actionable"), "entry_candidate")
        self.assertEqual(classify(decision), "trend_reversal")
        with self.assertRaises(ValueError):
            candidate_ready(decision, "other")

    def test_both_entry_points_call_the_shared_function(self):
        import oku100.backtest as backtest
        import oku100.distribution as distribution
        from tests.helpers import bars
        d1, h4, h1 = bars(60, 24, 0.8), bars(100, 4, 0.4), bars(240, 1)
        for gate in ("strict", "actionable"):
            with self.subTest(gate=gate):
                clear_caches()
                calls = []
                real = distribution.candidate_ready

                def spy(decision, g="strict"):
                    calls.append(g)
                    return real(decision, g)

                with patch.object(backtest, "candidate_ready", spy), \
                        patch.object(distribution, "candidate_ready", spy):
                    backtest.run_backtest(d1, h4, h1, Params(h1_direction_ma_period=120), warmup=120, gate=gate)
                    seen_backtest = set(calls)
                    calls.clear()
                    distribution.scan_distribution(d1, h4, h1, Params(h1_direction_ma_period=120), gate=gate)
                    seen_distribution = set(calls)
                self.assertEqual(seen_backtest, {gate})
                self.assertEqual(seen_distribution, {gate})

    def test_both_paths_default_to_adopted_strict_gate(self):
        # execution_spec 6: strict adopted on 2026-10-16.
        import inspect
        from oku100.backtest import run_backtest
        from oku100.distribution import scan_distribution
        self.assertEqual(inspect.signature(run_backtest).parameters["gate"].default, "strict")
        self.assertEqual(inspect.signature(scan_distribution).parameters["gate"].default, "strict")


if __name__ == "__main__":
    unittest.main()
