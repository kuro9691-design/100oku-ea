import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from oku100.backtest import run_backtest
from oku100.distribution import classify
from oku100.models import Bar, Criterion, Decision, Direction, Params, Pivot
from oku100.pipeline import DecisionPipeline, TimeframeState

from tests.helpers import bars


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.h1 = bars(240, 1)
        self.h4 = bars(100, 4, 0.4)
        self.d1 = bars(60, 24, 0.8)

    def test_decision_has_all_criteria(self):
        params = Params()
        self.assertEqual(
            (
                params.h1_fast_ma_period,
                params.h1_slow_ma_period,
                params.h1_direction_ma_period,
                params.h4_fast_ma_period,
                params.h4_direction_ma_period,
                params.d1_fast_ma_period,
                params.d1_direction_ma_period,
            ),
            (20, 80, 720, 20, 180, 30, 140),
        )
        self.assertFalse(params.use_weekend_filter)
        self.assertFalse(params.use_economic_event_filter)
        self.assertEqual(params.line_touch_min, 2)
        self.assertEqual(params.strong_line_touch_min, 3)
        self.assertEqual(params.strong_pivot_reaction_atr, 1.0)
        decision = DecisionPipeline().evaluate(self.d1, self.h4, self.h1)
        self.assertEqual(set(decision.criteria), {"A", "B", "B-2", "C", "D", "E", "F", "G"})
        self.assertIn("H1_turn=", decision.criteria["A"].evidence)
        self.assertIn("H4=", decision.criteria["A"].evidence)
        self.assertIn("D1_exception=", decision.criteria["A"].evidence)
        self.assertIn("H1_20_80_contracted=", decision.criteria["B"].evidence)
        self.assertIn("all_direction_aligned", decision.metadata)
        self.assertLessEqual(decision.metadata["access_audit"]["H1"], len(self.h1) - 1)

    def test_backtest_splits_is_and_oos(self):
        result = run_backtest(self.d1, self.h4, self.h1, warmup=120)
        self.assertGreater(result.split_timestamp, self.h1[0].timestamp)
        self.assertGreaterEqual(result.in_sample.trades, 0)
        self.assertGreaterEqual(result.out_of_sample.trades, 0)

    def test_alignment_allows_daily_ma_room_exception(self):
        pipeline = DecisionPipeline()
        d1 = self._state(trend=-1, fast_ma=110, fast_slope=-1)
        h4 = self._state(trend=1, fast_ma=101, fast_slope=1)
        h1 = self._state(trend=1, fast_ma=101, fast_slope=1)
        alignment = pipeline._alignment(d1, h4, h1, 1)
        self.assertTrue(alignment["passed"])
        self.assertTrue(alignment["d1_exception"])

    def test_alignment_requires_h1_dow_turn(self):
        pipeline = DecisionPipeline()
        d1 = self._state(trend=1, fast_ma=101, fast_slope=1)
        h4 = self._state(trend=1, fast_ma=101, fast_slope=1)
        h1 = self._state(trend=-1, fast_ma=101, fast_slope=1)
        self.assertFalse(pipeline._alignment(d1, h4, h1, 1)["passed"])

    def test_weak_pivot_is_not_a_structural_line(self):
        pipeline = DecisionPipeline()
        state = self._state(trend=1, fast_ma=101, fast_slope=1)
        state.pivots = [Pivot(0, state.bars[0].timestamp, 101, "high")]
        self.assertIsNone(pipeline._structural_line(state, 100, 1)["line"])

    def test_g_warning_does_not_remove_entry_candidate(self):
        criteria = {
            name: Criterion(name, True, 0, "")
            for name in ("A", "B", "B-2", "C", "D", "E", "F")
        }
        criteria["G"] = Criterion("G", False, 0, "strong_line_ahead")
        decision = Decision(
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            direction=Direction.LONG,
            pattern="test",
            confidence=80,
            criteria=criteria,
            pass_reasons=[],
            warning_flags=["strong_line_ahead"],
            entry=100,
            stop=99,
            target=102,
            rr=2,
            metadata={"all_direction_aligned": True},
        )
        self.assertEqual(classify(decision), "entry_candidate")
        self.assertTrue(decision.actionable)
        self.assertFalse(decision.clean_candidate)

    def test_e_allows_h4_dow_unconfirmed_when_h4_flow_matches(self):
        pipeline = DecisionPipeline()
        d1 = self._state(trend=1, fast_ma=101, fast_slope=1)
        h4 = self._state(trend=0, fast_ma=101, fast_slope=1)
        h1 = self._state(trend=1, fast_ma=101, fast_slope=1)
        # Pivots only establish the required H1-inside-H4 relationship.
        h4.pivots = [Pivot(0, h4.bars[0].timestamp, 99, "low")]
        h1.pivots = [Pivot(0, h1.bars[0].timestamp, 99, "low")]
        result = pipeline._score_direction(1, d1, h4, h1, 0.0)
        self.assertTrue(result["criteria"]["E"].passed)

    def test_stop_entry_fills_at_confirmed_pivot_on_first_later_touch(self):
        pipeline = DecisionPipeline(Params(N_h1=1))
        state = self._state(trend=1, fast_ma=101, fast_slope=1)
        timestamps = [
            datetime(2026, 1, day, tzinfo=timezone.utc)
            for day in range(1, 5)
        ]
        state.bars = [
            Bar(timestamps[0], 99, 100, 98, 99),
            Bar(timestamps[1], 99, 101, 98, 100),
            Bar(timestamps[2], 99, 100, 98, 99),
            Bar(timestamps[3], 99, 101, 98, 100),
        ]
        state.index = 3
        state.pivots = [Pivot(1, timestamps[1], 101, "high")]
        with patch.object(pipeline, "_d_setup_ready_at", side_effect=lambda bars, index, direction: index == 2):
            fill = pipeline._stop_entry_fill(state, 1)
        self.assertIsNotNone(fill)
        self.assertEqual(fill.price, 101)

    def test_stop_entry_does_not_fill_twice_at_same_pivot(self):
        pipeline = DecisionPipeline(Params(N_h1=1))
        state = self._state(trend=1, fast_ma=101, fast_slope=1)
        timestamps = [
            datetime(2026, 1, day, tzinfo=timezone.utc)
            for day in range(1, 6)
        ]
        state.bars = [
            Bar(timestamps[0], 99, 100, 98, 99),
            Bar(timestamps[1], 99, 101, 98, 100),
            Bar(timestamps[2], 99, 100, 98, 99),
            Bar(timestamps[3], 99, 101, 98, 100),
            Bar(timestamps[4], 99, 102, 98, 101),
        ]
        state.index = 4
        state.pivots = [Pivot(1, timestamps[1], 101, "high")]
        with patch.object(pipeline, "_d_setup_ready_at", side_effect=lambda bars, index, direction: index == 2):
            self.assertIsNone(pipeline._stop_entry_fill(state, 1))

    def test_d_requires_ma720_slope_aligned(self):
        pipeline = DecisionPipeline()
        d1 = self._state(trend=1, fast_ma=101, fast_slope=1)
        h4 = self._state(trend=1, fast_ma=101, fast_slope=1)
        dummy_pivot = Pivot(0, datetime(2026, 1, 1, tzinfo=timezone.utc), 105, "high")

        h1_up = self._state(trend=1, fast_ma=101, fast_slope=1)
        h1_up.direction_slope = 0.1  # MA720 上向き → long と一致
        with patch.object(pipeline, "_stop_entry_fill", return_value=dummy_pivot):
            self.assertTrue(
                pipeline._score_direction(1, d1, h4, h1_up, 0.0)["criteria"]["D"].passed
            )

        h1_dn = self._state(trend=1, fast_ma=101, fast_slope=1)
        h1_dn.direction_slope = -0.1  # MA720 下向き → long と不一致
        with patch.object(pipeline, "_stop_entry_fill", return_value=dummy_pivot):
            self.assertFalse(
                pipeline._score_direction(1, d1, h4, h1_dn, 0.0)["criteria"]["D"].passed
            )

        h1_flat = self._state(trend=1, fast_ma=101, fast_slope=1)
        h1_flat.direction_slope = 0.0  # MA720 横ばい → 不一致（レンジ除外）
        with patch.object(pipeline, "_stop_entry_fill", return_value=dummy_pivot):
            self.assertFalse(
                pipeline._score_direction(1, d1, h4, h1_flat, 0.0)["criteria"]["D"].passed
            )

    def test_stop_entry_can_be_rearmed_after_an_earlier_touch(self):
        pipeline = DecisionPipeline(Params(N_h1=1))
        state = self._state(trend=1, fast_ma=101, fast_slope=1)
        timestamps = [
            datetime(2026, 1, day, tzinfo=timezone.utc)
            for day in range(1, 7)
        ]
        state.bars = [
            Bar(timestamps[0], 99, 100, 98, 99),
            Bar(timestamps[1], 99, 101, 98, 100),
            Bar(timestamps[2], 99, 100, 98, 99),
            Bar(timestamps[3], 99, 101, 98, 100),
            Bar(timestamps[4], 99, 100, 98, 99),
            Bar(timestamps[5], 99, 102, 98, 101),
        ]
        state.index = 5
        state.pivots = [Pivot(1, timestamps[1], 101, "high")]
        with patch.object(pipeline, "_d_setup_ready_at", side_effect=lambda bars, index, direction: index == 4):
            self.assertIsNotNone(pipeline._stop_entry_fill(state, 1))

    @staticmethod
    def _state(trend: int, fast_ma: float, fast_slope: float) -> TimeframeState:
        bar = Bar(datetime(2026, 1, 1, tzinfo=timezone.utc), 100, 101, 99, 100)
        return TimeframeState(
            bars=[bar],
            index=0,
            pivots=[],
            trend=trend,
            atr=1,
            fast_ma=fast_ma,
            fast_ma_slope=fast_slope,
            slow_ma=100,
            direction_ma=100,
            direction_slope=0,
        )
